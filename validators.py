"""
Модуль валидации пользовательского ввода.

Содержит набор функций, проверяющих корректность данных, которые
вводятся в формах приложения. Все функции возвращают кортеж
(ok: bool, message: str), где ok - признак валидности, message -
сообщение об ошибке (или пустая строка при успехе).
"""
from typing import Tuple

from config import CONFIG


_VALIDATION = CONFIG["validation"]


def validate_name(value: str, field: str = "имя") -> Tuple[bool, str]:
    """Проверить корректность имени или названия.

    Условия:
    - не пустая строка после strip();
    - длина в пределах [min_name_length; max_name_length] из конфига.

    :param value: Проверяемое значение.
    :param field: Название поля (используется в сообщении об ошибке).
    :return: (True, '') если ok, иначе (False, описание ошибки).
    """
    if value is None:
        return False, f"Поле «{field}» не должно быть пустым."
    cleaned = value.strip()
    if not cleaned:
        return False, f"Поле «{field}» не должно быть пустым."
    if len(cleaned) < _VALIDATION["min_name_length"]:
        return False, (
            f"Поле «{field}» слишком короткое "
            f"(минимум {_VALIDATION['min_name_length']} символа)."
        )
    if len(cleaned) > _VALIDATION["max_name_length"]:
        return False, (
            f"Поле «{field}» слишком длинное "
            f"(максимум {_VALIDATION['max_name_length']} символов)."
        )
    return True, ""


def validate_price(value: float, field: str = "цена") -> Tuple[bool, str]:
    """Проверить корректность денежной суммы.

    Условия:
    - не отрицательная;
    - не превышает max_price из конфига.
    """
    if value is None:
        return False, f"Поле «{field}» не должно быть пустым."
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, f"Поле «{field}» должно быть числом."
    if v < 0:
        return False, f"Поле «{field}» не может быть отрицательным."
    if v > _VALIDATION["max_price"]:
        return False, (
            f"Поле «{field}» слишком большое "
            f"(максимум {_VALIDATION['max_price']:.0f})."
        )
    return True, ""


def validate_stock(value: int, field: str = "количество") -> Tuple[bool, str]:
    """Проверить корректность целочисленного количества (например, остатков на складе).

    Условия: целое число в диапазоне [0; max_stock].
    """
    if value is None:
        return False, f"Поле «{field}» не должно быть пустым."
    try:
        v = int(value)
    except (TypeError, ValueError):
        return False, f"Поле «{field}» должно быть целым числом."
    if v < 0:
        return False, f"Поле «{field}» не может быть отрицательным."
    if v > _VALIDATION["max_stock"]:
        return False, (
            f"Поле «{field}» слишком большое "
            f"(максимум {_VALIDATION['max_stock']})."
        )
    return True, ""


def validate_pin(pin: str) -> Tuple[bool, str]:
    """Проверить корректность PIN-кода: 4 цифры."""
    if pin is None:
        return False, "Введите PIN-код."
    if not isinstance(pin, str):
        pin = str(pin)
    if not pin.isdigit():
        return False, "PIN должен содержать только цифры."
    if len(pin) != 4:
        return False, "PIN должен состоять из 4 цифр."
    return True, ""


def validate_qty(value: float, field: str = "количество") -> Tuple[bool, str]:
    """Проверить количество в операции движения материала.

    Условия: число строго больше нуля и не больше max_stock.
    Дробные значения допустимы (метры, килограммы, литры).
    """
    if value is None:
        return False, f"Поле «{field}» не должно быть пустым."
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, f"Поле «{field}» должно быть числом."
    if v != v:  # NaN из пустой ячейки Excel
        return False, f"Поле «{field}» не заполнено."
    if v <= 0:
        return False, f"Поле «{field}» должно быть больше нуля."
    if v > _VALIDATION["max_stock"]:
        return False, (
            f"Поле «{field}» слишком большое "
            f"(максимум {_VALIDATION['max_stock']})."
        )
    return True, ""


def validate_code(value: str, field: str = "код") -> Tuple[bool, str]:
    """Проверить код объекта или артикул материала.

    Допустимы буквы, цифры, дефис, точка и косая черта, 2-20 символов.
    """
    if value is None or not str(value).strip():
        return False, f"Поле «{field}» не должно быть пустым."
    v = str(value).strip()
    if not 2 <= len(v) <= 20:
        return False, f"Поле «{field}» должно содержать от 2 до 20 символов."
    allowed = set("-./_")
    if not all(ch.isalnum() or ch in allowed for ch in v):
        return False, (
            f"Поле «{field}» может содержать только буквы, цифры и знаки - . / _"
        )
    return True, ""
