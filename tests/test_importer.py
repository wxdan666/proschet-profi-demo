"""
Интеграционные тесты импорта Excel-выгрузок.

Генератор tools/make_sample_excel.py создаёт таблицы в формате рабочих
файлов предприятия, импорт переносит их в пустую базу.
"""
import os

from openpyxl import Workbook

from services import importer, materials, objects
from tools.make_sample_excel import MATERIALS, OBJECTS, WORKERS, build


def test_import_folder_full_cycle(tmp_dir):
    build(tmp_dir)
    results = importer.import_folder(tmp_dir)
    assert [r.ok for r in results] == [True] * 5
    assert len(objects.list_objects()) == len(OBJECTS)
    assert len(materials.list_materials()) == len(MATERIALS)
    assert all(m.stock >= 0 for m in materials.list_materials())


def test_reimport_does_not_duplicate(tmp_dir):
    build(tmp_dir)
    importer.import_folder(tmp_dir)
    value_before = materials.stock_value_total()
    second = importer.import_folder(tmp_dir)
    assert sum(r.added for r in second) == 0
    assert materials.stock_value_total() == value_before


def test_header_found_below_title_rows(tmp_dir):
    """Шапка таблицы на 4-й строке, столбцы названы «по-рабочему»."""
    wb = Workbook()
    ws = wb.active
    ws.append(["ООО «СтройМонтаж»"])
    ws.append(["Ведомость остатков на 01.07.2026"])
    ws.append([])
    ws.append(["№", "Артикул", "Наименование", "Ед.изм", "Цена, руб.", "Остаток"])
    ws.append([1, "АИ-001", "Круг отрезной 230", "шт", "120,50", 10])
    ws.append([None, "Итого", None, None, None, None])
    path = os.path.join(tmp_dir, "материалы.xlsx")
    wb.save(path)
    r = importer.import_materials(path)
    assert r.ok and r.added == 1
    m = materials.find_by_code("АИ-001")
    assert m.price == 120.5 and m.stock == 10


def test_import_reports_bad_rows(tmp_dir):
    wb = Workbook()
    ws = wb.active
    ws.append(["Артикул", "Наименование", "Цена", "Остаток"])
    ws.append(["ОК-01", "Нормальная позиция", 100, 5])
    ws.append(["ОК-02", "Цена текстом", "сто рублей", 5])
    path = os.path.join(tmp_dir, "материалы.xlsx")
    wb.save(path)
    r = importer.import_materials(path)
    assert r.added == 1
    assert len(r.errors) == 1 and r.errors[0].startswith("строка 3")


def test_detect_kind_by_filename():
    assert importer.detect_kind("Расход_на_объекты_июль.xlsx")[0] == "расход"
    assert importer.detect_kind("Объекты_2026.xlsx")[0] == "объект"
    assert importer.detect_kind("отчёт.xlsx")[0] is None


def test_workers_import(tmp_dir):
    build(tmp_dir)
    r = importer.import_workers(os.path.join(tmp_dir, "Сотрудники.xlsx"))
    assert r.added == len(WORKERS)
