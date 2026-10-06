#!/bin/bash
# Запуск «ПросчётПрофи 2.0» (ООО «СтройМонтаж») на macOS двойным щелчком.
# При первом запуске создаётся окружение и ставятся библиотеки (1-2 минуты),
# дальше программа открывается сразу. Браузер откроется автоматически.

cd "$(dirname "$0")" || exit 1

if [ ! -d ".venv" ]; then
  echo "Первый запуск: создаю окружение и устанавливаю библиотеки (1-2 минуты)..."
  python3 -m venv .venv || { echo "Не найден Python 3. Установите его с https://python.org"; read -r _; exit 1; }
  ./.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  ./.venv/bin/python -m pip install -r requirements.txt || { echo "Ошибка установки зависимостей."; read -r _; exit 1; }
fi

./.venv/bin/python launcher.py
