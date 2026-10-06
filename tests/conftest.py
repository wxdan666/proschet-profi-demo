"""
Общие настройки тестов.

До импорта модулей приложения база подменяется на временный файл -
тесты никогда не трогают рабочую базу proschet.db.
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="proschet_test_")
os.environ["PROSCHET_DB_URL"] = "sqlite:///" + os.path.join(_TMP, "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from database import reset_database  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """Каждый тест начинается с пустой базы."""
    reset_database()
    yield


@pytest.fixture
def tmp_dir():
    return tempfile.mkdtemp(prefix="proschet_xlsx_")
