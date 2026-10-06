"""
Сервис сотрудников.
"""
from typing import List, Optional

from sqlalchemy import select

from database import Worker, session_scope
from logger import log
from validators import validate_name


def list_workers() -> List[Worker]:
    with session_scope() as s:
        return list(s.scalars(select(Worker).order_by(Worker.name)))


def find_by_name(name: str) -> Optional[Worker]:
    with session_scope() as s:
        return s.scalar(select(Worker).where(Worker.name == name.strip()))


def hire_worker(name: str, specialty: str, phone: str = "") -> Worker:
    """Добавить сотрудника.

    :raises ValueError: если ФИО или должность не прошли проверку.
    """
    for ok, msg in (validate_name(name, field="ФИО"),
                    validate_name(specialty, field="должность")):
        if not ok:
            log.warning("Не удалось добавить сотрудника: %s", msg)
            raise ValueError(msg)
    with session_scope() as s:
        w = Worker(name=name.strip(), specialty=specialty.strip(),
                   phone=(phone or "").strip())
        s.add(w)
        s.flush()
        log.info("Добавлен сотрудник id=%s %s", w.id, w.name)
        return w


def fire_worker(worker_id: int) -> bool:
    """Удалить сотрудника из справочника."""
    with session_scope() as s:
        w = s.get(Worker, worker_id)
        if w is None:
            log.warning("Сотрудник id=%s не найден", worker_id)
            return False
        s.delete(w)
    log.info("Сотрудник id=%s удалён", worker_id)
    return True
