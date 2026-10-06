"""
Модуль настройки журналирования.

Создаёт логгер с двумя обработчиками:
1. Запись в файл с ротацией - для постоянного хранения событий.
2. Вывод в консоль - для отладки.

Уровень и параметры файла берутся из config.json.
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

from config import BASE_DIR, CONFIG


def setup_logger(name: Optional[str] = None) -> logging.Logger:
    """Создать и настроить логгер.

    :param name: Имя логгера.
    :return: Настроенный объект logging.Logger.
    """
    log_cfg = CONFIG["logging"]
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, log_cfg["level"], logging.INFO))
    formatter = logging.Formatter(log_cfg["format"])

    file_handler = RotatingFileHandler(
        filename=os.path.join(BASE_DIR, log_cfg["file"]),
        maxBytes=log_cfg["max_bytes"],
        backupCount=log_cfg["backup_count"],
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


log = setup_logger("ProschetProfi")
