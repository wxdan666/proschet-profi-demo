"""
Сервис строительных объектов.

Объект - центр учёта: на него списываются материалы и по нему
открываются заявки на работы. Отсюда считается себестоимость объекта
и его маржа относительно суммы договора.
"""
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy import case, func, select

from config import CONFIG
from database import Material, Movement, Object, Order, session_scope
from logger import log
from validators import validate_code, validate_name, validate_price

STATUSES = CONFIG["object_statuses"]


def list_objects(status: str = "Все") -> List[Object]:
    stmt = select(Object).order_by(Object.code)
    if status and status != "Все":
        stmt = stmt.where(Object.status == status)
    with session_scope() as s:
        return list(s.scalars(stmt))


def active_objects() -> List[Object]:
    """Объекты, на которые можно списывать материалы."""
    with session_scope() as s:
        return list(s.scalars(
            select(Object).where(Object.status != "Сдан").order_by(Object.code)
        ))


def get_object(object_id: int) -> Optional[Object]:
    with session_scope() as s:
        return s.get(Object, object_id)


def find_by_code(code: str) -> Optional[Object]:
    with session_scope() as s:
        return s.scalar(select(Object).where(Object.code == str(code).strip()))


def create_object(code: str, name: str, address: str = "", customer: str = "",
                  contract_sum: float = 0.0, status: str = "Подготовка",
                  start_date: Optional[date] = None,
                  end_date: Optional[date] = None) -> Object:
    """Завести объект. :raises ValueError: при ошибке проверки."""
    for ok, msg in (validate_code(code, "код объекта"),
                    validate_name(name, "наименование объекта"),
                    validate_price(contract_sum, "сумма договора")):
        if not ok:
            raise ValueError(msg)
    if status not in STATUSES:
        raise ValueError(f"Недопустимый статус объекта: {status}")
    if start_date and end_date and end_date < start_date:
        raise ValueError("Дата окончания раньше даты начала.")
    with session_scope() as s:
        if s.scalar(select(Object.id).where(Object.code == code.strip())):
            raise ValueError(f"Объект с кодом {code} уже существует.")
        obj = Object(code=code.strip(), name=name.strip(),
                     address=address.strip(), customer=customer.strip(),
                     contract_sum=float(contract_sum), status=status,
                     start_date=start_date, end_date=end_date)
        s.add(obj)
        s.flush()
        log.info("Создан объект %s «%s»", obj.code, obj.name)
        return obj


def update_object(object_id: int, **fields) -> bool:
    """Изменить реквизиты объекта (статус, сумму, даты и т.д.)."""
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"Недопустимый статус объекта: {fields['status']}")
    if "contract_sum" in fields:
        ok, msg = validate_price(fields["contract_sum"], "сумма договора")
        if not ok:
            raise ValueError(msg)
    with session_scope() as s:
        obj = s.get(Object, object_id)
        if obj is None:
            return False
        for k, v in fields.items():
            if hasattr(obj, k):
                setattr(obj, k, v.strip() if isinstance(v, str) else v)
        log.info("Объект %s обновлён: %s", obj.code, ", ".join(fields))
        return True


# ===== Учётные выборки =====
_NET_QTY = func.sum(case(
    (Movement.kind == Movement.KIND_OUT, Movement.qty),
    (Movement.kind == Movement.KIND_RETURN, -Movement.qty),
    else_=0.0,
))
_NET_AMOUNT = func.sum(case(
    (Movement.kind == Movement.KIND_OUT, Movement.qty * Movement.price),
    (Movement.kind == Movement.KIND_RETURN, -Movement.qty * Movement.price),
    else_=0.0,
))


def material_report(object_id: int) -> List[Dict]:
    """Отчёт о расходе материалов по объекту (аналог формы М-29).

    Один агрегирующий запрос: выдано, возвращено, чистый расход и сумма
    по каждой позиции.
    """
    issued = func.sum(case((Movement.kind == Movement.KIND_OUT, Movement.qty),
                           else_=0.0))
    returned = func.sum(case((Movement.kind == Movement.KIND_RETURN,
                              Movement.qty), else_=0.0))
    stmt = (select(Material.code, Material.name, Material.unit,
                   issued, returned, _NET_QTY, _NET_AMOUNT)
            .join(Movement, Movement.material_id == Material.id)
            .where(Movement.object_id == object_id)
            .group_by(Material.id)
            .order_by(Material.name))
    with session_scope() as s:
        rows = s.execute(stmt).all()
    return [{
        "Артикул": r[0], "Материал": r[1], "Ед.": r[2],
        "Выдано": round(r[3], 3), "Возвращено": round(r[4], 3),
        "Израсходовано": round(r[5], 3), "Сумма, ₽": round(r[6], 2),
    } for r in rows]


def objects_summary() -> List[Dict]:
    """Сводка по всем объектам: материалы, работы, маржа.

    Два групповых запроса на весь список вместо отдельного запроса
    на каждый объект.
    """
    with session_scope() as s:
        objs = list(s.scalars(select(Object).order_by(Object.code)))
        mat = dict(s.execute(
            select(Movement.object_id, _NET_AMOUNT)
            .where(Movement.object_id.is_not(None))
            .group_by(Movement.object_id)
        ).all())
        works = dict(s.execute(
            select(Order.object_id, func.sum(Order.total_cost))
            .where(Order.status != "Отменена", Order.object_id.is_not(None))
            .group_by(Order.object_id)
        ).all())
    result = []
    for o in objs:
        m_cost = round(mat.get(o.id) or 0.0, 2)
        w_cost = round(works.get(o.id) or 0.0, 2)
        cost = m_cost + w_cost
        margin = round((o.contract_sum or 0) - cost, 2)
        pct = round(margin / o.contract_sum * 100, 1) if o.contract_sum else 0.0
        result.append({
            "id": o.id, "Код": o.code, "Объект": o.name, "Заказчик": o.customer,
            "Статус": o.status, "Договор, ₽": o.contract_sum,
            "Материалы, ₽": m_cost, "Работы, ₽": w_cost,
            "Маржа, ₽": margin, "Маржа, %": pct,
        })
    return result


def economics(object_id: int) -> Dict:
    """Экономика одного объекта."""
    for row in objects_summary():
        if row["id"] == object_id:
            return row
    return {}
