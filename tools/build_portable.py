"""
Сборка переносной версии «ПросчётПрофи» для Windows.

Результат - папка и ZIP-архив, которые работают на любом компьютере
с Windows 10/11 x64 без установки Python и без доступа в интернет:

    ProschetProfi/
        Запуск ПросчётПрофи.bat   - запуск двойным щелчком
        ПРОЧТИ.txt
        app/                       - программа
        python/                    - встраиваемый Python 3.13 с библиотеками

Перед сборкой в папке кэша должны лежать:
    py.zip         - python-3.13.x-embed-amd64.zip с python.org
    site-packages/ - библиотеки под win_amd64 (pip install --target
                     --platform win_amd64 --only-binary=:all:)

Запуск:  python tools/build_portable.py <папка_кэша> <папка_результата>
"""
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_ITEMS = ["app.py", "launcher.py", "config.py", "config.json", "database.py",
             "logger.py", "validators.py", "requirements.txt", "README.md",
             "services", "tools", "tests", "sample_data", "Image", ".streamlit", "deploy"]

BAT = r"""@echo off
chcp 65001 >nul
title ПросчётПрофи - ООО СтройМонтаж
cd /d "%~dp0"
if not exist "python\python.exe" (
  echo Не найдена папка python. Распакуйте архив целиком и запустите снова.
  pause
  exit /b 1
)
echo Запуск ПросчётПрофи. Браузер откроется автоматически.
echo Не закрывайте это окно, пока работаете с программой.
echo.
"python\python.exe" "app\launcher.py"
if errorlevel 1 pause
"""

README = """ПросчётПрофи 2.0 - учёт материалов и работ на объектах
ООО «СтройМонтаж»

ЗАПУСК
1. Распакуйте архив целиком в любую папку (например, на рабочий стол).
   Запускать прямо из архива нельзя.
2. Дважды щёлкните «Запуск ПросчётПрофи.bat».
3. Через 5-15 секунд программа откроется в браузере.
   Чёрное окно не закрывайте - это сервер программы.
   Закрыли окно - программа остановилась.

Python и интернет не нужны: всё необходимое лежит в папке python.
Требования: Windows 10 или 11, 64 бита.

PIN для разделов «Персонал» и «Импорт из Excel»: 1234

ДАННЫЕ
База - файл app\\proschet.db. При первом запуске в неё загружаются
демонстрационные данные из app\\sample_data (выгрузки Excel).
Чтобы вернуть демо-данные, удалите proschet.db и запустите программу снова.

ЕСЛИ НЕ ЗАПУСКАЕТСЯ
- Windows SmartScreen: «Подробнее» - «Выполнить в любом случае».
- Антивирус может проверять python.exe при первом запуске - подождите.
- Браузер не открылся: откройте вручную адрес из чёрного окна
  (обычно http://localhost:8501).
"""

PTH = "python313.zip\n.\nLib\\site-packages\n..\\app\nimport site\n"


def _ignore(_dir, names):
    return [n for n in names if n in ("__pycache__", ".pytest_cache", ".DS_Store")
            or n == "backups" or n.endswith((".pyc", ".db", ".db-wal", ".db-shm", ".log"))]


def build(cache: str, out_dir: str) -> str:
    dist = os.path.join(out_dir, "ProschetProfi")
    if os.path.exists(dist):
        shutil.rmtree(dist)
    os.makedirs(dist)

    # Программа
    app = os.path.join(dist, "app")
    os.makedirs(app)
    for item in APP_ITEMS:
        src = os.path.join(ROOT, item)
        dst = os.path.join(app, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=_ignore)
        else:
            shutil.copy2(src, dst)

    # Встраиваемый Python + библиотеки
    py = os.path.join(dist, "python")
    with zipfile.ZipFile(os.path.join(cache, "py.zip")) as z:
        z.extractall(py)
    for name in os.listdir(py):
        if name.endswith("._pth"):
            with open(os.path.join(py, name), "w", encoding="utf-8") as f:
                f.write(PTH)
    shutil.copytree(os.path.join(cache, "site-packages"),
                    os.path.join(py, "Lib", "site-packages"),
                    ignore=shutil.ignore_patterns("__pycache__", "tests", "*.pyc"))

    # Запуск и инструкция. Батник - с переводами строк Windows.
    with open(os.path.join(dist, "Запуск ПросчётПрофи.bat"), "w",
              encoding="utf-8", newline="\r\n") as f:
        f.write(BAT)
    with open(os.path.join(dist, "ПРОЧТИ.txt"), "w", encoding="utf-8-sig",
              newline="\r\n") as f:
        f.write(README)

    # Архив. Имена в UTF-8 с флагом, чтобы Проводник Windows
    # показал кириллицу без «кракозябр».
    archive = os.path.join(out_dir, "ПросчётПрофи_Windows.zip")
    if os.path.exists(archive):
        os.remove(archive)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, _dirs, files in os.walk(dist):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, out_dir))
    return archive


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    path = build(sys.argv[1], sys.argv[2])
    print(f"Готово: {path} ({os.path.getsize(path) / 1024 / 1024:.0f} МБ)")
