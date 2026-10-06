"""
Проверки качества «ПросчётПрофи»: безопасность, нагрузка, стресс.

Все проверки идут на отдельной временной базе, рабочая proschet.db
не затрагивается.

Запуск:  python tools/qa_checks.py [security|load|stress|all]
"""
import os
import random
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

TMP = tempfile.mkdtemp(prefix="proschet_qa_")
os.environ["PROSCHET_DB_URL"] = "sqlite:///" + os.path.join(TMP, "qa.db")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import logging  # noqa: E402

from sqlalchemy import inspect  # noqa: E402

from config import CONFIG  # noqa: E402
from database import engine, reset_database  # noqa: E402
from services import analytics, auth, importer, materials, objects, orders  # noqa: E402
from services.materials import StockError  # noqa: E402
from tools.make_sample_excel import build  # noqa: E402
from validators import validate_code  # noqa: E402

logging.getLogger("ProschetProfi").setLevel(logging.CRITICAL)


def demo_db():
    reset_database()
    folder = os.path.join(TMP, "xlsx")
    build(folder)
    importer.import_folder(folder)


def line(title, ok, note=""):
    print(f"  [{'OK ' if ok else 'ERR'}] {title}{(' — ' + note) if note else ''}")
    return ok


# ---------------- Безопасность ----------------
def security():
    print("\n== Тестирование безопасности ==")
    demo_db()
    tables_before = set(inspect(engine).get_table_names())
    counts_before = (len(orders.list_orders()), len(materials.list_materials()))
    payloads = ["' OR 1=1 --", "%'; DROP TABLE orders; --", '" OR ""="',
                "1; DELETE FROM materials", "<script>alert(1)</script>"]
    for p in payloads:
        r1 = orders.search_orders(p)
        r2 = materials.list_materials(p)
        line(f"SQL-инъекция в поиск: {p!r}", len(r1) == 0 and len(r2) == 0,
             f"найдено заявок {len(r1)}, материалов {len(r2)}")
    tables_after = set(inspect(engine).get_table_names())
    line("Таблицы базы на месте после попыток инъекций", tables_before == tables_after,
         f"{len(tables_after)} таблиц")
    counts_after = (len(orders.list_orders()), len(materials.list_materials()))
    line("Число заявок и материалов не изменилось", counts_before == counts_after,
         f"заявок {counts_after[0]}, материалов {counts_after[1]}")

    raw = open(os.path.join(ROOT, "config.json"), encoding="utf-8").read()
    line("PIN не хранится в открытом виде", '"1234"' not in raw,
         "в config.json только SHA-256 хеш")
    line("Неверный PIN отклоняется", auth.check_pin("0000") is False)
    line("PIN с буквами отклоняется до сравнения хешей", auth.check_pin("12ab") is False)
    line("Разделы «Персонал» и «Импорт» закрыты PIN",
         auth.is_section_protected("Персонал") and auth.is_section_protected("Импорт из Excel"))
    line("Код с опасными символами не принимается", not validate_code("МП-1;DROP")[0])

    t0 = time.perf_counter()
    tries = 0
    for pin in (f"{i:04d}" for i in range(10000)):
        tries += 1
        if auth.check_pin(pin):
            break
    dt = time.perf_counter() - t0
    line("Перебор всех PIN за время", True,
         f"PIN найден за {tries} попыток и {dt:.2f} с — нет ограничения числа попыток (ЗАМЕЧАНИЕ)")


# ---------------- Нагрузка ----------------
def _mixed_operation(rnd, mat_ids, obj_ids):
    op = rnd.random()
    t0 = time.perf_counter()
    if op < 0.35:
        orders.search_orders(rnd.choice(["монтаж", "решёток", "кабель", ""]))
    elif op < 0.55:
        analytics.dashboard()
    elif op < 0.75:
        materials.list_materials(rnd.choice(["труба", "кабель", ""]))
    elif op < 0.9:
        objects.objects_summary()
    else:
        materials.list_movements(limit=200)
    return (time.perf_counter() - t0) * 1000


