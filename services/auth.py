"""
Сервис PIN-авторизации служебных разделов.

Защищает доступ к разделам «Персонал», «Импорт» и «Сервис» 4-значным
PIN-кодом. PIN хранится не в открытом виде, а как SHA-256 хеш
в config.json.

Версия 2.1: после max_attempts неверных попыток подряд ввод PIN
блокируется на lock_minutes минут. В версии 2.0 тест безопасности
показал, что все 10 000 комбинаций перебираются за доли секунды.
"""
import hashlib
import threading
import time
from typing import Tuple

from config import CONFIG
from logger import log
from validators import validate_pin


def hash_pin(pin: str) -> str:
    """Вычислить SHA-256 хеш PIN-кода.

    :param pin: PIN-код в открытом виде.
    :return: 64-символьная hex-строка.
    """
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def check_pin(entered_pin: str) -> bool:
    """Проверить введённый PIN: совпадает ли его хеш с эталонным.

    :param entered_pin: PIN, введённый пользователем.
    :return: True если PIN корректный.
    """
    ok, _ = validate_pin(entered_pin)
    if not ok:
        return False
    expected_hash = CONFIG["auth"]["default_pin_hash"]
    actual_hash = hash_pin(entered_pin)
    result = actual_hash == expected_hash
    if result:
        log.info("Успешная авторизация PIN")
    else:
        log.warning("Неудачная попытка ввода PIN")
    return result


def is_section_protected(section_name: str) -> bool:
    """Защищён ли раздел PIN-кодом (берётся из config.json)."""
    protected = CONFIG["auth"]["pin_required_sections"]
    return any(p.lower() in section_name.lower() for p in protected)


# ----- Ограничение числа попыток -----
_LOCK = threading.Lock()
_STATE = {"fails": 0, "locked_until": 0.0}
MAX_ATTEMPTS = int(CONFIG["auth"].get("max_attempts", 5))
LOCK_SECONDS = int(CONFIG["auth"].get("lock_minutes", 5)) * 60


def lock_remaining(now: float = None) -> int:
    """Сколько секунд осталось до снятия блокировки (0 — не заблокировано)."""
    now = time.time() if now is None else now
    return max(0, int(_STATE["locked_until"] - now + 0.999))


def check_pin_limited(entered_pin: str, now: float = None) -> Tuple[bool, str]:
    """Проверить PIN с учётом блокировки после серии ошибок.

    :return: (успех, сообщение для пользователя).
    """
    now = time.time() if now is None else now
    with _LOCK:
        left = lock_remaining(now)
        if left:
            log.warning("Попытка ввода PIN во время блокировки")
            return False, f"Ввод PIN заблокирован, повторите через {left // 60 + 1} мин."
        if check_pin(entered_pin):
            _STATE["fails"] = 0
            return True, ""
        _STATE["fails"] += 1
        rest = MAX_ATTEMPTS - _STATE["fails"]
        if rest <= 0:
            _STATE["fails"] = 0
            _STATE["locked_until"] = now + LOCK_SECONDS
            log.warning("Ввод PIN заблокирован на %s с после %s ошибок",
                        LOCK_SECONDS, MAX_ATTEMPTS)
            return False, (f"Неверный PIN. Ввод заблокирован на "
                           f"{LOCK_SECONDS // 60} мин.")
        return False, f"Неверный PIN. Осталось попыток: {rest}."


def reset_limiter() -> None:
    """Сбросить счётчик (для тестов и после смены PIN)."""
    with _LOCK:
        _STATE["fails"] = 0
        _STATE["locked_until"] = 0.0
