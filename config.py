"""
Модуль загрузки конфигурации приложения.

Считывает параметры из файла config.json и предоставляет их остальным модулям
в виде словаря. Основные параметры (путь к БД, журналирование, справочники
статусов и единиц измерения) меняются без правок в коде.

Адрес базы данных можно переопределить переменной окружения
PROSCHET_DB_URL - так тесты работают на отдельной временной базе.
"""
import json
import os
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


def load_config(path: str = _CONFIG_FILE) -> Dict[str, Any]:
    """Загрузить конфигурацию приложения из JSON-файла.

    :param path: Путь к JSON-файлу конфигурации.
    :return: Словарь с параметрами конфигурации.
    :raises FileNotFoundError: Если файл конфигурации не найден.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Файл конфигурации не найден: {path}. "
            "Убедитесь, что config.json лежит в корне проекта."
        )
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    env_url = os.environ.get("PROSCHET_DB_URL")
    if env_url:
        cfg["database"]["url"] = env_url
    elif cfg["database"]["url"].startswith("sqlite:///") and not \
            cfg["database"]["url"].startswith("sqlite:////"):
        # Относительный путь к SQLite считаем от папки проекта,
        # чтобы база не создавалась там, откуда запустили программу.
        rel = cfg["database"]["url"][len("sqlite:///"):]
        cfg["database"]["url"] = "sqlite:///" + os.path.join(BASE_DIR, rel)
    return cfg


CONFIG: Dict[str, Any] = load_config()
