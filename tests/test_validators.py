"""
Unit-тесты для модуля validators.

Проверяют граничные случаи функций валидации: пустые строки,
слишком короткие/длинные значения, отрицательные числа,
некорректный формат PIN.
"""
from validators import (  # noqa: E402
    validate_code, validate_name, validate_pin, validate_price, validate_qty,
    validate_stock,
)


# ----- validate_name -----
def test_validate_name_ok():
    ok, msg = validate_name("Иван Иванов")
    assert ok is True
    assert msg == ""


def test_validate_name_empty():
    ok, msg = validate_name("")
    assert ok is False
    assert "не должно" in msg


def test_validate_name_only_spaces():
    ok, _ = validate_name("   ")
    assert ok is False


def test_validate_name_too_short():
    ok, _ = validate_name("И")  # 1 символ < минимум 2
    assert ok is False


# ----- validate_price -----
def test_validate_price_ok():
    ok, _ = validate_price(1500.50)
    assert ok is True


def test_validate_price_negative():
    ok, msg = validate_price(-1)
    assert ok is False
    assert "отрицательным" in msg


def test_validate_price_too_big():
    ok, _ = validate_price(150_000_000)
    assert ok is False


# ----- validate_stock -----
def test_validate_stock_ok():
    ok, _ = validate_stock(50)
    assert ok is True


def test_validate_stock_negative():
    ok, _ = validate_stock(-5)
    assert ok is False


# ----- validate_pin -----
def test_validate_pin_ok():
    ok, _ = validate_pin("1234")
    assert ok is True


def test_validate_pin_wrong_length():
    ok, _ = validate_pin("12")
    assert ok is False


def test_validate_pin_letters():
    ok, _ = validate_pin("ab12")
    assert ok is False


# ----- validate_qty -----
def test_validate_qty_fraction_ok():
    ok, _ = validate_qty(12.5)
    assert ok is True


def test_validate_qty_zero():
    ok, msg = validate_qty(0)
    assert ok is False
    assert "больше нуля" in msg


def test_validate_qty_nan_from_excel():
    ok, _ = validate_qty(float("nan"))
    assert ok is False


# ----- validate_code -----
def test_validate_code_ok():
    assert validate_code("С-26-031")[0] is True
    assert validate_code("МП-001")[0] is True


def test_validate_code_bad_symbols():
    ok, _ = validate_code("МП 001;DROP")
    assert ok is False
