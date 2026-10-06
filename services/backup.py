"""
Сервис резервного копирования и восстановления базы данных.

Копия снимается штатным механизмом SQLite (Connection.backup): он
корректно копирует базу даже во время работы программы, в отличие
от простого копирования файла, которое может захватить
недописанную транзакцию.

- create_backup()   - снять копию в папку backups/;
- auto_backup()     - снять копию, если сегодня её ещё не было
                      (вызывается при каждом запуске программы);
- list_backups()    - список копий, новые сверху;
- restore_backup()  - восстановить базу из копии, предварительно
                      сохранив текущее состояние.
Хранится не больше keep последних копий, старые удаляются.
"""
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from config import BASE_DIR, CONFIG
from database import engine
from logger import log

_CFG = CONFIG.get("backup", {})
BACKUP_DIR = os.path.join(BASE_DIR, _CFG.get("dir", "backups"))
KEEP = int(_CFG.get("keep", 14))
PREFIX = "proschet_"


def _db_path() -> str:
    return engine.url.database


def _copy(src: str, dst: str) -> None:
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)


def _rotate() -> None:
    files = sorted(f for f in os.listdir(BACKUP_DIR)
                   if f.startswith(PREFIX) and f.endswith(".db"))
    for old in files[:-KEEP] if len(files) > KEEP else []:
        os.remove(os.path.join(BACKUP_DIR, old))
        log.info("Удалена старая резервная копия %s", old)


def create_backup(note: str = "") -> str:
    """Снять резервную копию. :return: путь к файлу копии."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{note}" if note else ""
    path = os.path.join(BACKUP_DIR, f"{PREFIX}{stamp}{suffix}.db")
    _copy(_db_path(), path)
    log.info("Создана резервная копия %s", os.path.basename(path))
    _rotate()
    return path


def list_backups() -> List[Dict]:
    if not os.path.isdir(BACKUP_DIR):
        return []
    rows = []
    for f in os.listdir(BACKUP_DIR):
        if f.startswith(PREFIX) and f.endswith(".db"):
            p = os.path.join(BACKUP_DIR, f)
            rows.append({"file": f, "path": p,
                         "size_kb": round(os.path.getsize(p) / 1024, 1),
                         "created": datetime.fromtimestamp(os.path.getmtime(p))})
    return sorted(rows, key=lambda r: r["file"], reverse=True)


def auto_backup() -> Optional[str]:
    """Ежедневная копия при запуске: снимается, если за сегодня копии нет."""
    today = datetime.now().strftime("%Y%m%d")
    if any(b["file"].startswith(PREFIX + today) for b in list_backups()):
        return None
    return create_backup("auto")


def restore_backup(file_name: str) -> str:
    """Восстановить базу из копии.

    Перед восстановлением текущая база сохраняется отдельной копией
    с пометкой before_restore, чтобы восстановление можно было отменить.
    :return: путь к копии состояния до восстановления.
    """
    src = os.path.join(BACKUP_DIR, os.path.basename(file_name))
    if not os.path.exists(src):
        raise ValueError(f"Резервная копия {file_name} не найдена.")
    with sqlite3.connect(src) as c:
        ok = c.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise ValueError(f"Копия {file_name} повреждена: {ok}")
    before = create_backup("before_restore")
    engine.dispose()  # закрыть открытые соединения пула
    _copy(src, _db_path())
    log.warning("База восстановлена из копии %s", file_name)
    return before
