"""
Unit-тесты для модуля авторизации (services/auth.py).
"""
from services.auth import hash_pin, check_pin, is_section_protected  # noqa: E402


def test_hash_pin_consistent():
    """Один и тот же PIN всегда даёт одинаковый хеш."""
    h1 = hash_pin("1234")
    h2 = hash_pin("1234")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex = 64 символа


def test_hash_pin_different():
    """Разные PIN дают разные хеши."""
    assert hash_pin("1234") != hash_pin("4321")


def test_check_pin_default():
    """Проверка PIN по умолчанию '1234' (хеш зашит в config.json)."""
    assert check_pin("1234") is True


def test_check_pin_wrong():
    assert check_pin("0000") is False


def test_check_pin_invalid_format():
    """Невалидный формат PIN не должен проходить."""
    assert check_pin("abcd") is False
    assert check_pin("12") is False


def test_is_section_protected():
    """Служебные разделы закрыты PIN-кодом, рабочие - открыты."""
    assert is_section_protected("Персонал") is True
    assert is_section_protected("Импорт из Excel") is True
    assert is_section_protected("Сервис") is True
    assert is_section_protected("Склад") is False
