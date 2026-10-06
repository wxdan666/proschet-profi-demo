"""
Тесты складского учёта: приход, списание на объект, возврат.
"""
from datetime import date

import pytest

from services import materials, objects
from services.materials import StockError


@pytest.fixture
def pipe():
    """Профильная труба с остатком 100 м по 150 ₽."""
    m = materials.add_material("МП-002", "Труба профильная 40×20×2",
                               "Металлопрокат", "м", 150, 30)
    materials.receive(m.id, 100, 150, "УПД 1", "Поставщик")
    return materials.get_material(m.id)


@pytest.fixture
def site():
    return objects.create_object("С-26-031", "Оконные решётки", contract_sum=400000,
                                 status="В работе")


def test_receive_increases_stock(pipe):
    assert pipe.stock == 100
    assert pipe.price == 150


def test_receive_weighted_price(pipe):
    """100 м по 150 + 50 м по 180 = 150 м по 160."""
    materials.receive(pipe.id, 50, 180, "УПД 2")
    m = materials.get_material(pipe.id)
    assert m.stock == 150
    assert m.price == 160.0


def test_write_off_decreases_stock(pipe, site):
    mv = materials.write_off(pipe.id, site.id, 30.5, "ТР-1")
    assert mv.price == 150
    assert materials.get_material(pipe.id).stock == 69.5


def test_write_off_insufficient_stock(pipe, site):
    with pytest.raises(StockError):
        materials.write_off(pipe.id, site.id, 100.1)
    assert materials.get_material(pipe.id).stock == 100  # остаток не изменился


def test_write_off_zero_qty_rejected(pipe, site):
    with pytest.raises(ValueError):
        materials.write_off(pipe.id, site.id, 0)


def test_closed_object_blocks_new_write_off(pipe):
    obj = objects.create_object("С-26-024", "Ограждение", status="Сдан",
                                start_date=date(2026, 7, 1),
                                end_date=date(2026, 8, 28))
    with pytest.raises(ValueError):
        materials.write_off(pipe.id, obj.id, 5, doc_date=date(2026, 9, 3))


def test_closed_object_accepts_old_documents(pipe):
    """Требование, датированное до сдачи объекта, проводится (перенос истории)."""
    obj = objects.create_object("С-26-024", "Ограждение", status="Сдан",
                                start_date=date(2026, 7, 1),
                                end_date=date(2026, 8, 28))
    materials.write_off(pipe.id, obj.id, 5, doc_date=date(2026, 8, 10))
    assert materials.get_material(pipe.id).stock == 95


def test_return_limited_by_issued(pipe, site):
    materials.write_off(pipe.id, site.id, 20)
    materials.return_stock(pipe.id, site.id, 5)
    assert materials.issued_to_object(pipe.id, site.id) == 15
    with pytest.raises(StockError):
        materials.return_stock(pipe.id, site.id, 16)


def test_duplicate_code_rejected(pipe):
    with pytest.raises(ValueError):
        materials.add_material("МП-002", "Другая труба")


def test_low_stock(pipe, site):
    materials.write_off(pipe.id, site.id, 75)  # остаток 25 < минимум 30
    assert [m.code for m in materials.low_stock()] == ["МП-002"]


def test_stock_value(pipe):
    assert materials.stock_value_total() == 15000.0


def test_search_cyrillic_case_insensitive(pipe):
    assert [m.code for m in materials.list_materials("ТРУБА")] == ["МП-002"]
    assert [m.code for m in materials.list_materials("мп-002")] == ["МП-002"]


def test_concurrent_write_off_no_lost_update(pipe, site):
    """Регрессия: 40 потоков списывают по 3 м при остатке 100 м.

    Пройти должны ровно 33 списания, остаток 1 м, без ухода в минус.
    """
    from concurrent.futures import ThreadPoolExecutor

    def take(_):
        try:
            materials.write_off(pipe.id, site.id, 3)
            return True
        except StockError:
            return False

    with ThreadPoolExecutor(40) as ex:
        done = sum(ex.map(take, range(40)))
    assert done == 33
    assert materials.get_material(pipe.id).stock == 1
    assert materials.issued_to_object(pipe.id, site.id) == 99


def test_concurrent_receive_weighted_price(pipe):
    """Параллельные приходы не теряют ни количества, ни цены."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(20) as ex:
        list(ex.map(lambda _: materials.receive(pipe.id, 10, 150), range(20)))
    m = materials.get_material(pipe.id)
    assert m.stock == 300
    assert m.price == 150
