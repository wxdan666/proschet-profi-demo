"""
Замер эффекта оптимизации: алгоритмы версии 1.0 против версии 2.0
на одной и той же базе данных.

Сравниваются три операции, которые пользователь выполняет чаще всего:
1. Поиск заявок по описанию и статусу с выводом бригады в таблицу.
2. Подсчёт суммы выполненных работ (показатель на главной странице).
3. Сводка по объектам: стоимость работ по каждому объекту.

Версия 1.0 выгружала все строки в память и фильтровала их циклом Python,
а связанные записи (бригаду) подгружала отдельным запросом на каждую строку.
Версия 2.0 передаёт условия в SQL, подгружает связи пакетно и считает
суммы агрегатными функциями СУБД.

Запуск:  python tools/bench_optimization.py
Результат печатается таблицей; база создаётся во временной папке.
"""
import os
import random
import statistics
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="proschet_bench_")
os.environ["PROSCHET_DB_URL"] = "sqlite:///" + os.path.join(TMP, "bench.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging  # noqa: E402

from sqlalchemy import event, func, insert, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from database import (  # noqa: E402
    Object, Order, Worker, engine, order_workers, reset_database,
)
from services import objects, orders  # noqa: E402

logging.getLogger("ProschetProfi").setLevel(logging.WARNING)

QUERIES = {"n": 0}


@event.listens_for(engine, "before_cursor_execute")
def _count(*_args):
    QUERIES["n"] += 1


WORDS = ["монтаж", "демонтаж", "сварка", "решётки", "ворот", "кабеля", "щита",
         "освещения", "кровли", "ограждения", "двери", "покраска", "замеры"]
STATUSES = ["Новая", "В работе", "Выполнена", "Отменена"]


def fill(n_orders: int) -> None:
    reset_database()
    rnd = random.Random(7)
    with engine.begin() as c:
        c.execute(insert(Object), [{"code": f"Ю-B-{i:03d}", "name": f"Объект {i}",
                                    "status": "В работе", "contract_sum": 500000}
                                   for i in range(1, 41)])
        c.execute(insert(Worker), [{"name": f"Сотрудник {i}", "specialty": "Монтажник"}
                                   for i in range(1, 31)])
        c.execute(insert(Order), [{
            "object_id": rnd.randint(1, 40),
            "description": " ".join(rnd.sample(WORDS, 3)).capitalize() + f" №{i}",
            "status": rnd.choice(STATUSES),
            "total_cost": rnd.randint(5, 300) * 1000,
        } for i in range(1, n_orders + 1)])
        c.execute(insert(order_workers), [
            {"order_id": i, "worker_id": w}
            for i in range(1, n_orders + 1)
            for w in rnd.sample(range(1, 31), rnd.randint(1, 3))])


# ---------- Алгоритмы версии 1.0 (воспроизведены из курсовой) ----------
def v1_search(query: str, status: str):
    """v1: выгрузить все заявки, отфильтровать в цикле, бригада лениво."""
    s = Session(engine)
    all_orders = s.query(Order).all()
    q = query.strip().lower()
    result = []
    for o in all_orders:
        if q and q not in (o.description or "").lower():
            continue
        if status != "Все" and o.status != status:
            continue
        result.append(o)
    rows = [(o.id, ", ".join(w.name for w in o.workers)) for o in result]
    s.close()
    return rows


def v1_revenue():
    s = Session(engine)
    total = sum(o.total_cost for o in s.query(Order).all() if o.status == "Выполнена")
    s.close()
    return total


def v1_summary():
    s = Session(engine)
    res = {}
    for obj in s.query(Object).all():
        res[obj.id] = sum(o.total_cost for o in obj.orders if o.status != "Отменена")
    s.close()
    return res


# ---------- Версия 2.0 ----------
def v2_search(query: str, status: str):
    found = orders.search_orders(query, status)
    return [(o.id, ", ".join(w.name for w in o.workers)) for o in found]


def v2_revenue():
    with engine.connect() as c:
        return c.execute(select(func.sum(Order.total_cost))
                         .where(Order.status == "Выполнена")).scalar() or 0


def v2_summary():
    return {r["id"]: r["Работы, ₽"] for r in objects.objects_summary()}


def measure(fn, *args, repeat: int = 5):
    times, queries, result = [], 0, None
    for _ in range(repeat):
        QUERIES["n"] = 0
        t0 = time.perf_counter()
        result = fn(*args)
        times.append((time.perf_counter() - t0) * 1000)
        queries = QUERIES["n"]
    return statistics.median(times), queries, result


def main():
    print(f"{'Заявок':>7} | {'Операция':<26} | {'v1, мс':>8} | {'v2, мс':>8} | "
          f"{'Ускорение':>9} | {'Запросов v1':>11} | {'Запросов v2':>11}")
    print("-" * 98)
    for n in (1000, 5000, 20000):
        fill(n)
        cases = [
            ("Поиск «монтаж», В работе", v1_search, v2_search, ("монтаж", "В работе")),
            ("Сумма выполненных работ", v1_revenue, v2_revenue, ()),
            ("Сводка по 40 объектам", v1_summary, v2_summary, ()),
        ]
        for title, f1, f2, args in cases:
            t1, q1, r1 = measure(f1, *args)
            t2, q2, r2 = measure(f2, *args)
            if title.startswith("Сводка"):
                same = all(abs(r1[k] - r2.get(k, 0)) < 0.01 for k in r1)
            elif title.startswith("Поиск"):
                same = sorted(r1) == sorted(r2)
            else:
                same = abs(r1 - r2) < 0.01
            assert same, f"Результаты v1 и v2 разошлись: {title}"
            print(f"{n:>7} | {title:<26} | {t1:>8.1f} | {t2:>8.1f} | "
                  f"{t1 / t2:>8.1f}× | {q1:>11} | {q2:>11}")
        print("-" * 98)
    print("Результаты обеих версий совпадают во всех замерах.")


if __name__ == "__main__":
    main()
