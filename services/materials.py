"""
Сервис склада: номенклатура материалов и их движение.

Остаток материала меняется только тремя операциями:
- receive()      - приход от поставщика (пересчитывает учётную цену
                   по средневзвешенной);
- write_off()    - расход на строительный объект;
- return_stock() - возврат неиспользованного материала с объекта.

Каждая операция записывает строку в журнал Movement и меняет остаток
в одной транзакции: либо выполняется всё, либо ничего.

Остаток меняется одной командой UPDATE с условием прямо в SQL
(«уменьшить, если хватает»). Вариант «прочитать остаток в Python,
вычесть, записать» при одновременной работе нескольких пользователей
терял изменения: стресс-тест показал 150 выданных штук при остатке 100.
"""
from datetime import date
from typing import List, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import selectinload

from config import CONFIG
from database import Material, Movement, Object, session_scope
from logger import log
from validators import (
    validate_code, validate_name, validate_price, validate_qty,
)


class StockError(ValueError):
    """Операция невозможна из-за остатка (недостаточно на складе)."""


def _check(*results) -> None:
    """Поднять ValueError по первой неуспешной проверке."""
    for ok, msg in results:
        if not ok:
            raise ValueError(msg)


# ===== Номенклатура =====
def list_materials(search: str = "", category: str = "Все") -> List[Material]:
    """Список материалов с фильтром по названию/артикулу и категории.

    Фильтрация выполняется на стороне СУБД.
    """
    stmt = select(Material).order_by(Material.category, Material.name)
    q = (search or "").strip()
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower_ru(Material.name).like(like),
                              func.lower_ru(Material.code).like(like)))
    if category and category != "Все":
        stmt = stmt.where(Material.category == category)
    with session_scope() as s:
        return list(s.scalars(stmt))


def get_material(material_id: int) -> Optional[Material]:
    with session_scope() as s:
        return s.get(Material, material_id)


def find_by_code(code: str) -> Optional[Material]:
    with session_scope() as s:
        return s.scalar(select(Material).where(Material.code == code.strip()))


def add_material(code: str, name: str, category: str = "Прочее",
                 unit: str = "шт", price: float = 0.0,
                 min_stock: float = 0.0) -> Material:
    """Завести новую позицию номенклатуры с нулевым остатком.

    :raises ValueError: при ошибке проверки или повторе артикула.
    """
    _check(validate_code(code, "артикул"),
           validate_name(name, "наименование"),
           validate_price(price, "цена"),
           validate_price(min_stock, "минимальный остаток"))
    if unit not in CONFIG["units"]:
        raise ValueError(f"Неизвестная единица измерения: {unit}")
    with session_scope() as s:
        if s.scalar(select(Material.id).where(Material.code == code.strip())):
            raise ValueError(f"Материал с артикулом {code} уже есть в справочнике.")
        m = Material(code=code.strip(), name=name.strip(), category=category,
                     unit=unit, price=float(price), stock=0.0,
                     min_stock=float(min_stock))
        s.add(m)
        s.flush()
        log.info("Добавлен материал %s «%s»", m.code, m.name)
        return m


def update_material(material_id: int, name: str, category: str, unit: str,
                    price: float, min_stock: float) -> bool:
    """Изменить реквизиты позиции. Остаток здесь не редактируется -
    только через приход, расход и возврат."""
    _check(validate_name(name, "наименование"),
           validate_price(price, "цена"),
           validate_price(min_stock, "минимальный остаток"))
    with session_scope() as s:
        m = s.get(Material, material_id)
        if m is None:
            log.warning("Материал id=%s не найден", material_id)
            return False
        m.name, m.category, m.unit = name.strip(), category, unit
        m.price, m.min_stock = float(price), float(min_stock)
        log.info("Материал %s обновлён", m.code)
        return True


# ===== Движение =====
def receive(material_id: int, qty: float, price: float,
            doc_number: str = "", supplier: str = "",
            doc_date: Optional[date] = None, comment: str = "") -> Movement:
    """Оприходовать материал от поставщика.

    Учётная цена пересчитывается по средневзвешенной:
    (остаток * цена + приход * цена прихода) / (остаток + приход).
    """
    _check(validate_qty(qty), validate_price(price, "цена"))
    q, p = float(qty), float(price)
    with session_scope() as s:
        m = s.get(Material, material_id)
        if m is None:
            raise ValueError("Материал не найден.")
        # Цена и остаток пересчитываются одной командой: в правой части
        # UPDATE берутся значения до изменения, поэтому параллельный приход
        # не может «затереть» чужой.
        s.execute(
            update(Material).where(Material.id == material_id).values(
                price=func.round((Material.stock * Material.price + q * p)
                                 / (Material.stock + q), 2),
                stock=func.round(Material.stock + q, 3),
            ).execution_options(synchronize_session=False))
        mv = Movement(kind=Movement.KIND_IN, material_id=m.id, qty=float(qty),
                      price=float(price), doc_number=doc_number.strip(),
                      counterparty=supplier.strip(), comment=comment,
                      doc_date=doc_date or date.today())
        s.add(mv)
        s.flush()
        log.info("Приход %s %s x%s по %.2f (накл. %s)",
                 m.code, m.name, qty, price, doc_number)
        return mv


