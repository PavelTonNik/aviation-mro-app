# Создание таблиц для аутентификации и первого админа
from backend import models, database
import hashlib

def hash_password(password: str) -> str:
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_auth_tables():
    print("Создание таблиц для аутентификации...")
    try:
        # Создаем все таблицы
        models.Base.metadata.create_all(bind=database.engine)
        print("✅ Таблицы users и notifications успешно созданы!")
        
        # Создаем первого админа
        db = database.SessionLocal()
        try:
            # Проверяем, есть ли уже админ
            admin = db.query(models.User).filter(models.User.username == "admin").first()
            
            if not admin:
                admin = models.User(
                    username="admin",
                    password_hash=hash_password("admin123"),  # Пароль по умолчанию
                    first_name="Admin",
                    last_name="User",
                    position="Administrator",
                    role="admin",
                    is_active=True
                )
                db.add(admin)
                db.commit()
                print("\n✅ Создан первый админ:")
                print("   Username: admin")
                print("   Password: admin123")
                print("   ⚠️  ОБЯЗАТЕЛЬНО СМЕНИТЕ ПАРОЛЬ ПОСЛЕ ПЕРВОГО ВХОДА!")
            else:
                print("\n✅ Админ уже существует в системе")
        finally:
            db.close()
        
        # Проверяем
        import sqlite3
        conn = sqlite3.connect('aviation_mro.db')
        cursor = conn.cursor()
        
        # Проверяем таблицу users
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if cursor.fetchone():
            print("\n✅ Таблица users создана!")
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            print(f"   Пользователей в системе: {count}")
        
        # Проверяем таблицу notifications
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'")
        if cursor.fetchone():
            print("✅ Таблица notifications создана!")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    create_auth_tables()
