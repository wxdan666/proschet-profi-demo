@echo off
chcp 65001 >nul
rem Запуск приложения "ПросчётПрофи" на Windows двойным щелчком.
rem При первом запуске создаётся локальное окружение и ставятся библиотеки (1-2 минуты),
rem дальше приложение открывается сразу. Браузер откроется автоматически.

cd /d "%~dp0"

rem Подавляем первый интерактивный запрос e-mail у Streamlit
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

if not exist ".venv" (
  echo Первый запуск: создаю окружение и устанавливаю библиотеки (1-2 минуты)...
  python -m venv .venv
  if errorlevel 1 (
    echo Не найден Python. Установите его с https://python.org и при установке
    echo поставьте галочку "Add Python to PATH".
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Ошибка установки зависимостей.
    pause
    exit /b 1
  )
)

if not exist "proschet.db" (
  echo База не найдена: загружаю демонстрационные данные СтройМонтаж...
  ".venv\Scripts\python.exe" tools\seed_demo.py >nul 2>&1
)

echo Запуск "ПросчётПрофи"... Браузер откроется автоматически (http://localhost:8501).
echo Чтобы остановить программу - закройте это окно.
".venv\Scripts\python.exe" -m streamlit run app.py
pause
