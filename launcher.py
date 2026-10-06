"""
Запускалка «ПросчётПрофи» для батника и переносной сборки.

1. Переходит в папку программы (иначе Streamlit не найдёт тему
   в .streamlit/config.toml).
2. Если базы нет - загружает демонстрационные данные СтройМонтаж.
3. Находит свободный порт, начиная с 8501: на компьютере уже может
   работать другая копия или чужая программа.
4. Запускает сервер Streamlit без интерактивных вопросов и открывает
   браузер, как только сервер начал отвечать.

Окно консоли остаётся открытым: его закрытие останавливает программу.
"""
import os
import socket
import subprocess
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port(start: int = 8501, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("Не найден свободный порт 8501-8520.")


def wait_ready(port: int, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def main() -> int:
    os.chdir(HERE)
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")

    if not os.path.exists(os.path.join(HERE, "proschet.db")):
        print("Первый запуск: загружаю демонстрационные данные СтройМонтаж...")
        subprocess.run([sys.executable, os.path.join("tools", "seed_demo.py")],
                       env=env, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)

    port = free_port()
    url = f"http://localhost:{port}"
    print(f"Запускаю ПросчётПрофи на {url} ...")
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.headless", "true", "--server.port", str(port),
         "--server.address", "localhost"],
        env=env,
    )
    if wait_ready(port):
        webbrowser.open(url)
        print(f"\nПрограмма работает: {url}")
        print("Чтобы остановить - закройте это окно.\n")
    else:
        print("Сервер не ответил за 90 секунд, смотрите сообщения выше.")
    try:
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