def load(duration=15):
    print("\n== Нагрузочное тестирование (операции чтения, смешанный профиль) ==")
    demo_db()
    mat_ids = [m.id for m in materials.list_materials()]
    obj_ids = [o.id for o in objects.active_objects()]
    print(f"  {'Потоков':>7} | {'Операций':>8} | {'Оп/с':>6} | {'Медиана, мс':>11} | "
          f"{'95%, мс':>8} | {'Макс, мс':>8} | Ошибок")
    for users in (1, 5, 10, 25):
        stop = time.time() + duration
        lat, errors = [], []
        lock = threading.Lock()

        def worker(seed):
            rnd = random.Random(seed)
            while time.time() < stop:
                try:
                    v = _mixed_operation(rnd, mat_ids, obj_ids)
                    with lock:
                        lat.append(v)
                except Exception as e:  # noqa: BLE001
                    with lock:
                        errors.append(repr(e))

        with ThreadPoolExecutor(users) as ex:
            for i in range(users):
                ex.submit(worker, i)
        lat.sort()
        p95 = lat[int(len(lat) * 0.95) - 1]
        print(f"  {users:>7} | {len(lat):>8} | {len(lat) / duration:>6.0f} | "
              f"{statistics.median(lat):>11.1f} | {p95:>8.1f} | {lat[-1]:>8.1f} | {len(errors)}")


# ---------------- Стресс ----------------
def stress():
    print("\n== Стрессовое тестирование ==")
    demo_db()
    site = objects.find_by_code("С-26-031")
    m = materials.add_material("СТ-001", "Стресс-позиция", "Прочее", "шт", 100, 0)
    materials.receive(m.id, 100, 100, "СТРЕСС")

    # 1. Конкурентное списание одной позиции: 50 потоков по 3 шт при остатке 100.
    ok, refused, failed = [], [], []

    def take(_):
        try:
            materials.write_off(m.id, site.id, 3, "СТ")
            ok.append(1)
        except StockError:
            refused.append(1)
        except Exception as e:  # noqa: BLE001
            failed.append(repr(e)[:80])

    with ThreadPoolExecutor(50) as ex:
        list(ex.map(take, range(50)))
    stock = materials.get_material(m.id).stock
    issued = materials.issued_to_object(m.id, site.id)
    line("Параллельное списание 50×3 шт. при остатке 100", stock >= 0 and stock + issued == 100,
         f"проведено {len(ok)}, отказов {len(refused)}, ошибок {len(failed)}, "
         f"остаток {stock:g}, выдано по журналу {issued:g}")
    if failed:
        print("     пример ошибки:", failed[0])

    # 2. Большой объём: 20 000 строк журнала требований в одном Excel.
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Дата", "Требование", "Объект", "Артикул", "Кол-во", "Получил"])
    materials.receive(m.id, 50000, 100, "СТРЕСС-2")
    for i in range(20000):
        ws.append(["01.10.2026", f"ТР-S-{i}", "С-26-031", "СТ-001", 1, "Тест"])
    path = os.path.join(TMP, "big_issues.xlsx")
    wb.save(path)
    t0 = time.perf_counter()
    r = importer.import_issues(path)
    dt = time.perf_counter() - t0
    line("Импорт 20 000 строк требований", r.ok and r.added == 20000,
         f"{dt:.1f} с, {r.added / dt:.0f} строк/с, ошибок {len(r.errors)}")

    # 3. Граничные значения
    for q in (1_000_000, 1_000_001, -1, 0, float("nan")):
        try:
            materials.receive(m.id, q, 1, "ГРАНИЦА")
            res = "принято"
        except ValueError as e:
            res = f"отказ: {e}"
        print(f"     приход {q!r:>10}: {res}")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("security", "all"):
        security()
    if what in ("load", "all"):
        load()
    if what in ("stress", "all"):
        stress()
