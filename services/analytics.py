"""
Сервис аналитики: показатели для главной страницы и графиков.

Все суммы считаются агрегирующими SQL-запросами (SUM, GROUP BY) -
в память не выгружается ни одной лишней строки.
"""
from datetime import date
from typing import Dict, List

from sqlalchemy import case, func, select

from database import Material, Movement, Object, Order, session_scope
from services.materials import stock_value_total

_NET_AMOUNT = func.sum(case(
    (Movement.kind == Movement.KIND_OUT, Movement.qty * Movement.price),
    (Movement.kind == Movement.KIND_RETURN, -Movement.qty * Movement.price),
    else_=0.0,
))


def dashboard(today: date = None) -> Dict:
    """Ключевые показатели для главной страницы."""
    today = today or date.today()
    month_start = today.replace(day=1)
    with session_scope() as s:
        active = s.scalar(select(func.count(Object.id))
                          .where(Object.status == "В работе"))
        low = s.scalar(select(func.count(Material.id))
                       .where(Material.min_stock > 0,
                              Material.stock < Material.min_stock))
        month_out = s.scalar(select(_NET_AMOUNT)
                             .where(Movement.doc_date >= month_start,
                                    Movement.doc_date <= today))
        orders_open = s.scalar(select(func.count(Order.id))
                               .where(Order.status.in_(("Новая", "В работе"))))
        positions = s.scalar(select(func.count(Material.id)))
    return {
        "objects_active": active or 0,
        "stock_value": stock_value_total(),
        "positions": positions or 0,
        "low_stock": low or 0,
        "month_consumption": round(month_out or 0.0, 2),
        "orders_open": orders_open or 0,
    }


def consumption_by_month() -> List[Dict]:
    """Расход материалов на объекты по месяцам (чистый, за вычетом возвратов)."""
    month = func.strftime("%Y-%m", Movement.doc_date)
    with session_scope() as s:
        rows = s.execute(
            select(month, _NET_AMOUNT)
            .where(Movement.object_id.is_not(None))
            .group_by(month).order_by(month)
        ).all()
    return [{"Месяц": r[0], "Расход, ₽": round(r[1] or 0, 2)} for r in rows]


def consumption_by_category(date_from: date, date_to: date) -> List[Dict]:
    with session_scope() as s:
        rows = s.execute(
            select(Material.category, _NET_AMOUNT)
            .join(Movement, Movement.material_id == Material.id)
            .where(Movement.doc_date >= date_from, Movement.doc_date <= date_to,
                   Movement.object_id.is_not(None))
            .group_by(Material.category)
            .order_by(_NET_AMOUNT.desc())
        ).all()
    return [{"Категория": r[0], "Расход, ₽": round(r[1] or 0, 2)} for r in rows]


def top_materials(date_from: date, date_to: date, limit: int = 10) -> List[Dict]:
    with session_scope() as s:
        rows = s.execute(
            select(Material.name, Material.unit,
                   func.sum(Movement.qty), _NET_AMOUNT)
            .join(Movement, Movement.material_id == Material.id)
            .where(Movement.kind == Movement.KIND_OUT,
                   Movement.doc_date >= date_from, Movement.doc_date <= date_to)
            .group_by(Material.id)
            .order_by(_NET_AMOUNT.desc())
            .limit(limit)
        ).all()
    return [{"Материал": r[0], "Ед.": r[1], "Кол-во": round(r[2], 3),
             "Сумма, ₽": round(r[3] or 0, 2)} for r in rows]