def write_off(material_id: int, object_id: int, qty: float,
              doc_number: str = "", receiver: str = "",
              doc_date: Optional[date] = None, comment: str = "") -> Movement:
    """Списать материал на строительный объект.

    :raises StockError: если на складе меньше, чем требуется.
    """
    _check(validate_qty(qty))
    with session_scope() as s:
        m = s.get(Material, material_id)
        obj = s.get(Object, object_id)
        if m is None or obj is None:
            raise ValueError("Материал или объект не найден.")
        doc_date = doc_date or date.today()
        # Сданный объект закрыт для новых списаний, но документы, датированные
        # до сдачи, проводятся: так переносится история из Excel.
        if obj.status == "Сдан" and (obj.end_date is None
                                     or doc_date > obj.end_date):
            raise ValueError(f"Объект {obj.code} сдан, списание на него закрыто.")
        q = float(qty)
        # Проверка остатка и списание — одна атомарная команда.
        res = s.execute(
            update(Material)
            .where(Material.id == material_id, Material.stock >= q - 1e-9)
            .values(stock=func.round(Material.stock - q, 3))
            .execution_options(synchronize_session=False))
        if res.rowcount == 0:
            s.refresh(m)
            raise StockError(
                f"Недостаточно «{m.name}»: на складе {m.stock:g} {m.unit}, "
                f"требуется {q:g}."
            )
        mv = Movement(kind=Movement.KIND_OUT, material_id=m.id,
                      object_id=obj.id, qty=float(qty), price=m.price,
                      doc_number=doc_number.strip(),
                      counterparty=receiver.strip(), comment=comment,
                      doc_date=doc_date)
        s.add(mv)
        s.flush()
        log.info("Расход %s x%s на объект %s (треб. %s)",
                 m.code, qty, obj.code, doc_number)
        return mv


def issued_to_object(material_id: int, object_id: int) -> float:
    """Сколько материала числится на объекте: выдано минус возвращено."""
    with session_scope() as s:
        rows = s.execute(
            select(Movement.kind, func.sum(Movement.qty))
            .where(Movement.material_id == material_id,
                   Movement.object_id == object_id)
            .group_by(Movement.kind)
        ).all()
    d = dict(rows)
    return round(d.get(Movement.KIND_OUT, 0.0) - d.get(Movement.KIND_RETURN, 0.0), 3)


def return_stock(material_id: int, object_id: int, qty: float,
                 doc_number: str = "", doc_date: Optional[date] = None,
                 comment: str = "") -> Movement:
    """Вернуть на склад неиспользованный материал с объекта."""
    _check(validate_qty(qty))
    on_object = issued_to_object(material_id, object_id)
    if float(qty) > on_object + 1e-9:
        raise StockError(
            f"На объекте числится только {on_object:g}, вернуть {float(qty):g} нельзя."
        )
    with session_scope() as s:
        m = s.get(Material, material_id)
        s.execute(update(Material).where(Material.id == material_id)
                  .values(stock=func.round(Material.stock + float(qty), 3))
                  .execution_options(synchronize_session=False))
        mv = Movement(kind=Movement.KIND_RETURN, material_id=m.id,
                      object_id=object_id, qty=float(qty), price=m.price,
                      doc_number=doc_number.strip(), comment=comment,
                      doc_date=doc_date or date.today())
        s.add(mv)
        s.flush()
        log.info("Возврат %s x%s с объекта id=%s", m.code, qty, object_id)
        return mv


def list_movements(kind: str = "Все", object_id: Optional[int] = None,
                   material_id: Optional[int] = None,
                   date_from: Optional[date] = None,
                   date_to: Optional[date] = None,
                   limit: int = 500) -> List[Movement]:
    """Журнал движения с фильтрами. Материал и объект подгружаются
    одним дополнительным запросом на всю выборку (selectinload)."""
    stmt = (select(Movement)
            .options(selectinload(Movement.material),
                     selectinload(Movement.object))
            .order_by(Movement.doc_date.desc(), Movement.id.desc())
            .limit(limit))
    if kind and kind != "Все":
        stmt = stmt.where(Movement.kind == kind)
    if object_id:
        stmt = stmt.where(Movement.object_id == object_id)
    if material_id:
        stmt = stmt.where(Movement.material_id == material_id)
    if date_from:
        stmt = stmt.where(Movement.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(Movement.doc_date <= date_to)
    with session_scope() as s:
        return list(s.scalars(stmt))


def low_stock() -> List[Material]:
    """Позиции, остаток которых опустился ниже неснижаемого."""
    with session_scope() as s:
        return list(s.scalars(
            select(Material)
            .where(Material.min_stock > 0, Material.stock < Material.min_stock)
            .order_by(Material.name)
        ))


def stock_value_total() -> float:
    """Общая стоимость складских остатков."""
    with session_scope() as s:
        v = s.scalar(select(func.sum(Material.stock * Material.price)))
    return round(v or 0.0, 2)
