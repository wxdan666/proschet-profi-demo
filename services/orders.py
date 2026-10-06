"""
Сервис заявок на работы.

Заявка привязана к объекту, на неё назначается бригада. Стоимость
работ по заявке входит в себестоимость объекта.
"""
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from config import CONFIG
from database import Order, Worker, session_scope
from logger import log
from validators import validate_name, validate_price

STATUSES = CONFIG["order_statuses"]


def _base_query():
    """Заявки вместе с бригадой и объектом: связанные записи подгружаются
    пакетно, а не отдельным запросом на каждую строку таблицы."""
    return (select(Order)
            .options(selectinload(Order.workers), selectinload(Order.object))
            .order_by(Order.id.desc()))


def list_orders(object_id: Optional[int] = None) -> List[Order]:
    stmt = _base_query()
    if object_id:
        stmt = stmt.where(Order.object_id == object_id)
    with session_scope() as s:
        return list(s.scalars(stmt))


def get_order(order_id: int) -> Optional[Order]:
    with session_scope() as s:
        return s.scalar(_base_query().where(Order.id == order_id))


def create_order(description: str, object_id: Optional[int] = None,
                 total_cost: float = 0.0) -> Order:
    """Создать заявку.

    :raises ValueError: если описание или стоимость не прошли проверку.
    """
    ok, msg = validate_name(description, field="описание")
    if not ok:
        log.warning("Не удалось создать заявку: %s", msg)
        raise ValueError(msg)
    ok, msg = validate_price(total_cost, field="стоимость")
    if not ok:
        raise ValueError(msg)
    with session_scope() as s:
        order = Order(description=description.strip(), object_id=object_id,
                      total_cost=float(total_cost))
        s.add(order)
        s.flush()
        log.info("Создана заявка id=%s (объект %s)", order.id, object_id)
        return order


def update_order(order_id: int, status: str, total_cost: float,
                 worker_ids: List[int]) -> bool:
    """Обновить статус, стоимость и бригаду заявки."""
    if status not in STATUSES:
        log.warning("Недопустимый статус заявки: %s", status)
        return False
    ok, msg = validate_price(total_cost, field="стоимость")
    if not ok:
        log.warning("Не удалось обновить заявку %s: %s", order_id, msg)
        return False
    try:
        with session_scope() as s:
            order = s.get(Order, order_id)
            if order is None:
                log.warning("Заявка id=%s не найдена", order_id)
                return False
            order.status = status
            order.total_cost = float(total_cost)
            order.workers = list(s.scalars(
                select(Worker).where(Worker.id.in_(worker_ids))))
        log.info("Заявка id=%s: статус=%s, сумма=%.2f, бригада=%s",
                 order_id, status, total_cost, worker_ids)
        return True
    except Exception as e:
        log.error("Ошибка при обновлении заявки %s: %s", order_id, e)
        return False


def search_orders(query: str = "", status: str = "Все",
                  object_id: Optional[int] = None) -> List[Order]:
    """Поиск заявок по описанию с фильтрами по статусу и объекту.

    В версии 1.0 приложение выгружало из базы все заявки и перебирало
    их в цикле Python. Теперь условия передаются в SQL, СУБД возвращает
    только подходящие строки и использует индекс по статусу.
    """
    stmt = _base_query()
    q = (query or "").strip()
    if q:
        stmt = stmt.where(func.lower_ru(Order.description).like(f"%{q.lower()}%"))
    if status and status != "Все":
        stmt = stmt.where(Order.status == status)
    if object_id:
        stmt = stmt.where(Order.object_id == object_id)
    with session_scope() as s:
        result = list(s.scalars(stmt))
    log.debug("search_orders(%r, %r, %r) -> %d", query, status, object_id,
              len(result))
    return result
