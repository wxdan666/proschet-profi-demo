"""
Тесты объектов (себестоимость, маржа) и заявок (поиск, бригада).
"""
import pytest

from services import materials, objects, orders, workers


@pytest.fixture
def setup():
    obj = objects.create_object("С-26-033", "Электромонтаж АЗС",
                                contract_sum=300000, status="В работе")
    cable = materials.add_material("ЭТ-002", "Кабель ВВГнг 3×2,5",
                                   "Электротехника", "м", 120)
    materials.receive(cable.id, 500, 120)
    materials.write_off(cable.id, obj.id, 200)    # 24 000
    materials.return_stock(cable.id, obj.id, 50)  # -6 000
    o1 = orders.create_order("Электромонтаж освещения", obj.id, 90000)
    orders.create_order("Отменённые работы", obj.id, 50000)
    cancelled = orders.list_orders(obj.id)[0]
    orders.update_order(cancelled.id, "Отменена", 50000, [])
    return obj, cable, o1


def test_material_report(setup):
    obj, _, _ = setup
    rep = objects.material_report(obj.id)
    assert len(rep) == 1
    row = rep[0]
    assert row["Выдано"] == 200 and row["Возвращено"] == 50
    assert row["Израсходовано"] == 150
    assert row["Сумма, ₽"] == 18000


def test_economics_excludes_cancelled(setup):
    obj, _, _ = setup
    e = objects.economics(obj.id)
    assert e["Материалы, ₽"] == 18000
    assert e["Работы, ₽"] == 90000           # отменённая заявка не учитывается
    assert e["Маржа, ₽"] == 192000
    assert e["Маржа, %"] == 64.0


def test_object_duplicate_code():
    objects.create_object("С-26-001", "Объект")
    with pytest.raises(ValueError):
        objects.create_object("С-26-001", "Объект-дубль")


def test_object_dates_order():
    from datetime import date
    with pytest.raises(ValueError):
        objects.create_object("С-26-002", "Объект", start_date=date(2026, 10, 1),
                              end_date=date(2026, 9, 1))


def test_search_orders_sql_filters(setup):
    obj, _, _ = setup
    assert len(orders.search_orders("ОСВЕЩЕНИЯ")) == 1   # без учёта регистра
    assert len(orders.search_orders(status="Отменена")) == 1
    assert len(orders.search_orders(object_id=obj.id)) == 2
    assert orders.search_orders("нет такой работы") == []


def test_assign_team(setup):
    _, _, o1 = setup
    a = workers.hire_worker("Лаптев Глеб Андреевич", "Электромонтажник")
    b = workers.hire_worker("Зуев Кирилл Олегович", "Электромонтажник")
    assert orders.update_order(o1.id, "В работе", 90000, [a.id, b.id])
    names = sorted(w.name for w in orders.get_order(o1.id).workers)
    assert names == ["Зуев Кирилл Олегович", "Лаптев Глеб Андреевич"]


def test_update_order_bad_status(setup):
    _, _, o1 = setup
    assert orders.update_order(o1.id, "Непонятный", 1, []) is False
