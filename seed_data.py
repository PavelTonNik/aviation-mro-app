# seed_data.py
from backend.database import SessionLocal, engine
from backend import models

# --- ВАЖНО: Эта строка создает пустые таблицы, если их нет ---
models.Base.metadata.create_all(bind=engine)
# ------------------------------------------------------------

# Создаем сессию
db = SessionLocal()

def seed():
    print("--- Начало загрузки данных ---")
    
    # 1. Создаем Локации (Cities & Shops)
    locations = [
        {"name": "SHJ", "city": "Sharjah"},
        {"name": "FRU", "city": "Bishkek"},
        {"name": "FUJ", "city": "Fujairah"},
        {"name": "MIAMI", "city": "Miami"},
        {"name": "Rome (Italy)", "city": "Rome (Italy)"},
        {"name": "Main Shop", "city": "Sharjah Base"},
    ]
    
    for loc in locations:
        exists = db.query(models.Location).filter_by(name=loc["name"]).first()
        if not exists:
            new_loc = models.Location(name=loc["name"], city=loc["city"])
            db.add(new_loc)
    
    # 2. Создаем Самолеты (Fleet)
    aircrafts = [
        {"tail_number": "EX-BAT", "model": "Boeing 737"},
        {"tail_number": "EX-BAR", "model": "Boeing 737"},
        {"tail_number": "EX-BAQ", "model": "Boeing 737"},
    ]
    
    for ac in aircrafts:
        exists = db.query(models.Aircraft).filter_by(tail_number=ac["tail_number"]).first()
        if not exists:
            new_ac = models.Aircraft(tail_number=ac["tail_number"], model=ac["model"])
            db.add(new_ac)

    db.commit() # Сохраняем, чтобы получить ID

    # Получаем ID для привязки
    shj_loc = db.query(models.Location).filter_by(name="SHJ").first()
    shop_loc = db.query(models.Location).filter_by(name="Main Shop").first()
    bat_plane = db.query(models.Aircraft).filter_by(tail_number="EX-BAT").first()

    # 3. Создаем тестовые Двигатели с новыми полями
    if not db.query(models.Engine).first():
        engines = [
            # Двигатель 1: SV
            models.Engine(
                original_sn="CFM56-3-72001",
                current_sn="850123",
                status="SV",
                location_id=shj_loc.id,
                total_time=12000.5,
                total_cycles=4500
            ),
            # Двигатель 2: US
            models.Engine(
                original_sn="CFM56-3-72002",
                current_sn="850124",
                status="US",
                location_id=shop_loc.id,
                total_time=14500.0,
                total_cycles=5100
            ),
            # Двигатель 3: INSTALLED (с параметрами N1/N2)
            models.Engine(
                original_sn="CFM56-3-72003",
                current_sn="850125",
                status="INSTALLED",
                aircraft_id=bat_plane.id,
                position=1,
                total_time=8000.2,
                total_cycles=3000,
                # Мониторинг
                n1_takeoff=98.5,
                n1_cruise=88.2,
                n2_takeoff=92.1,
                n2_cruise=85.4
            ),
        ]
        db.add_all(engines)
        db.commit()
        print("--- Данные успешно загружены! ---")
    else:
        print("--- Данные уже существуют ---")

    db.close()

if __name__ == "__main__":
    seed()