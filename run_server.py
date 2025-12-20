"""
Запуск сервера без проблем с кириллицей
"""
import subprocess
import sys

print("=" * 40)
print("   STARTING FASTAPI SERVER")
print("=" * 40)
print()

try:
    subprocess.run([
        sys.executable, 
        "-m", 
        "uvicorn", 
        "backend.main:app", 
        "--reload",
        "--host", "127.0.0.1",
        "--port", "8000"
    ])
except KeyboardInterrupt:
    print("\n\nСервер остановлен")
except Exception as e:
    print(f"Ошибка: {e}")
    input("Нажмите Enter для выхода...")
