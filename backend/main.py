from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import json
from pathlib import Path
import hashlib
import secrets

try:
    from . import models, database
except ImportError:  # fallback when running as a standalone script
    import models
    import database

# Создаем таблицы в БД (если их нет)
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Aviation MRO System")
# --- ВСТАВИТЬ ЭТО В backend/main.py ПОСЛЕ app = FastAPI(...) ---

@app.on_event("startup")
def startup_event():
    ensure_sqlite_column("aircrafts", "initial_total_time FLOAT DEFAULT 0")
    ensure_sqlite_column("aircrafts", "initial_total_cycles INTEGER DEFAULT 0")
    ensure_sqlite_column("aircrafts", "last_atlb_ref TEXT")
    ensure_sqlite_column("action_logs", "is_maintenance BOOLEAN DEFAULT 0")
    ensure_sqlite_column("action_logs", "atlb_ref TEXT")
    ensure_sqlite_column("action_logs", "maintenance_type TEXT")
    ensure_sqlite_column("action_logs", "block_time_str TEXT")
    ensure_sqlite_column("action_logs", "flight_time_str TEXT")
    ensure_sqlite_column("action_logs", "block_out_str TEXT")
    ensure_sqlite_column("action_logs", "block_in_str TEXT")
    ensure_sqlite_column("action_logs", "flight_off_str TEXT")
    ensure_sqlite_column("action_logs", "flight_on_str TEXT")
    ensure_sqlite_column("action_logs", "from_apt TEXT")
    ensure_sqlite_column("action_logs", "to_apt TEXT")
    ensure_sqlite_column("action_logs", "oil_1 FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "oil_2 FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "oil_3 FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "oil_4 FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "oil_apu FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "hyd_1 FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "hyd_2 FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "hyd_3 FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "hyd_4 FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "performed_by TEXT")

    # Открываем сессию базы данных
    db = database.SessionLocal()
    try:
        # 1. Если нет Локаций -> Создаем базовые (SHJ, FRU, DXB, MIAMI, ROME)
        if not db.query(models.Location).first():
            print("База пуста. Создаем пустые окна Локаций...")
            locations = [
                models.Location(name="SHJ", city="Sharjah"),
                models.Location(name="FRU", city="Bishkek"),
                models.Location(name="DXB", city="Dubai"),
                models.Location(name="MIAMI", city="Miami"),
                models.Location(name="Rome (Italy)", city="Rome (Italy)")
            ]
            db.add_all(locations)
            db.commit()
        else:
            # Обновляем устаревшую запись KBL -> MIAMI и добавляем новые базовые локации
            legacy_kbl = db.query(models.Location).filter(models.Location.name == "KBL").first()
            if legacy_kbl:
                existing_miami = db.query(models.Location).filter(models.Location.name == "MIAMI").first()
                if existing_miami:
                    legacy_kbl.name = "Rome (Italy)"
                    legacy_kbl.city = "Rome (Italy)"
                else:
                    legacy_kbl.name = "MIAMI"
                    legacy_kbl.city = "Miami"
                db.commit()

            desired_locations = [
                {"name": "SHJ", "city": "Sharjah"},
                {"name": "FRU", "city": "Bishkek"},
                {"name": "DXB", "city": "Dubai"},
                {"name": "MIAMI", "city": "Miami"},
                {"name": "Rome (Italy)", "city": "Rome (Italy)"}
            ]

            for cfg in desired_locations:
                loc = db.query(models.Location).filter(models.Location.name == cfg["name"]).first()
                if loc:
                    if loc.city != cfg["city"]:
                        loc.city = cfg["city"]
                else:
                    db.add(models.Location(name=cfg["name"], city=cfg["city"]))
            db.commit()

        # 2. Если нет Самолетов -> Создаем базовый флот
        if not db.query(models.Aircraft).first():
            print("База пуста. Создаем пустые окна Флота...")
            aircrafts = [
                models.Aircraft(tail_number="ER-BAT", model="Boeing 747-200", msn="22545"),
                models.Aircraft(tail_number="ER-BAR", model="Boeing 747-200", msn="23813"),
                models.Aircraft(tail_number="ER-BAQ", model="Boeing 747-200", msn="239139")
            ]
            db.add_all(aircrafts)
            db.commit()

        # 3. Применяем базовые значения налета/ATLB для флота (если еще не заданы)
        fleet = db.query(models.Aircraft).all()
        for ac in fleet:
            baseline = get_baseline_for_tail(ac.tail_number)
            if not baseline:
                continue

            base_hours = hhmm_to_hours(baseline.get("initial_ttsn"))
            base_cycles = baseline.get("initial_tcsn", 0) or 0

            if ac.initial_total_time in (None, 0):
                ac.initial_total_time = base_hours
            if ac.initial_total_cycles in (None, 0):
                ac.initial_total_cycles = base_cycles

            if (ac.total_time or 0) < base_hours:
                ac.total_time = base_hours
            if (ac.total_cycles or 0) < base_cycles:
                ac.total_cycles = base_cycles

            if baseline.get("last_atlb") and not ac.last_atlb_ref:
                ac.last_atlb_ref = baseline.get("last_atlb")

            if baseline.get("msn") and (not ac.msn or ac.msn != baseline.get("msn")):
                ac.msn = baseline.get("msn")

        db.commit()
            
    except Exception as e:
        print(f"Ошибка при создании структуры: {e}")
    finally:
        db.close()
# 1. Подключаем папку frontend как хранилище статических файлов
# Используем абсолютный путь, чтобы сервер всегда брал нужную копию фронтенда.
BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# 2. Главная страница
@app.get("/")
def read_index():
    return FileResponse(FRONTEND_DIR / "index.html")

# Dependency (получение сессии БД)
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Current user resolver: requires ?user_id= in query params (admin-only endpoints)
def get_current_user(user_id: int = Query(..., alias="user_id"), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")
    return user

def parse_input_date(date_value: Optional[str]):
    """Convert user-supplied date strings to datetime objects when possible."""
    if not date_value:
        return None
    cleaned = date_value.strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
    return None


def hhmm_to_hours(value: Optional[str]) -> float:
    """Convert a HH:MM style string to decimal hours."""
    if not value:
        return 0.0
    cleaned = value.strip()
    if not cleaned:
        return 0.0
    if ':' not in cleaned:
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    hours_part, minutes_part = cleaned.split(':', 1)
    try:
        hours_val = int(hours_part)
    except ValueError:
        return 0.0
    try:
        minutes_val = int(minutes_part)
    except ValueError:
        minutes_val = 0
    minutes_val = max(0, min(minutes_val, 59))
    return hours_val + minutes_val / 60.0


def hours_to_hhmm(hours: Optional[float]) -> str:
    """Convert decimal hours to HH:MM string (rounded to the nearest minute)."""
    if hours is None:
        return "0:00"
    total_minutes = int(round(hours * 60))
    total_minutes = max(0, total_minutes)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh}:{mm:02d}"


def increment_atlb_ref(ref: Optional[str]) -> Optional[str]:
    if not ref:
        return None
    ref = ref.strip()
    if not ref:
        return None
    # Split prefix and numeric suffix
    prefix = ref.rstrip('0123456789')
    suffix = ref[len(prefix):]
    if not suffix:
        return ref
    try:
        number = int(suffix)
    except ValueError:
        return ref
    width = len(suffix)
    return f"{prefix}{number + 1:0{width}d}"


def extract_atlb_ref(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    ref = raw.strip()
    if not ref:
        return None
    if not ref.upper().startswith("ATLB:"):
        return None
    ref = ref.split(":", 1)[1].strip()
    if "|" in ref:
        ref = ref.split("|", 1)[0].strip()
    return ref or None


def normalize_time_str(value: Optional[str], default: str = "") -> str:
    if not value:
        return default
    value = value.strip()
    if not value:
        return default
    if ":" in value:
        parts = value.split(":", 1)
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            minutes = max(0, min(minutes, 59))
            return f"{hours:02d}:{minutes:02d}"
        except ValueError:
            return value
    return value


def sanitize_time_input(value: Optional[str]) -> Optional[str]:
    normalized = normalize_time_str(value, "")
    return normalized if normalized else None


def time_str_to_minutes(value: Optional[str]) -> Optional[int]:
    sanitized = sanitize_time_input(value)
    if not sanitized:
        return None
    if ":" not in sanitized:
        return None
    parts = sanitized.split(":", 1)
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        return None
    minutes = max(0, min(minutes, 59))
    total_minutes = max(0, hours) * 60 + minutes
    return total_minutes


def compute_time_diff(start_value: Optional[str], end_value: Optional[str]) -> Optional[str]:
    start_minutes = time_str_to_minutes(start_value)
    end_minutes = time_str_to_minutes(end_value)
    if start_minutes is None or end_minutes is None:
        return None
    diff = end_minutes - start_minutes
    if diff < 0:
        diff += 24 * 60
    hours = diff // 60
    minutes = diff % 60
    return f"{hours:02d}:{minutes:02d}"


def ensure_sqlite_column(table_name: str, column_definition: str):
    """Add column to SQLite table if it does not exist.
    No-op when using non-SQLite databases (e.g., PostgreSQL).
    """
    try:
        # Skip for non-SQLite engines
        from . import database as dbmod
    except ImportError:
        import database as dbmod

    if not getattr(dbmod, "IS_SQLITE", True):
        return

    column_name = column_definition.split()[0]
    with dbmod.engine.connect() as conn:
        result = conn.execute(text(f"PRAGMA table_info({table_name})"))
        existing = {row[1] for row in result}
        if column_name not in existing:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}"))


BASELINE_UTILIZATION = {
    "ER-BAQ": {
        "initial_ttsn": "102071:09",
        "initial_tcsn": 18880,
        "last_atlb": "D00900",
        "last_date": "01.12.2025",
        "msn": "23139",
    },
    "ER-BAR": {
        "initial_ttsn": "105362:07",
        "initial_tcsn": 20454,
        "last_atlb": "B02585",
        "last_date": "12.11.2025",
        "msn": "22545",
    },
    "ER-BAT": {
        "initial_ttsn": "102868:46",
        "initial_tcsn": 17513,
        "last_atlb": "A03032",
        "last_date": "25.11.2025",
        "msn": "23813",
    },
}


def get_baseline_for_tail(tail_number: Optional[str]):
    if not tail_number:
        return None
    if tail_number in BASELINE_UTILIZATION:
        return BASELINE_UTILIZATION[tail_number]
    suffix = tail_number.split('-')[-1] if '-' in tail_number else tail_number
    for key, cfg in BASELINE_UTILIZATION.items():
        if key.endswith(suffix):
            return cfg
    return None

# --- Pydantic Schemas (Для валидации данных с форм) ---
class InstallSchema(BaseModel):
    date: str
    engine_id: int
    aircraft_id: int
    position: int
    tt: float
    tc: int
    remarks: Optional[str] = ""


class ShipmentSchema(BaseModel):
    date: str
    engine_id: int
    to_location_id: int  # Куда отправляем (ID локации)
    waybill: Optional[str] = "" # Номер накладной
    remarks: Optional[str] = ""

class RemoveSchema(BaseModel):
    date: str
    engine_id: int
    to_location_id: int # Куда положили снятый двигатель
    reason: Optional[str] = ""


class RepairSchema(BaseModel):
    date: str
    engine_id: int
    vendor: str         # Название мастерской (Lufthansa, GE, etc.)
    work_order: str     # Номер заказ-наряда
    tt: float           # Наработка после ремонта
    tc: int
    photo_url: Optional[str] = ""
    remarks: Optional[str] = ""


class PartActionSchema(BaseModel):
    date: str
    action: str       # INSTALLED, REMOVED, SWAP
    part_name: str
    part_number: str
    serial_number: str
    quantity: int


class StoreItemSchema(BaseModel):
    received_date: Optional[str] = None
    part_name: str
    part_number: str
    serial_number: Optional[str] = ""
    condition: Optional[str] = ""
    quantity: int = 1
    unit: Optional[str] = ""
    location: Optional[str] = ""
    shelf: Optional[str] = ""
    owner: Optional[str] = ""
    remarks: Optional[str] = ""


class UtilizationSchema(BaseModel):
    date: str
    aircraft_id: Optional[int] = None
    aircraft_tail: Optional[str] = None
    flight_from: Optional[str] = ""
    flight_to: Optional[str] = ""
    flight_hours: float # Время в полете (например 2.5 часа)
    flight_cycles: int  # Количество посадок (обычно 1)
    atlb_ref: Optional[str] = "" # Номер страницы бортжурнала
    maintenance: bool = False


    # Откуда (для REMOVED / SWAP)
    from_esn: Optional[str] = ""  # Original SN двигателя
    from_gss: Optional[str] = ""  # Наш ID
    
    # Куда (для INSTALLED / SWAP)
    to_esn: Optional[str] = ""
    to_gss: Optional[str] = ""
    
    location: Optional[str] = ""  # Текущая локация (город/шоп)
    reason: Optional[str] = ""
class ATLBSchema(BaseModel):
    date: str
    aircraft_id: int
    atlb_no: str

    # Flight Leg
    from_apt: str
    to_apt: str

    # Times (в формате HH:MM)
    out_time: str
    in_time: str
    block_time: str  # Рассчитанное значение

    off_time: str
    on_time: str
    flight_time: str  # Рассчитанное значение (идет в наработку)

    cycles: int

    maintenance_type: str
    maintenance_only: bool = False

    # Oil & Hyd (просто текст или числа)
    oil_1: Optional[float] = None
    oil_2: Optional[float] = None
    oil_3: Optional[float] = None
    oil_4: Optional[float] = None
    oil_apu: Optional[float] = None

    hyd_1: Optional[float] = None
    hyd_2: Optional[float] = None
    hyd_3: Optional[float] = None
    hyd_4: Optional[float] = None

class EngineParametersSchema(BaseModel):
    engine_id: int
    date: str  # Дата записи параметров (в формате ISO)
    n1_takeoff: Optional[float] = None
    n2_takeoff: Optional[float] = None
    egt_takeoff: Optional[float] = None
    n1_cruise: Optional[float] = None
    n2_cruise: Optional[float] = None
    egt_cruise: Optional[float] = None

class BoroscopeSchema(BaseModel):
    date: str
    aircraft: str
    serial_number: str
    position: str
    gss_id: Optional[str] = ""
    inspector: str
    link: Optional[str] = ""

class PurchaseOrderSchema(BaseModel):
    date: str
    name: str
    purpose: str
    aircraft: str
    ro_number: str
    link: Optional[str] = ""


class UtilizationParameterSchema(BaseModel):
    """Schema for Utilization Parameters"""
    date: str
    aircraft: str
    ttsn: float
    tcsn: int
    period: bool = False
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class UserCreateSchema(BaseModel):
    """Schema for creating new user"""
    username: str
    password: str
    first_name: str
    last_name: str
    position: Optional[str] = None
    role: str = "viewer"  # admin, user, viewer


class UserUpdateSchema(BaseModel):
    """Schema for updating user"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    position: Optional[str] = None
    role: Optional[str] = None
    photo_url: Optional[str] = None
    is_active: Optional[bool] = None


class LoginSchema(BaseModel):
    """Schema for login"""
    username: str
    password: str


class ChangePasswordSchema(BaseModel):
    """Schema for changing password"""
    old_password: str
    new_password: str


# === UTILITY FUNCTIONS FOR AUTH ===

def hash_password(password: str) -> str:
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password"""
    return hash_password(plain_password) == hashed_password


def create_notification(db: Session, action_type: str, entity_type: str, 
                       entity_id: int, message: str, performed_by: str,
                       user_id: Optional[int] = None):
    """Create notification for admins"""
    # Support dict messages by encoding to JSON for rich details
    if isinstance(message, (dict, list)):
        try:
            message = json.dumps(message, ensure_ascii=False)
        except Exception:
            message = str(message)
    notification = models.Notification(
        user_id=user_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        message=message,
        performed_by=performed_by,
        is_read=False
    )
    db.add(notification)
    db.commit()


# --- API (GET DATA) ---

@app.get("/api/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    return {
        "SV": db.query(models.Engine).filter(models.Engine.status == "SV").count(),
        "US": db.query(models.Engine).filter(models.Engine.status == "US").count(),
        "INSTALLED": db.query(models.Engine).filter(models.Engine.status == "INSTALLED").count(),
        "REMOVED": db.query(models.Engine).filter(models.Engine.status == "REMOVED").count()
    }

@app.get("/api/locations")
def get_locations_overview(db: Session = Depends(get_db)):
    locations = db.query(models.Location).all()
    result = []
    for loc in locations:
        engine_count = db.query(models.Engine).filter(models.Engine.location_id == loc.id).count()
        result.append({
            "id": loc.id,
            "name": loc.name,
            "city": loc.city,
            "engine_count": engine_count
        })
    return result

class LocationUpdateSchema(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None

@app.put("/api/locations/{location_id}")
def update_location(location_id: int, data: LocationUpdateSchema, db: Session = Depends(get_db)):
    """Update location name and/or city"""
    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    
    if data.name:
        location.name = data.name
    if data.city:
        location.city = data.city
    
    db.commit()
    db.refresh(location)
    
    return {
        "message": "Location updated successfully",
        "id": location.id,
        "name": location.name,
        "city": location.city
    }

@app.delete("/api/locations/{location_id}")
def delete_location(location_id: int, db: Session = Depends(get_db)):
    """Delete location"""
    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    
    # Check if location has engines
    engine_count = db.query(models.Engine).filter(models.Engine.location_id == location_id).count()
    if engine_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete location with {engine_count} engines")
    
    db.delete(location)
    db.commit()
    
    return {"message": "Location deleted successfully"}

@app.get("/api/fleet")
def get_fleet_status(db: Session = Depends(get_db)):
    aircrafts = db.query(models.Aircraft).all()
    result = []
    
    for ac in aircrafts:
        engines_on_wing = db.query(models.Engine).filter(models.Engine.aircraft_id == ac.id).all()
        eng_list = []
        for eng in engines_on_wing:
            eng_list.append({
                "position": eng.position,
                "current_sn": eng.current_sn,
                "original_sn": eng.original_sn,
                "tt": eng.total_time,
                "tc": eng.total_cycles,
                "n1_to": eng.n1_takeoff, 
                "n1_cr": eng.n1_cruise,
                "n2_to": eng.n2_takeoff, 
                "n2_cr": eng.n2_cruise
            })
            
        result.append({
            "id": ac.id,
            "tail_number": ac.tail_number,
            "model": ac.model,
            "msn": ac.msn,
            "total_time": round(ac.total_time, 2) if ac.total_time else 0.0,
            "total_cycles": ac.total_cycles or 0,
            "engines": eng_list
        })
    return result

class AircraftCreateSchema(BaseModel):
    tail_number: str
    model: Optional[str] = None
    msn: Optional[str] = None
    total_time: float = 0.0
    total_cycles: int = 0

class AircraftUpdateSchema(BaseModel):
    tail_number: Optional[str] = None
    model: Optional[str] = None
    msn: Optional[str] = None

@app.post("/api/aircrafts")
def create_aircraft(data: AircraftCreateSchema, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create new aircraft"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create aircraft")
    
    existing = db.query(models.Aircraft).filter(
        models.Aircraft.tail_number == data.tail_number
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Aircraft with this tail number already exists")
    
    new_aircraft = models.Aircraft(
        tail_number=data.tail_number,
        model=data.model,
        msn=data.msn,
        total_time=data.total_time,
        total_cycles=data.total_cycles
    )
    
    db.add(new_aircraft)
    db.commit()
    db.refresh(new_aircraft)
    
    return {
        "message": "Aircraft created successfully",
        "id": new_aircraft.id,
        "tail_number": new_aircraft.tail_number
    }

@app.put("/api/aircrafts/{aircraft_id}")
def update_aircraft(aircraft_id: int, data: AircraftUpdateSchema, db: Session = Depends(get_db)):
    """Update aircraft"""
    aircraft = db.query(models.Aircraft).filter(models.Aircraft.id == aircraft_id).first()
    
    if not aircraft:
        raise HTTPException(status_code=404, detail="Aircraft not found")
    
    if data.tail_number:
        aircraft.tail_number = data.tail_number
    if data.model:
        aircraft.model = data.model
    if data.msn:
        aircraft.msn = data.msn
    
    db.commit()
    db.refresh(aircraft)
    
    return {
        "message": "Aircraft updated successfully",
        "id": aircraft.id,
        "tail_number": aircraft.tail_number
    }

@app.delete("/api/aircrafts/{aircraft_id}")
def delete_aircraft(aircraft_id: int, db: Session = Depends(get_db)):
    """Delete aircraft"""
    aircraft = db.query(models.Aircraft).filter(models.Aircraft.id == aircraft_id).first()
    
    if not aircraft:
        raise HTTPException(status_code=404, detail="Aircraft not found")
    
    # Check if aircraft has engines installed
    engines = db.query(models.Engine).filter(models.Engine.aircraft_id == aircraft_id).count()
    if engines > 0:
        raise HTTPException(status_code=400, detail="Cannot delete aircraft with installed engines")
    
    db.delete(aircraft)
    db.commit()
    
    return {"message": f"Aircraft {aircraft.tail_number} deleted successfully"}

@app.get("/api/recent-actions")
def get_recent_actions(limit: int = 20, db: Session = Depends(get_db)):
    """Get recent actions/activity log"""
    notifications = db.query(models.Notification).order_by(
        models.Notification.created_at.desc()
    ).limit(limit).all()
    
    result = []
    for notif in notifications:
        result.append({
            "id": notif.id,
            "action_type": notif.action_type,
            "entity_type": notif.entity_type,
            "entity_id": notif.entity_id,
            "message": notif.message,
            "performed_by": notif.performed_by,
            "created_at": notif.created_at.isoformat() if notif.created_at else None,
            "is_read": notif.is_read
        })
    
    return result

@app.delete("/api/recent-actions")
def delete_recent_actions(range_key: str = Query("all", alias="range"), db: Session = Depends(get_db)):
    """Delete recent actions within preset ranges (older than given window)."""
    ranges = {
        "1d": 1,
        "3d": 3,
        "7d": 7,
        "30d": 30,
        "all": None
    }

    if range_key not in ranges:
        raise HTTPException(status_code=400, detail="Invalid range. Use 1d, 3d, 7d, 30d, or all.")

    query = db.query(models.Notification)
    cutoff = None

    if ranges[range_key] is not None:
        cutoff = datetime.utcnow() - timedelta(days=ranges[range_key])
        query = query.filter(models.Notification.created_at <= cutoff)

    deleted_count = query.delete()
    db.commit()

    return {
        "deleted": deleted_count,
        "range": range_key,
        "cutoff": cutoff.isoformat() if cutoff else None
    }
    
    # Log action
    create_notification(
        db, 
        action_type="updated",
        entity_type="location",
        entity_id=location.id,
        message=f"Локация переименована в '{location.name}'",
        performed_by="Admin"
    )
    
    location_name = location.name
    
    # Log action
    create_notification(
        db,
        action_type="deleted",
        entity_type="location",
        entity_id=location_id,
        message=f"Локация '{location_name}' удалена",
        performed_by="Admin"
    )
    
    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="aircraft",
        entity_id=new_aircraft.id,
        message=f"Воздушное судно {new_aircraft.tail_number} создано (модель: {new_aircraft.model or '-'}), MSN: {new_aircraft.msn or '-'}",
        performed_by="Admin"
    )
    
    # Log action
    create_notification(
        db,
        action_type="updated",
        entity_type="aircraft",
        entity_id=aircraft.id,
        message=f"Воздушное судно {aircraft.tail_number} обновлено (модель: {aircraft.model or '-'})",
        performed_by="Admin"
    )
    
    tail_number = aircraft.tail_number
    
    # Log action
    create_notification(
        db,
        action_type="deleted",
        entity_type="aircraft",
        entity_id=aircraft_id,
        message=f"Воздушное судно {tail_number} удалено",
        performed_by="Admin"
    )

@app.get("/api/dashboard/aircraft-details")
def get_aircraft_dashboard_details(db: Session = Depends(get_db)):
    """
    Возвращает детальную информацию для дашборда:
    - Общий налет самолета
    - 4 позиции двигателей (даже если пустые)
    - Для каждого двигателя: TSN/CSN с момента установки, N1/N2, дата обновления
    """
    aircrafts = db.query(models.Aircraft).all()
    
    # Если в базе нет самолетов - создаем пустые карточки для визуализации
    if not aircrafts:
        result = [
            {
                "aircraft_id": 1,
                "tail_number": "ER-BAT",
                "model": "Boeing 747-200",
                "total_time": 0.0,
                "total_cycles": 0,
                "positions": [None, None, None, None]
            },
            {
                "aircraft_id": 2,
                "tail_number": "ER-BAR",
                "model": "Boeing 747-200",
                "total_time": 0.0,
                "total_cycles": 0,
                "positions": [None, None, None, None]
            },
            {
                "aircraft_id": 3,
                "tail_number": "ER-BAQ",
                "model": "Boeing 747-200",
                "total_time": 0.0,
                "total_cycles": 0,
                "positions": [None, None, None, None]
            }
        ]
        return result
    
    result = []
    
    for ac in aircrafts:
        # Последняя запись БЕЗ периода для заголовка (текущий налет)
        latest_non_period = db.query(models.UtilizationParameter).filter(
            models.UtilizationParameter.aircraft == ac.tail_number,
            models.UtilizationParameter.period == False
        ).order_by(
            models.UtilizationParameter.created_at.desc(),
            models.UtilizationParameter.date.desc(),
            models.UtilizationParameter.id.desc()
        ).first()

        # Последняя ПЕРИОДНАЯ запись для сводки внутри раскрытия
        latest_period = db.query(models.UtilizationParameter).filter(
            models.UtilizationParameter.aircraft == ac.tail_number,
            models.UtilizationParameter.period == True
        ).order_by(
            models.UtilizationParameter.created_at.desc(),
            models.UtilizationParameter.date.desc(),
            models.UtilizationParameter.id.desc()
        ).first()

        # Итог для заголовка: берем без периода, если есть, иначе поля самолета
        util_ttsn = ac.total_time or 0.0
        util_tcsn = ac.total_cycles or 0
        util_date = None
        if latest_non_period:
            util_ttsn = latest_non_period.ttsn if latest_non_period.ttsn is not None else util_ttsn
            util_tcsn = latest_non_period.tcsn if latest_non_period.tcsn is not None else util_tcsn
            util_date = latest_non_period.date.strftime("%Y-%m-%d") if latest_non_period.date else None

        # Сводка периода: берем последнюю периодную запись
        util_period = bool(latest_period)
        util_date_from = latest_period.date_from.strftime("%Y-%m-%d") if latest_period and latest_period.date_from else None
        util_date_to = latest_period.date_to.strftime("%Y-%m-%d") if latest_period and latest_period.date_to else None
        period_ttsn = latest_period.ttsn if latest_period else None
        period_tcsn = latest_period.tcsn if latest_period else None

        # Последняя дата ввода данных (любая запись - периодная или нет)
        last_entry = db.query(models.UtilizationParameter).filter(
            models.UtilizationParameter.aircraft == ac.tail_number
        ).order_by(
            models.UtilizationParameter.created_at.desc()
        ).first()
        last_data_date = last_entry.created_at.strftime("%d-%m-%Y") if last_entry and last_entry.created_at else None

        # Все двигатели на самолете
        engines_on_wing = db.query(models.Engine).filter(
            models.Engine.aircraft_id == ac.id,
            models.Engine.status == "INSTALLED"
        ).all()
        
        # Создаем 4 позиции (1, 2, 3, 4)
        positions = {}
        for pos in [1, 2, 3, 4]:
            positions[pos] = None
            
        # Заполняем реальными двигателями
        for eng in engines_on_wing:
            if eng.position and 1 <= eng.position <= 4:
                # Вычисляем налет на конкретном самолете
                tsn_on_aircraft = 0.0
                csn_on_aircraft = 0
                
                if eng.tsn_at_install is not None and eng.csn_at_install is not None:
                    # Налет = Текущий TSN - TSN при установке
                    tsn_on_aircraft = eng.total_time - eng.tsn_at_install
                    csn_on_aircraft = eng.total_cycles - eng.csn_at_install
                
                # Находим последнюю запись ATLB для определения даты обновления
                last_atlb = db.query(models.ActionLog).filter(
                    models.ActionLog.action_type == "FLIGHT"
                ).order_by(models.ActionLog.date.desc()).first()
                
                last_update = last_atlb.date.strftime("%Y-%m-%d %H:%M") if last_atlb else "N/A"
                
                positions[eng.position] = {
                    "engine_id": eng.id,
                    "original_sn": eng.original_sn,
                    "gss_sn": eng.gss_sn or eng.original_sn,
                    "current_sn": eng.current_sn,
                    "model": eng.model,
                    "total_tsn": round(eng.total_time, 1),
                    "total_csn": eng.total_cycles,
                    "tsn_on_aircraft": round(tsn_on_aircraft, 1),
                    "csn_on_aircraft": csn_on_aircraft,
                    "n1_takeoff": eng.n1_takeoff,
                    "n1_cruise": eng.n1_cruise,
                    "n2_takeoff": eng.n2_takeoff,
                    "n2_cruise": eng.n2_cruise,
                    "egt_takeoff": eng.egt_takeoff,
                    "egt_cruise": eng.egt_cruise,
                    "install_date": eng.install_date.strftime("%Y-%m-%d") if eng.install_date else "N/A",
                    "last_update": last_update,
                    "param_date": eng.last_param_update.strftime("%d.%m.%Y") if eng.last_param_update else None
                }
        
        result.append({
            "aircraft_id": ac.id,
            "tail_number": ac.tail_number,
            "model": ac.model,
            "total_time": round(util_ttsn, 1) if util_ttsn else 0.0,
            "total_cycles": util_tcsn if util_tcsn else 0,
            "utilization_date": util_date,
            "utilization_period": util_period,
            "utilization_date_from": util_date_from,
            "utilization_date_to": util_date_to,
            "period_ttsn": period_ttsn,
            "period_tcsn": period_tcsn,
            "last_data_date": last_data_date,
            "positions": [
                positions[1],
                positions[2],
                positions[3],
                positions[4]
            ]
        })
    
    return result

# --- ВОТ ИСПРАВЛЕННАЯ ФУНКЦИЯ (ПОКАЗЫВАЕТ ВСЕ ДВИГАТЕЛИ) ---
@app.get("/api/engines")
def get_all_engines(status: str = None, db: Session = Depends(get_db)):
    # 1. Запрашиваем ВСЕ двигатели из базы
    query = db.query(models.Engine)
    if status:
        query = query.filter(models.Engine.status == status)
    
    engines = query.all()
    result = []
    
    for eng in engines:
        # 2. Безопасное определение локации (чтобы не было ошибок, если локация удалена)
        loc_name = "Не указано" 
        
        try:
            if eng.location:
                loc_name = eng.location.name
            elif eng.aircraft:
                tail = eng.aircraft.tail_number if eng.aircraft.tail_number else "No Tail"
                loc_name = f"{tail} (Pos {eng.position})"
        except Exception:
            loc_name = "Ошибка данных" # Если ссылка на удаленный объект

        # 3. Собираем данные, заменяя пустые (None) на текст или нули
        result.append({
            "id": eng.id,
            "original_sn": eng.original_sn or "Нет данных",
            "gss_sn": eng.gss_sn or eng.original_sn,
            "current_sn": eng.current_sn or "Нет данных",
            "model": eng.model or "-",
            "status": eng.status,
            "location": loc_name,
            "tt": eng.total_time if eng.total_time is not None else 0,
            "tc": eng.total_cycles if eng.total_cycles is not None else 0,
            "aircraft_id": eng.aircraft_id,
            "aircraft": eng.aircraft.tail_number if eng.aircraft else None,
            "position": eng.position,
            "photo_url": eng.photo_url,
            "remarks": eng.remarks or "",
            "removed_from": eng.removed_from or "",
            "install_date": eng.install_date.strftime('%Y-%m-%d') if eng.install_date else None
        })
    return result

# --- API (ACTIONS & HISTORY) ---

# СОЗДАНИЕ НОВОГО ДВИГАТЕЛЯ
class EngineCreateSchema(BaseModel):
    original_sn: str
    gss_sn: Optional[str] = None
    current_sn: str
    model: Optional[str] = None
    status: str = "SV"
    location_id: Optional[int] = None
    total_time: float = 0.0
    total_cycles: int = 0
    photo_url: Optional[str] = None
    remarks: Optional[str] = None
    removed_from: Optional[str] = None

@app.post("/api/engines")
def create_engine(data: EngineCreateSchema, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create engines")
    
    # Проверяем, существует ли уже двигатель с таким original_sn
    existing = db.query(models.Engine).filter(models.Engine.original_sn == data.original_sn).first()
    if existing:
        raise HTTPException(400, f"Engine with ESN {data.original_sn} already exists")
    
    # location_id обязателен для создания
    if not data.location_id:
        raise HTTPException(400, "location_id is required for creating new engine")
    
    # Создаем новый двигатель
    new_engine = models.Engine(
        original_sn=data.original_sn,
        gss_sn=data.gss_sn or data.original_sn,
        current_sn=data.current_sn,
        model=data.model,
        status=data.status,
        location_id=data.location_id,
        total_time=data.total_time,
        total_cycles=data.total_cycles,
        photo_url=data.photo_url,
        remarks=data.remarks,
        removed_from=data.removed_from
    )
    
    db.add(new_engine)
    db.commit()
    db.refresh(new_engine)
    
    # Создаем лог о добавлении
    location = db.query(models.Location).filter(models.Location.id == data.location_id).first()
    loc_name = location.name if location else "Unknown"
    
    new_log = models.ActionLog(
        engine_id=new_engine.id,
        action_type="INSPECT",  # Используем как "Engine Added"
        from_location="NEW",
        to_location=loc_name,
        snapshot_tt=data.total_time,
        snapshot_tc=data.total_cycles,
        comments=f"Engine created: {data.remarks or 'No remarks'}"
    )
    db.add(new_log)
    db.commit()
    
    # Создаем notification для Recent Actions
    create_notification(db, 
                       action_type="created",
                       entity_type="engine",
                       entity_id=new_engine.id,
                       message=f"Был добавлен новый двигатель {new_engine.current_sn} (ESN: {new_engine.original_sn}) в локацию {loc_name} пользователем System",
                       performed_by="System")
    
    return {"message": "Engine created successfully", "id": new_engine.id}

# УДАЛЕНИЕ ДВИГАТЕЛЯ
@app.delete("/api/engines/{engine_id}")
def delete_engine(engine_id: int, db: Session = Depends(get_db)):
    # Находим двигатель
    engine = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
    if not engine:
        raise HTTPException(404, "Engine not found")
    
    # Проверяем, не установлен ли двигатель на самолет
    if engine.status == "INSTALLED":
        raise HTTPException(400, "Cannot delete engine that is installed on aircraft. Remove it first.")
    
    # Сохраняем информацию для лога
    engine_sn = engine.original_sn
    
    # Удаляем все связанные логи (опционально, можно оставить для истории)
    # db.query(models.ActionLog).filter(models.ActionLog.engine_id == engine_id).delete()
    
    # Удаляем двигатель
    db.delete(engine)
    db.commit()
    
    return {"message": f"Engine {engine_sn} deleted successfully"}

# ОБНОВЛЕНИЕ ДВИГАТЕЛЯ
@app.put("/api/engines/{engine_id}")
def update_engine(engine_id: int, data: EngineCreateSchema, db: Session = Depends(get_db)):
    # Находим двигатель
    engine = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
    if not engine:
        raise HTTPException(404, "Engine not found")
    
    # Обновляем поля
    engine.original_sn = data.original_sn
    engine.model = data.model
    engine.gss_sn = data.gss_sn or data.original_sn
    engine.current_sn = data.current_sn
    engine.status = data.status
    engine.total_time = data.total_time
    engine.total_cycles = data.total_cycles
    engine.photo_url = data.photo_url
    engine.remarks = data.remarks
    engine.removed_from = data.removed_from
    
    if data.location_id:
        engine.location_id = data.location_id
    
    db.commit()
    db.refresh(engine)
    db.refresh(engine)
    
    return {"message": "Engine updated successfully", "id": engine.id}

# ОБНОВЛЕНИЕ ЗАПИСИ В ИСТОРИИ (ActionLog)
class ActionLogUpdateSchema(BaseModel):
    date: Optional[str] = None
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    to_aircraft: Optional[str] = None
    position: Optional[int] = None
    snapshot_tt: Optional[float] = None
    snapshot_tc: Optional[int] = None
    comments: Optional[str] = None
    file_url: Optional[str] = None

class ActionLogCreateSchema(BaseModel):
    date: Optional[str] = None
    engine_original_sn: Optional[str] = None
    engine_current_sn: Optional[str] = None
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    to_aircraft: Optional[str] = None
    position: Optional[int] = None
    snapshot_tt: Optional[float] = None
    snapshot_tc: Optional[int] = None
    comments: Optional[str] = None
    file_url: Optional[str] = None

@app.put("/api/history/{action_type}/{log_id}")
def update_history_record(action_type: str, log_id: int, data: ActionLogUpdateSchema, db: Session = Depends(get_db)):
    # Специальная обработка для BORESCOPE
    if action_type == "BORESCOPE":
        inspection = db.query(models.BoroscopeInspection).filter(models.BoroscopeInspection.id == log_id).first()
        if not inspection:
            raise HTTPException(404, f"Borescope inspection not found (ID: {log_id})")
        
        if data.date:
            parsed = parse_input_date(data.date)
            if parsed:
                inspection.date = parsed.strftime("%Y-%m-%d")
        if data.to_aircraft:
            inspection.aircraft_tail = data.to_aircraft
        if data.from_location:  # serial_number
            inspection.serial_number = data.from_location
        if data.position:
            inspection.position = data.position
        if data.to_location:  # gss_id
            inspection.gss_id = data.to_location
        if data.comments:  # inspector
            inspection.inspector = data.comments
        if data.file_url:
            inspection.link = data.file_url
            
        db.commit()
        db.refresh(inspection)
        return {"message": "Borescope inspection updated successfully"}
    
    # Специальная обработка для PURCHASE_ORDER
    if action_type == "PURCHASE_ORDER":
        order = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == log_id).first()
        if not order:
            raise HTTPException(404, f"Purchase order not found (ID: {log_id})")
        
        if data.date:
            parsed = parse_input_date(data.date)
            if parsed:
                order.date = parsed.strftime("%Y-%m-%d")
        if data.from_location:  # name
            order.name = data.from_location
        if data.to_location:  # purpose
            order.purpose = data.to_location
        if data.to_aircraft:
            order.aircraft_tail = data.to_aircraft
        if data.comments:  # ro_number
            order.ro_number = data.comments
        if data.file_url:
            order.link = data.file_url
            
        db.commit()
        db.refresh(order)
        return {"message": "Purchase order updated successfully"}
    
    # Специальная обработка для PARAMETER
    if action_type == "PARAMETER":
        param = db.query(models.EngineParameterHistory).filter(models.EngineParameterHistory.id == log_id).first()
        if not param:
            raise HTTPException(404, f"Engine parameter record not found (ID: {log_id})")
        
        if data.date:
            parsed = parse_input_date(data.date)
            if parsed:
                param.date = parsed
        if data.from_location:  # n1_takeoff
            param.n1_takeoff = float(data.from_location) if data.from_location else None
        if data.to_location:  # n2_takeoff
            param.n2_takeoff = float(data.to_location) if data.to_location else None
        if data.snapshot_tt:  # egt_takeoff
            param.egt_takeoff = data.snapshot_tt
        if data.snapshot_tc:  # n1_cruise
            param.n1_cruise = float(data.snapshot_tc) if data.snapshot_tc else None
        if data.comments:  # n2_cruise (первая часть)
            param.n2_cruise = float(data.comments.split(',')[0]) if data.comments else None
        if data.file_url:  # egt_cruise (вторая часть)
            param.egt_cruise = float(data.file_url) if data.file_url else None
            
        db.commit()
        db.refresh(param)
        return {"message": "Engine parameter record updated successfully"}
    
    if action_type == "INSTALL":
        log = db.query(models.ActionLog).filter(
            models.ActionLog.id == log_id,
            models.ActionLog.action_type == action_type
        ).first()
        if not log:
            raise HTTPException(404, f"Install record not found (ID: {log_id})")
        if not log.engine:
            raise HTTPException(400, "Install record is not linked to an engine")
        engine = log.engine

        if data.date:
            parsed = parse_input_date(data.date)
            if parsed:
                log.date = parsed
                engine.install_date = parsed

        if data.from_location is not None:
            log.from_location = data.from_location

        if data.to_aircraft is not None:
            if data.to_aircraft.strip() == "":
                log.to_aircraft = None
                engine.aircraft_id = None
            else:
                aircraft = db.query(models.Aircraft).filter(models.Aircraft.tail_number == data.to_aircraft).first()
                if not aircraft:
                    raise HTTPException(400, f"Aircraft {data.to_aircraft} not found")
                log.to_aircraft = aircraft.tail_number
                engine.aircraft_id = aircraft.id
                engine.status = models.EngineStatus.INSTALLED
                engine.location_id = None

        if data.position is not None:
            log.position = data.position
            engine.position = data.position

        if data.snapshot_tt is not None:
            log.snapshot_tt = data.snapshot_tt
            engine.total_time = data.snapshot_tt
            engine.tsn_at_install = data.snapshot_tt

        if data.snapshot_tc is not None:
            log.snapshot_tc = data.snapshot_tc
            engine.total_cycles = data.snapshot_tc
            engine.csn_at_install = data.snapshot_tc

        if data.comments is not None:
            log.comments = data.comments

        if data.file_url is not None:
            log.file_url = data.file_url

        db.commit()
        db.refresh(log)
        db.refresh(engine)
        return {"message": f"Install record updated successfully (ID: {log_id})"}

    # Обычная обработка для ActionLog
    log = db.query(models.ActionLog).filter(
        models.ActionLog.id == log_id,
        models.ActionLog.action_type == action_type
    ).first()
    
    if not log:
        raise HTTPException(404, f"History record not found (ID: {log_id}, Type: {action_type})")
    
    # Обновляем только переданные поля
    if data.date:
        parsed = parse_input_date(data.date)
        if parsed:
            log.date = parsed
    if data.from_location is not None:
        log.from_location = data.from_location
    if data.to_location is not None:
        log.to_location = data.to_location
    if data.to_aircraft is not None:
        log.to_aircraft = data.to_aircraft
    if data.position is not None:
        log.position = data.position
    if data.snapshot_tt is not None:
        log.snapshot_tt = data.snapshot_tt
    if data.snapshot_tc is not None:
        log.snapshot_tc = data.snapshot_tc
    if data.comments is not None:
        log.comments = data.comments
    if data.file_url is not None:
        log.file_url = data.file_url
    
    db.commit()
    db.refresh(log)
    
    return {"message": f"History record updated successfully (ID: {log_id})"}

# УДАЛЕНИЕ ЗАПИСИ ИЗ ИСТОРИИ (ActionLog)
@app.delete("/api/history/{action_type}/{log_id}")
def delete_history_record(action_type: str, log_id: int, db: Session = Depends(get_db)):
    # Специальная обработка для Reports
    if action_type == "BORESCOPE":
        inspection = db.query(models.BoroscopeInspection).filter(models.BoroscopeInspection.id == log_id).first()
        if not inspection:
            raise HTTPException(404, f"Borescope inspection not found (ID: {log_id})")
        db.delete(inspection)
        db.commit()
        return {"message": f"Borescope inspection deleted successfully (ID: {log_id})"}
    
    if action_type == "PURCHASE_ORDER":
        order = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == log_id).first()
        if not order:
            raise HTTPException(404, f"Purchase order not found (ID: {log_id})")
        db.delete(order)
        db.commit()
        return {"message": f"Purchase order deleted successfully (ID: {log_id})"}
    
    if action_type == "PARAMETER":
        param = db.query(models.EngineParameterHistory).filter(models.EngineParameterHistory.id == log_id).first()
        if not param:
            raise HTTPException(404, f"Engine parameter record not found (ID: {log_id})")
        db.delete(param)
        db.commit()
        return {"message": f"Engine parameter record deleted successfully (ID: {log_id})"}
    
    # Обычная обработка для ActionLog
    log = db.query(models.ActionLog).filter(
        models.ActionLog.id == log_id,
        models.ActionLog.action_type == action_type
    ).first()
    
    if not log:
        raise HTTPException(404, f"History record not found (ID: {log_id}, Type: {action_type})")
    
    # Если это INSTALL, отменяем установку: возвращаем двигатель в статус SV
    if action_type == "INSTALL" and log.engine:
        engine = log.engine
        engine.status = models.EngineStatus.SV  # Возвращаем статус "Serviceable"
        engine.aircraft_id = None
        engine.position = None
        engine.tsn_at_install = None
        engine.csn_at_install = None
        engine.install_date = None
        # Примечание: location_id оставляем как есть (последняя известная локация)
    
    # Если это REMOVE, отменяем снятие: возвращаем двигатель обратно на самолет
    if action_type == "REMOVE" and log.engine:
        engine = log.engine
        # Находим последнюю INSTALL запись для этого двигателя (до текущей REMOVE)
        last_install = db.query(models.ActionLog).filter(
            models.ActionLog.engine_id == engine.id,
            models.ActionLog.action_type == "INSTALL",
            models.ActionLog.date < log.date
        ).order_by(models.ActionLog.date.desc()).first()
        
        if last_install:
            # Восстанавливаем данные из последней установки
            aircraft = db.query(models.Aircraft).filter(models.Aircraft.tail_number == last_install.to_aircraft).first()
            if aircraft:
                engine.status = models.EngineStatus.INSTALLED
                engine.aircraft_id = aircraft.id
                engine.position = last_install.position
                engine.location_id = None
                engine.total_time = last_install.snapshot_tt if last_install.snapshot_tt else engine.total_time
                engine.total_cycles = last_install.snapshot_tc if last_install.snapshot_tc else engine.total_cycles
        else:
            # Если нет предыдущей установки, просто меняем статус на SV
            engine.status = models.EngineStatus.SV
            engine.aircraft_id = None
            engine.position = None
    
    # Если это REPAIR, отменяем ремонт: восстанавливаем предыдущие TT/TC
    if action_type == "REPAIR" and log.engine:
        engine = log.engine
        # Находим предыдущую запись с TT/TC для этого двигателя
        prev_log = db.query(models.ActionLog).filter(
            models.ActionLog.engine_id == engine.id,
            models.ActionLog.date < log.date,
            models.ActionLog.snapshot_tt.isnot(None)
        ).order_by(models.ActionLog.date.desc()).first()
        
        if prev_log:
            engine.total_time = prev_log.snapshot_tt
            engine.total_cycles = prev_log.snapshot_tc if prev_log.snapshot_tc else engine.total_cycles
        # Примечание: Статус остается как есть (не меняем на SV автоматически)
    
    # Если это SHIP (отгрузка), отменяем отгрузку: возвращаем двигатель в исходную локацию
    if action_type == "SHIP" and log.engine:
        engine = log.engine
        # Пытаемся найти локацию из from_location
        if log.from_location:
            from_location = db.query(models.Location).filter(models.Location.name == log.from_location).first()
            if from_location:
                engine.location_id = from_location.id
        # Примечание: Статус не меняем (остается как был)
    
    # Удаляем запись
    db.delete(log)
    db.commit()
    
    return {"message": f"History record deleted successfully (ID: {log_id})"}

# ВАЖНО: Сначала специфичные маршруты (INSTALL), потом общие ({action_type})

# 1. Получить историю установок (Вся информация)
@app.get("/api/history/INSTALL")
def get_install_history(db: Session = Depends(get_db)):
    # Берем логи только типа INSTALL
    logs = db.query(models.ActionLog).filter(models.ActionLog.action_type == "INSTALL").order_by(models.ActionLog.date.desc()).all()
    res = []
    for l in logs:
        # Если двигатель удален, пишем заглушку
        orig_sn = l.engine.original_sn if l.engine else "Deleted"
        curr_sn = l.engine.current_sn if l.engine else "-"
        
        res.append({
            "id": l.id,
            "date": l.date.strftime("%Y-%m-%d"),
            "original_sn": orig_sn,
            "current_sn": curr_sn,
            "install_to": l.to_aircraft, 
            "position": l.position,
            "location_from": l.from_location,
            "tt": l.snapshot_tt,
            "tc": l.snapshot_tc,
            "remarks": l.comments
        })
    return res

# 3. Сохранить Установку (INSTALL)
@app.post("/api/actions/install")
def install_engine(data: InstallSchema, db: Session = Depends(get_db)):
    # Ищем двигатель
    eng = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
    if not eng: raise HTTPException(404, "Engine not found")
    
    # Ищем самолет
    ac = db.query(models.Aircraft).filter(models.Aircraft.id == data.aircraft_id).first()
    if not ac: raise HTTPException(404, "Aircraft not found")
    
    # Запоминаем откуда взяли
    from_loc = eng.location.name if eng.location else "Unknown"
    install_dt = parse_input_date(data.date)
    
    # Обновляем сам двигатель
    eng.status = "INSTALLED"
    eng.location_id = None
    eng.aircraft_id = ac.id
    eng.position = data.position
    eng.total_time = data.tt
    eng.total_cycles = data.tc
    
    # SNAPSHOT для отслеживания наработки на конкретном самолете
    eng.tsn_at_install = data.tt
    eng.csn_at_install = data.tc
    eng.install_date = install_dt or datetime.utcnow()
    
    # Пишем историю
    new_log = models.ActionLog(
        action_type="INSTALL",
        engine_id=eng.id,
        from_location=from_loc,
        to_aircraft=ac.tail_number,
        position=data.position,
        snapshot_tt=data.tt,
        snapshot_tc=data.tc,
        comments=data.remarks
    )
    if install_dt:
        new_log.date = install_dt
    db.add(new_log)
    db.commit()

    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="install",
        entity_id=new_log.id,
        message=f"Были внесены данные пользователем User в группу Installation: двигатель {eng.current_sn} установлен на {ac.tail_number} позиция {data.position}",
        performed_by="User"
    )
    return {"message": "Success"}

# 4. История перемещений (SHIP)
@app.get("/api/history/SHIP")
def get_shipment_history(db: Session = Depends(get_db)):
    logs = db.query(models.ActionLog).filter(models.ActionLog.action_type == "SHIP").order_by(models.ActionLog.date.desc()).all()
    res = []
    for l in logs:
        orig_sn = l.engine.original_sn if l.engine else "Deleted"
        curr_sn = l.engine.current_sn if l.engine else "-"
        
        res.append({
            "id": l.id,
            "date": l.date.strftime("%Y-%m-%d"),
            "original_sn": orig_sn,
            "current_sn": curr_sn,
            "from": l.from_location or "-",
            "to": l.to_location or "-",
            "remarks": l.comments
        })
    return res

# 5. Сохранить Перемещение (SHIPMENT)
@app.post("/api/actions/ship")
def ship_engine(data: ShipmentSchema, db: Session = Depends(get_db)):
    # Ищем двигатель
    eng = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
    if not eng: raise HTTPException(404, "Engine not found")
    
    # Ищем локацию назначения
    dest_loc = db.query(models.Location).filter(models.Location.id == data.to_location_id).first()
    if not dest_loc: raise HTTPException(404, "Destination Location not found")

    # Откуда забираем (для истории)
    from_loc_txt = "Unknown"
    if eng.location:
        from_loc_txt = eng.location.name
    elif eng.aircraft:
        from_loc_txt = f"AC: {eng.aircraft.tail_number}"

    # Логика перемещения:
    # 1. Убираем с самолета (если был там)
    eng.aircraft_id = None
    eng.position = None
    # 2. Ставим новую локацию
    eng.location_id = dest_loc.id
    # Статус обычно не меняется при shipment, но если он был INSTALLED, нужно сменить на SV или US.
    # Для простоты предположим, что он становится SV, если не указано иное.
    if eng.status == "INSTALLED":
        eng.status = "SV"

    # Пишем лог
    new_log = models.ActionLog(
        action_type="SHIP",
        engine_id=eng.id,
        from_location=from_loc_txt,
        to_location=dest_loc.name,
        comments=f"WB: {data.waybill} | {data.remarks}"
    )
    
    db.add(new_log)
    db.commit()

    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="shipment",
        entity_id=new_log.id,
        message=f"Были внесены данные пользователем User в группу Shipment: двигатель {eng.current_sn} отправлен из {from_loc_txt} в {dest_loc.name}",
        performed_by="User"
    )
    return {"message": "Shipment Saved"}

# 6. История снятий (REMOVE)
@app.get("/api/history/REMOVE")
def get_remove_history(db: Session = Depends(get_db)):
    logs = db.query(models.ActionLog).filter(models.ActionLog.action_type == "REMOVE").order_by(models.ActionLog.date.desc()).all()
    res = []
    for l in logs:
        orig_sn = l.engine.original_sn if l.engine else "Deleted"
        curr_sn = l.engine.current_sn if l.engine else "-"
        res.append({
            "id": l.id,
            "date": l.date.strftime("%Y-%m-%d"),
            "original_sn": orig_sn,
            "current_sn": curr_sn,
            "from": l.from_location or "-",
            "to": l.to_location or "-",
            "remarks": l.comments
        })
    return res

# 7. Сохранить Снятие (REMOVE)
@app.post("/api/actions/remove")
def remove_engine(data: RemoveSchema, db: Session = Depends(get_db)):
    eng = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
    if not eng: 
        raise HTTPException(404, "Engine not found in database. Please add the engine to Master Engine List first.")
    
    # Проверяем что двигатель установлен на самолете
    if eng.status != models.EngineStatus.INSTALLED:
        raise HTTPException(400, f"Engine {eng.original_sn} cannot be removed! Current status: {eng.status}. Only INSTALLED engines can be removed.")
    
    if not eng.aircraft_id:
        raise HTTPException(400, f"Engine {eng.original_sn} is not installed on any aircraft!")
    
    dest_loc = db.query(models.Location).filter(models.Location.id == data.to_location_id).first()
    if not dest_loc: raise HTTPException(404, "Destination Location not found")

    # Запоминаем, откуда сняли (с самолета)
    from_txt = "Unknown"
    if eng.aircraft:
        from_txt = f"AC: {eng.aircraft.tail_number} (Pos {eng.position})"

    # Логика: Отвязываем от самолета, привязываем к локации
    eng.aircraft_id = None
    eng.position = None
    eng.location_id = dest_loc.id
    eng.status = "REMOVED" # Меняем статус

    # Пишем лог
    new_log = models.ActionLog(
        action_type="REMOVE",
        engine_id=eng.id,
        from_location=from_txt,
        to_location=dest_loc.name,
        comments=data.reason
    )
    db.add(new_log)
    db.commit()

    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="remove",
        entity_id=new_log.id,
        message=f"Были внесены данные пользователем User в группу Remove: двигатель {eng.current_sn} снят с {from_txt} и перемещен в {dest_loc.name}",
        performed_by="User"
    )
    return {"message": "Engine Removed Successfully"}
    
    # 9. История ремонтов (REPAIR)
@app.get("/api/history/REPAIR")
def get_repair_history(db: Session = Depends(get_db)):
    logs = db.query(models.ActionLog).filter(models.ActionLog.action_type == "REPAIR").order_by(models.ActionLog.date.desc()).all()
    res = []
    for l in logs:
        orig_sn = l.engine.original_sn if l.engine else "Deleted"
        curr_sn = l.engine.current_sn if l.engine else "-"
        res.append({
            "id": l.id,
            "date": l.date.strftime("%Y-%m-%d"),
            "original_sn": orig_sn,
            "current_sn": curr_sn,
            "vendor": l.from_location,   # Используем поле from для Вендора
            "wo": l.to_location,         # Используем поле to для Work Order
            "tt": l.snapshot_tt,
            "tc": l.snapshot_tc,
            "photo": l.file_url,
            "remarks": l.comments
        })
    return res

# 10. Сохранить Ремонт (REPAIR)
@app.post("/api/actions/repair")
def repair_engine(data: RepairSchema, db: Session = Depends(get_db)):
    eng = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
    if not eng: raise HTTPException(404, "Engine not found")
    
    # Логика ремонта:
    # 1. Обновляем наработку (обычно после ремонта она меняется или подтверждается)
    eng.total_time = data.tt
    eng.total_cycles = data.tc
    # 2. Статус всегда становится SV (Исправен)
    eng.status = "SV"
    # 3. Двигатель теперь числится на складе "Вендора" (условно) или возвращается на склад
    # Для простоты оставляем локацию как есть, но логируем вендора

    new_log = models.ActionLog(
        action_type="REPAIR",
        engine_id=eng.id,
        from_location=data.vendor,   # Кто делал
        to_location=data.work_order, # Основание (документ)
        snapshot_tt=data.tt,
        snapshot_tc=data.tc,
        file_url=data.photo_url,
        comments=data.remarks
    )
    db.add(new_log)
    db.commit()

    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="repair",
        entity_id=new_log.id,
        message=f"Были внесены данные пользователем User в группу Repair: ремонт двигателя {eng.current_sn} у вендора {data.vendor}",
        performed_by="User"
    )
    return {"message": "Repair Recorded"} 
# 13. История запчастей (PARTS LOGISTICS / STORE BALANCE)
@app.get("/api/parts/history")
def get_parts_history(db: Session = Depends(get_db)):
    # Получаем логи, связанные с запчастями (где part_id не null или в комментах пометка PART)
    # Для простоты пока будем фильтровать по типам действий запчастей
    # Но так как мы пишем всё в ActionLog, будем искать по ключевым словам в типе или создадим новый тип
    # В данной реализации мы просто вернем все записи, у которых есть данные о запчастях
    # (Подразумевается, что мы расширим ActionLog или будем писать в comments JSON, но для старта сделаем просто)
    
    # ВАЖНО: В реальном проекте лучше отдельная таблица PartLog. 
    # Сейчас мы будем использовать ActionLog с action_type="PART_ACTION"
    
    logs = db.query(models.ActionLog).filter(models.ActionLog.action_type == "PART_ACTION").order_by(models.ActionLog.date.desc()).all()
    res = []
    for l in logs:
        # Парсим данные из полей ActionLog (упрощенная схема)
        import json
        try:
            details = json.loads(l.comments) if l.comments else {}
        except:
            details = {}
        date_value = ""
        if isinstance(l.date, datetime):
            date_value = l.date.strftime("%Y-%m-%d")
        elif isinstance(l.date, str) and l.date:
            date_value = l.date

        res.append({
            "id": l.id,
            "date": date_value,
            "action": l.from_location or "UNKNOWN",
            "part_name": details.get("part_name", "-"),
            "part_number": details.get("part_number", "-"),
            "serial_number": details.get("serial_number", "-"),
            "quantity": details.get("quantity", 0),
            "from_esn": details.get("from_esn", "-"),
            "to_esn": details.get("to_esn", "-"),
            "location": details.get("location", "-"),
            "reason": details.get("reason", "-")
        })
    return res

# 14. Сохранить действие с запчастью (PART ACTION)
@app.post("/api/actions/part")
def part_action(data: PartActionSchema, db: Session = Depends(get_db)):
    # 1. Находим или создаем запчасть в базе (Таблица parts)
    part = db.query(models.Part).filter(models.Part.part_number == data.part_number, models.Part.serial_number == data.serial_number).first()
    if not part:
        part = models.Part(
            name=data.part_name,
            part_number=data.part_number,
            serial_number=data.serial_number,
            quantity=data.quantity
        )
        db.add(part)
        db.commit()
        db.refresh(part)

    # 2. Формируем JSON для хранения в comments
    import json
    details_json = json.dumps({
        "part_name": data.part_name,
        "part_number": data.part_number,
        "serial_number": data.serial_number,
        "quantity": data.quantity,
        "from_esn": data.from_esn or "-",
        "to_esn": data.to_esn or "-",
        "location": data.location or "-",
        "reason": data.reason or "-"
    })

    # 3. Пишем в историю
    log_date = parse_input_date(data.date)
    new_log = models.ActionLog(
        date=log_date,
        action_type="PART_ACTION", # Специальный тип для запчастей
        part_id=part.id,
        from_location=data.action, # Пишем действие сюда (INSTALLED/REMOVED/SWAP)
        to_location=f"{data.part_name}", # Пишем имя запчасти сюда
        comments=details_json # Все детали в JSON
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    return {"message": "Part Action Recorded", "id": new_log.id}

# 14A. Store Balance Inventory CRUD
@app.get("/api/store-balance")
def get_store_balance(db: Session = Depends(get_db)):
    items = db.query(models.StoreItem).order_by(
        models.StoreItem.received_date.desc(),
        models.StoreItem.part_name.asc()
    ).all()

    result = []
    for item in items:
        result.append({
            "id": item.id,
            "received_date": item.received_date.strftime("%Y-%m-%d") if item.received_date else "",
            "part_name": item.part_name,
            "part_number": item.part_number,
            "serial_number": item.serial_number or "",
            "condition": item.condition or "",
            "quantity": item.quantity or 0,
            "unit": item.unit or "",
            "location": item.location or "",
            "shelf": item.shelf or "",
            "owner": item.owner or "",
            "remarks": item.remarks or ""
        })
    return result


@app.post("/api/store-balance")
def create_store_item(data: StoreItemSchema, db: Session = Depends(get_db)):
    if data.quantity is None:
        raise HTTPException(status_code=400, detail="Quantity is required")
    if data.quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity cannot be negative")

    received_date = parse_input_date(data.received_date)
    part_name = data.part_name.strip()
    part_number = data.part_number.strip()

    if not part_name:
        raise HTTPException(status_code=400, detail="Part name is required")
    if not part_number:
        raise HTTPException(status_code=400, detail="Part number is required")

    item = models.StoreItem(
        received_date=received_date,
        part_name=part_name,
        part_number=part_number,
        serial_number=data.serial_number.strip() if data.serial_number else None,
        condition=data.condition.strip() if data.condition else None,
        quantity=int(data.quantity),
        unit=data.unit.strip() if data.unit else None,
        location=data.location.strip() if data.location else None,
        shelf=data.shelf.strip() if data.shelf else None,
        owner=data.owner.strip() if data.owner else None,
        remarks=data.remarks.strip() if data.remarks else None
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="store_item",
        entity_id=item.id,
        message=f"Были внесены данные пользователем User в группу Store Balance: запчасть {part_name} {part_number} количество {item.quantity}",
        performed_by="User"
    )

    return {
        "id": item.id,
        "message": "Store item created"
    }


@app.put("/api/store-balance/{item_id}")
def update_store_item(item_id: int, data: StoreItemSchema, db: Session = Depends(get_db)):
    item = db.query(models.StoreItem).filter(models.StoreItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Store item not found")

    if data.quantity is None:
        raise HTTPException(status_code=400, detail="Quantity is required")
    if data.quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity cannot be negative")

    item.received_date = parse_input_date(data.received_date)
    part_name = data.part_name.strip()
    part_number = data.part_number.strip()

    if not part_name:
        raise HTTPException(status_code=400, detail="Part name is required")
    if not part_number:
        raise HTTPException(status_code=400, detail="Part number is required")

    item.part_name = part_name
    item.part_number = part_number
    item.serial_number = data.serial_number.strip() if data.serial_number else None
    item.condition = data.condition.strip() if data.condition else None
    item.quantity = int(data.quantity)
    item.unit = data.unit.strip() if data.unit else None
    item.location = data.location.strip() if data.location else None
    item.shelf = data.shelf.strip() if data.shelf else None
    item.owner = data.owner.strip() if data.owner else None
    item.remarks = data.remarks.strip() if data.remarks else None

    db.commit()
    db.refresh(item)

    create_notification(
        db,
        action_type="updated",
        entity_type="store_item",
        entity_id=item.id,
        message=f"Склад обновлён: {item.part_name} {item.part_number}, количество {item.quantity}",
        performed_by="User"
    )

    return {"message": "Store item updated"}


@app.delete("/api/store-balance/{item_id}")
def delete_store_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(models.StoreItem).filter(models.StoreItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Store item not found")

    part_name = item.part_name; part_number = item.part_number
    db.delete(item)
    db.commit()

    create_notification(
        db,
        action_type="deleted",
        entity_type="store_item",
        entity_id=item_id,
        message=f"Склад: позиция {part_name} {part_number} удалена",
        performed_by="User"
    )

    return {"message": "Store item deleted"}

# 15. История налетов (UTILIZATION HISTORY)
@app.get("/api/history/FLIGHT")
def get_flight_history(db: Session = Depends(get_db)):
    logs = db.query(models.ActionLog).filter(
        models.ActionLog.action_type == models.ActionType.FLIGHT
    ).order_by(models.ActionLog.date.asc(), models.ActionLog.id.asc()).all()

    totals_map = {}
    rows = []
    placeholder = "-"

    for log in logs:
        tail = (log.from_location or "").strip()
        if not tail:
            continue

        if tail not in totals_map:
            ac = db.query(models.Aircraft).filter(models.Aircraft.tail_number == tail).first()
            base_hours = ac.initial_total_time if ac and ac.initial_total_time else 0.0
            base_cycles = ac.initial_total_cycles if ac and ac.initial_total_cycles else 0
            totals_map[tail] = {"hours": base_hours, "cycles": base_cycles}

        state = totals_map[tail]

        delta_hours = log.snapshot_tt or 0.0
        delta_cycles = log.snapshot_tc or 0

        if log.is_maintenance:
            delta_hours = 0.0
            delta_cycles = 0

        state["hours"] += delta_hours
        state["cycles"] += delta_cycles

        atlb_ref = log.atlb_ref or extract_atlb_ref(log.comments) or ""

        log_date = log.date or datetime.utcnow()

        rows.append({
            "id": log.id,
            "date": log_date.strftime("%Y-%m-%d"),
            "aircraft": tail,
            "route": log.to_location or "",
            "added_tt": round(delta_hours, 2),
            "added_tc": delta_cycles,
            "cycles": delta_cycles,
            "ref": atlb_ref,
            "total_ttsn": hours_to_hhmm(state["hours"]),
            "total_tcsn": state["cycles"],
            "maintenance": bool(log.is_maintenance),
            "_sort": (log_date, log.id or 0)
        })

    rows.sort(key=lambda item: item["_sort"], reverse=True)
    for row in rows:
        row.pop("_sort", None)
    return rows


@app.get("/api/utilization/summary")
def get_utilization_summary(db: Session = Depends(get_db)):
    aircrafts = db.query(models.Aircraft).all()
    summary = []
    for ac in aircrafts:
        baseline = get_baseline_for_tail(ac.tail_number) or {}
        baseline_tt = hhmm_to_hours(baseline.get("initial_ttsn")) if baseline.get("initial_ttsn") else 0.0
        baseline_tc = baseline.get("initial_tcsn") or 0

        current_tt = ac.total_time if ac.total_time is not None else baseline_tt
        current_tc = ac.total_cycles if ac.total_cycles is not None else baseline_tc
        initial_tt = ac.initial_total_time if ac.initial_total_time not in (None, 0) else (baseline_tt or current_tt or 0.0)
        initial_tc = ac.initial_total_cycles if ac.initial_total_cycles not in (None, 0) else (baseline_tc or current_tc or 0)

        last_log = db.query(models.ActionLog).filter(
            models.ActionLog.action_type == models.ActionType.FLIGHT,
            models.ActionLog.from_location == ac.tail_number
        ).order_by(models.ActionLog.date.desc(), models.ActionLog.id.desc()).first()
        last_entry_date = last_log.date.strftime("%d.%m.%Y") if last_log and last_log.date else None
        if not last_entry_date and baseline.get("last_date"):
            last_entry_date = baseline.get("last_date")

        last_atlb_ref = ac.last_atlb_ref or extract_atlb_ref(last_log.comments if last_log else None) or baseline.get("last_atlb")
        next_atlb_ref = increment_atlb_ref(last_atlb_ref) if last_atlb_ref else None

        summary.append({
            "aircraft_id": ac.id,
            "tail_number": ac.tail_number,
            "model": ac.model,
            "msn": ac.msn or baseline.get("msn"),
            "initial_ttsn": hours_to_hhmm(initial_tt),
            "initial_tcsn": initial_tc,
            "current_ttsn": hours_to_hhmm(current_tt),
            "current_tcsn": current_tc,
            "last_atlb_ref": last_atlb_ref,
            "next_atlb_ref": next_atlb_ref,
            "last_entry_date": last_entry_date
        })
    return summary

# 16. Добавить Налет (UTILIZATION ADD)
@app.post("/api/actions/utilization")
def add_utilization(data: UtilizationSchema, db: Session = Depends(get_db)):
    ac = None
    if data.aircraft_id:
        ac = db.query(models.Aircraft).filter(models.Aircraft.id == data.aircraft_id).first()
    if not ac and data.aircraft_tail:
        ac = db.query(models.Aircraft).filter(func.lower(models.Aircraft.tail_number) == data.aircraft_tail.lower()).first()
    if not ac:
        raise HTTPException(status_code=404, detail="Aircraft not found")

    flight_hours = data.flight_hours if not data.maintenance else 0.0
    flight_cycles = data.flight_cycles if not data.maintenance else 0

    ac.total_time = (ac.total_time or 0.0) + flight_hours
    ac.total_cycles = (ac.total_cycles or 0) + flight_cycles

    # Обновляем базовые значения, если они не заполнены
    if ac.initial_total_time in (None, 0):
        ac.initial_total_time = (ac.total_time or 0.0) - flight_hours
    if ac.initial_total_cycles in (None, 0):
        ac.initial_total_cycles = (ac.total_cycles or 0) - flight_cycles

    if data.atlb_ref:
        ac.last_atlb_ref = data.atlb_ref.strip()

    installed_engines = []
    if not data.maintenance:
        installed_engines = db.query(models.Engine).filter(
            models.Engine.aircraft_id == ac.id,
            models.Engine.status == models.EngineStatus.INSTALLED
        ).all()
        for eng in installed_engines:
            eng.total_time = (eng.total_time or 0.0) + flight_hours
            eng.total_cycles = (eng.total_cycles or 0) + flight_cycles

    route_from = (data.flight_from or "").strip().upper()
    route_to = (data.flight_to or "").strip().upper()
    route_display = "" if not (route_from or route_to) else f"{route_from or '---'}-{route_to or '---'}"
    atlb_ref = (data.atlb_ref or "").strip()
    maintenance_type_label = None
    if data.maintenance:
        maintenance_type_label = "Maintenance"
        if not route_display:
            route_display = "Maintenance Entry"

    log_date = parse_input_date(data.date) or datetime.utcnow()

    new_log = models.ActionLog(
        action_type=models.ActionType.FLIGHT,
        from_location=ac.tail_number,
        to_location=route_display,
        snapshot_tt=flight_hours,
        snapshot_tc=flight_cycles,
        comments=atlb_ref if atlb_ref else None,
        is_maintenance=data.maintenance,
        date=log_date,
        atlb_ref=atlb_ref or None,
        maintenance_type=maintenance_type_label,
        block_time_str=None,
        flight_time_str=hours_to_hhmm(flight_hours) if flight_hours else ("00:00" if data.maintenance else None),
        from_apt=route_from or None,
        to_apt=route_to or None,
        performed_by="Admin"
    )
    db.add(new_log)
    db.commit()

    return {
        "message": "Utilization updated",
        "aircraft_id": ac.id,
        "tail_number": ac.tail_number,
        "current_ttsn": hours_to_hhmm(ac.total_time or 0.0),
        "current_tcsn": ac.total_cycles or 0,
        "next_atlb_ref": increment_atlb_ref(ac.last_atlb_ref)
    }


@app.post("/api/utilization/reset")
def reset_utilization_state(db: Session = Depends(get_db)):
    deleted_logs = (
        db.query(models.ActionLog)
        .filter(models.ActionLog.action_type == models.ActionType.FLIGHT)
        .delete(synchronize_session=False)
    )

    aircrafts = db.query(models.Aircraft).all()
    for ac in aircrafts:
        baseline = get_baseline_for_tail(ac.tail_number) or {}
        base_hours = hhmm_to_hours(baseline.get("initial_ttsn")) if baseline.get("initial_ttsn") else 0.0
        base_cycles = baseline.get("initial_tcsn") or 0

        ac.initial_total_time = base_hours
        ac.initial_total_cycles = base_cycles
        ac.total_time = base_hours
        ac.total_cycles = base_cycles
        ac.last_atlb_ref = baseline.get("last_atlb")

    db.commit()

    return {
        "message": "Utilization data reset",
        "deleted_logs": deleted_logs
    }
# 17. История ATLB
@app.get("/api/history/ATLB")
def get_atlb_history(db: Session = Depends(get_db)):
    logs = db.query(models.ActionLog).filter(
        models.ActionLog.action_type == models.ActionType.FLIGHT
    ).order_by(models.ActionLog.date.asc(), models.ActionLog.id.asc()).all()

    totals_map = {}
    rows = []
    placeholder = "-"

    for log in logs:
        tail = (log.from_location or "").strip()
        if not tail:
            continue

        if tail not in totals_map:
            ac = db.query(models.Aircraft).filter(models.Aircraft.tail_number == tail).first()
            base_hours = ac.initial_total_time if ac and ac.initial_total_time else 0.0
            base_cycles = ac.initial_total_cycles if ac and ac.initial_total_cycles else 0
            totals_map[tail] = {"hours": base_hours, "cycles": base_cycles}

        state = totals_map[tail]

        computed_block = compute_time_diff(log.block_out_str, log.block_in_str)
        computed_flight = compute_time_diff(log.flight_off_str, log.flight_on_str)

        delta_hours = log.snapshot_tt if log.snapshot_tt is not None else hhmm_to_hours(log.flight_time_str or computed_flight)
        delta_hours = delta_hours or 0.0
        delta_cycles = log.snapshot_tc if log.snapshot_tc is not None else 0

        if log.is_maintenance:
            delta_hours = 0.0
            delta_cycles = 0

        state["hours"] += delta_hours
        state["cycles"] += delta_cycles

        atlb_ref = log.atlb_ref or extract_atlb_ref(log.comments) or ""

        block_time_text = normalize_time_str(log.block_time_str, computed_block or "")
        flight_time_text = normalize_time_str(
            log.flight_time_str,
            computed_flight or normalize_time_str(hours_to_hhmm(delta_hours), "")
        )

        if not block_time_text:
            block_time_text = placeholder
        if not flight_time_text or (log.is_maintenance and not (computed_flight or log.flight_time_str)):
            flight_time_text = placeholder

        if log.is_maintenance:
            flight_leg = "Maintenance"
        elif log.from_apt or log.to_apt:
            flight_leg = f"{(log.from_apt or '---').upper()}-{(log.to_apt or '---').upper()}"
        elif log.to_location:
            flight_leg = log.to_location
        else:
            flight_leg = placeholder

        log_date = log.date or datetime.utcnow()

        block_out_display = sanitize_time_input(log.block_out_str) or placeholder
        block_in_display = sanitize_time_input(log.block_in_str) or placeholder
        flight_off_display = sanitize_time_input(log.flight_off_str) or placeholder
        flight_on_display = sanitize_time_input(log.flight_on_str) or placeholder

        rows.append({
            "id": log.id,
            "date": log_date.strftime("%Y-%m-%d"),
            "tail_number": tail,
            "atlb_sheet": atlb_ref,
            "flight_leg": flight_leg,
            "block_out": block_out_display,
            "block_in": block_in_display,
            "block_time": block_time_text,
            "flight_off": flight_off_display,
            "flight_on": flight_on_display,
            "flight_time_text": flight_time_text,
            "flight_time_decimal": round(delta_hours, 2),
            "cycles": delta_cycles,
            "total_ttsn": hours_to_hhmm(state["hours"]),
            "total_tcsn": state["cycles"],
            "maintenance": log.maintenance_type or ("Maintenance Only" if log.is_maintenance else ""),
            "maintenance_only": bool(log.is_maintenance),
            "user": log.performed_by or "Admin",
            "oil_1": log.oil_1,
            "oil_2": log.oil_2,
            "oil_3": log.oil_3,
            "oil_4": log.oil_4,
            "oil_apu": log.oil_apu,
            "hyd_1": log.hyd_1,
            "hyd_2": log.hyd_2,
            "hyd_3": log.hyd_3,
            "hyd_4": log.hyd_4,
            "_sort": (log_date, log.id or 0)
        })

    rows.sort(key=lambda item: item["_sort"], reverse=True)
    for row in rows:
        row.pop("_sort", None)
    return rows

# 18. Сохранить ATLB (и обновить счетчики)
@app.post("/api/actions/atlb")
def save_atlb(data: ATLBSchema, db: Session = Depends(get_db)):
    # 1. Ищем самолет
    ac = db.query(models.Aircraft).filter(models.Aircraft.id == data.aircraft_id).first()
    if not ac: raise HTTPException(404, "Aircraft not found")
    
    atlb_no = (data.atlb_no or "").strip()
    if not atlb_no:
        raise HTTPException(status_code=400, detail="ATLB sheet number is required")

    log_date = parse_input_date(data.date) or datetime.utcnow()

    maintenance_only = bool(data.maintenance_only)

    block_out = sanitize_time_input(data.out_time)
    block_in = sanitize_time_input(data.in_time)
    flight_off = sanitize_time_input(data.off_time)
    flight_on = sanitize_time_input(data.on_time)

    computed_block = compute_time_diff(block_out, block_in)
    computed_flight = compute_time_diff(flight_off, flight_on)

    block_time_str = normalize_time_str(data.block_time, "")
    if not block_time_str and computed_block:
        block_time_str = computed_block

    flight_time_str = normalize_time_str(data.flight_time, "")
    if not flight_time_str and computed_flight:
        flight_time_str = computed_flight

    flight_hours_decimal = hhmm_to_hours(flight_time_str)
    cycles_to_add = data.cycles or 0
    if maintenance_only:
        flight_hours_decimal = 0.0
        cycles_to_add = 0
        block_time_str = None
        flight_time_str = None
        block_out = None
        block_in = None
        flight_off = None
        flight_on = None

    # 3. Обновляем Самолет
    if ac.total_time is None:
        ac.total_time = 0.0
    if ac.total_cycles is None:
        ac.total_cycles = 0

    if not maintenance_only:
        ac.total_time += flight_hours_decimal
        ac.total_cycles += cycles_to_add
    else:
        ac.total_time = ac.total_time or 0.0
        ac.total_cycles = ac.total_cycles or 0
    
    # 4. Обновляем Двигатели
    if not maintenance_only:
        engines = db.query(models.Engine).filter(models.Engine.aircraft_id == ac.id, models.Engine.status == "INSTALLED").all()
        for eng in engines:
            eng.total_time = (eng.total_time or 0.0) + flight_hours_decimal
            eng.total_cycles = (eng.total_cycles or 0) + cycles_to_add
    
    if atlb_no:
        ac.last_atlb_ref = atlb_no

    if ac.initial_total_time in (None, 0):
        ac.initial_total_time = max(0.0, (ac.total_time or 0.0) - flight_hours_decimal)
    if ac.initial_total_cycles in (None, 0):
        ac.initial_total_cycles = max(0, (ac.total_cycles or 0) - cycles_to_add)

    if maintenance_only and ac.initial_total_time is None:
        ac.initial_total_time = ac.total_time or 0.0
    if maintenance_only and ac.initial_total_cycles is None:
        ac.initial_total_cycles = ac.total_cycles or 0

    if maintenance_only and ac.total_time is None:
        ac.total_time = 0.0
    if maintenance_only and ac.total_cycles is None:
        ac.total_cycles = 0

    from_apt = (data.from_apt or "").strip().upper()
    to_apt = (data.to_apt or "").strip().upper()

    if maintenance_only:
        route_display = "Maintenance"
    elif from_apt or to_apt:
        route_display = f"{from_apt or '---'}-{to_apt or '---'}"
    else:
        route_display = ""

    comments_parts = []
    if atlb_no:
        comments_parts.append(f"ATLB: {atlb_no}")
    if data.maintenance_type:
        comments_parts.append(f"Maint: {data.maintenance_type}")
    if maintenance_only:
        comments_parts.append("Maintenance Only")
    comment_text = " | ".join(part for part in comments_parts if part)

    # 5. Лог
    new_log = models.ActionLog(
        action_type="FLIGHT",
        from_location=ac.tail_number,
        to_location=route_display,
        snapshot_tt=flight_hours_decimal,
        snapshot_tc=cycles_to_add,
        comments=comment_text if comment_text else None,
        date=log_date,
        is_maintenance=maintenance_only,
        atlb_ref=atlb_no,
        maintenance_type=data.maintenance_type.strip() if data.maintenance_type else None,
        block_time_str=block_time_str or None,
        flight_time_str=flight_time_str or None,
        block_out_str=block_out,
        block_in_str=block_in,
        flight_off_str=flight_off,
        flight_on_str=flight_on,
        from_apt=from_apt if from_apt else None,
        to_apt=to_apt if to_apt else None,
        oil_1=data.oil_1,
        oil_2=data.oil_2,
        oil_3=data.oil_3,
        oil_4=data.oil_4,
        oil_apu=data.oil_apu,
        hyd_1=data.hyd_1,
        hyd_2=data.hyd_2,
        hyd_3=data.hyd_3,
        hyd_4=data.hyd_4,
        performed_by="Admin"
    )
    db.add(new_log)
    db.commit()
    return {"message": "Flight Saved & Counters Updated"}

# 19. Сохранить параметры двигателя (N1, N2, EGT)
@app.post("/api/engines/parameters")
def save_engine_parameters(data: EngineParametersSchema, db: Session = Depends(get_db)):
    from datetime import datetime
    
    # Находим двигатель
    eng = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
    if not eng:
        raise HTTPException(404, "Engine not found")
    
    # Парсим дату
    try:
        param_date = datetime.fromisoformat(data.date.replace('Z', '+00:00'))
    except:
        param_date = datetime.now()
    
    # Обновляем текущие параметры двигателя
    if data.n1_takeoff is not None:
        eng.n1_takeoff = data.n1_takeoff
    if data.n2_takeoff is not None:
        eng.n2_takeoff = data.n2_takeoff
    if data.egt_takeoff is not None:
        eng.egt_takeoff = data.egt_takeoff
    if data.n1_cruise is not None:
        eng.n1_cruise = data.n1_cruise
    if data.n2_cruise is not None:
        eng.n2_cruise = data.n2_cruise
    if data.egt_cruise is not None:
        eng.egt_cruise = data.egt_cruise
    eng.last_param_update = param_date
    
    # Сохраняем в историю
    history_entry = models.EngineParameterHistory(
        engine_id=eng.id,
        date=param_date,
        n1_takeoff=data.n1_takeoff,
        n2_takeoff=data.n2_takeoff,
        egt_takeoff=data.egt_takeoff,
        n1_cruise=data.n1_cruise,
        n2_cruise=data.n2_cruise,
        egt_cruise=data.egt_cruise
    )
    db.add(history_entry)
    db.commit()
    
    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="engine_parameters",
        entity_id=history_entry.id,
        message=f"Были внесены данные пользователем User в группу Engine Parameters: параметры для двигателя {eng.current_sn}",
        performed_by="User"
    )
    
    return {
        "message": f"Parameters saved for engine {eng.current_sn}",
        "engine_sn": eng.current_sn,
        "aircraft": eng.aircraft.tail_number if eng.aircraft else None,
        "position": eng.position,
        "date": param_date.isoformat()
    }

# 20. Получить историю параметров двигателя
@app.get("/api/engines/parameters/history")
def get_parameter_history(engine_id: int = None, db: Session = Depends(get_db)):
    query = db.query(models.EngineParameterHistory)
    
    if engine_id:
        query = query.filter(models.EngineParameterHistory.engine_id == engine_id)
    
    history = query.order_by(models.EngineParameterHistory.date.desc()).all()
    
    result = []
    for h in history:
        eng = h.engine
        result.append({
            "id": h.id,
            "date": h.date.isoformat() if h.date else None,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "engine_sn": eng.current_sn if eng else "Unknown",
            "aircraft": eng.aircraft.tail_number if eng and eng.aircraft else None,
            "position": eng.position if eng else None,
            "n1_takeoff": h.n1_takeoff,
            "n2_takeoff": h.n2_takeoff,
            "egt_takeoff": h.egt_takeoff,
            "n1_cruise": h.n1_cruise,
            "n2_cruise": h.n2_cruise,
            "egt_cruise": h.egt_cruise
        })
    
    return result

# --- BORESCOPE INSPECTIONS API ---

@app.get("/api/history/BORESCOPE")
def get_borescope_history(db: Session = Depends(get_db)):
    inspections = db.query(models.BoroscopeInspection).order_by(models.BoroscopeInspection.date.desc()).all()
    result = []
    for insp in inspections:
        result.append({
            "id": insp.id,
            "date": insp.date,
            "aircraft": insp.aircraft,
            "serial_number": insp.serial_number,
            "position": insp.position,
            "gss_id": insp.gss_id,
            "inspector": insp.inspector,
            "link": insp.link
        })
    return result

@app.post("/api/history/BORESCOPE")
def create_borescope_inspection(data: BoroscopeSchema, db: Session = Depends(get_db)):
    new_inspection = models.BoroscopeInspection(
        date=data.date,
        aircraft=data.aircraft,
        serial_number=data.serial_number,
        position=data.position,
        gss_id=data.gss_id,
        inspector=data.inspector,
        link=data.link
    )
    db.add(new_inspection)
    db.commit()
    db.refresh(new_inspection)

    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="borescope",
        entity_id=new_inspection.id,
        message=f"Бороскопия: борт {data.aircraft}, двигатель {data.serial_number}, позиция {data.position or '-'} (инспектор {data.inspector or '-'})",
        performed_by="User"
    )
    return {"status": "ok", "id": new_inspection.id}

# --- PURCHASE ORDERS API ---

@app.get("/api/history/PURCHASE_ORDER")
def get_purchase_orders_history(db: Session = Depends(get_db)):
    orders = db.query(models.PurchaseOrder).order_by(models.PurchaseOrder.date.desc()).all()
    result = []
    for order in orders:
        result.append({
            "id": order.id,
            "date": order.date,
            "name": order.name,
            "purpose": order.purpose,
            "aircraft": order.aircraft,
            "ro_number": order.ro_number,
            "link": order.link
        })
    return result

@app.post("/api/history/PURCHASE_ORDER")
def create_purchase_order(data: PurchaseOrderSchema, db: Session = Depends(get_db)):
    new_order = models.PurchaseOrder(
        date=data.date,
        name=data.name,
        purpose=data.purpose,
        aircraft=data.aircraft,
        ro_number=data.ro_number,
        link=data.link
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="purchase_order",
        entity_id=new_order.id,
        message=f"Purchase Order '{data.name}' для борта {data.aircraft or '-'} (RO: {data.ro_number or '-'}) создан",
        performed_by="User"
    )
    return {"status": "ok", "id": new_order.id}

# --- GENERIC HISTORY CREATION (used by Installation edit mode) ---

@app.post("/api/history/{action_type}")
def create_history_record(action_type: str, data: ActionLogCreateSchema, db: Session = Depends(get_db)):
    normalized_type = action_type.upper()
    if normalized_type not in {"INSTALL"}:
        raise HTTPException(400, f"Creating records for {action_type} via table edit mode is not supported")
    if not data.date:
        raise HTTPException(400, "Date is required for installation history entries")

    engine = None
    serial_candidates = [data.engine_original_sn, data.engine_current_sn]
    for sn in serial_candidates:
        if not sn:
            continue
        engine = db.query(models.Engine).filter(
            or_(models.Engine.original_sn == sn, models.Engine.current_sn == sn)
        ).first()
        if engine:
            break
    if not engine:
        raise HTTPException(400, "Engine with the provided serial number was not found. Please add the engine first.")

    if not data.to_aircraft:
        raise HTTPException(400, "Aircraft tail number is required for installation records")
    aircraft = db.query(models.Aircraft).filter(models.Aircraft.tail_number == data.to_aircraft).first()
    if not aircraft:
        raise HTTPException(400, f"Aircraft {data.to_aircraft} not found")
    aircraft_tail = aircraft.tail_number

    if data.position is None:
        raise HTTPException(400, "Engine position is required for installation records")

    log = models.ActionLog(
        action_type=normalized_type,
        engine_id=engine.id,
        from_location=data.from_location,
        to_location=data.to_location,
        to_aircraft=aircraft_tail,
        position=data.position,
        snapshot_tt=data.snapshot_tt,
        snapshot_tc=data.snapshot_tc,
        comments=data.comments,
        file_url=data.file_url
    )

    parsed_date = parse_input_date(data.date)
    if parsed_date:
        log.date = parsed_date

    # Mirror changes on the engine itself so dashboards stay in sync
    if normalized_type == "INSTALL":
        engine.status = models.EngineStatus.INSTALLED
        engine.location_id = None
        engine.aircraft_id = aircraft.id
        engine.position = data.position
        if data.snapshot_tt is not None:
            engine.total_time = data.snapshot_tt
            engine.tsn_at_install = data.snapshot_tt
        if data.snapshot_tc is not None:
            engine.total_cycles = data.snapshot_tc
            engine.csn_at_install = data.snapshot_tc
        engine.install_date = parsed_date or datetime.utcnow()

    db.add(log)
    db.commit()
    db.refresh(log)
    return {"message": "Installation history record added", "id": log.id}

# --- FALLBACK HISTORY ENDPOINT (ActionLog-based) ---

@app.get("/api/history/{action_type}")
def get_history(action_type: str, db: Session = Depends(get_db)):
    """Return history entries stored in the generic action_logs table."""
    logs = (
        db.query(models.ActionLog)
        .filter(models.ActionLog.action_type == action_type)
        .order_by(models.ActionLog.date.desc())
        .all()
    )
    res = []
    for l in logs:
        orig_sn = l.engine.original_sn if l.engine else "Deleted"
        curr_sn = l.engine.current_sn if l.engine else "Deleted"

        res.append({
            "id": l.id,
            "date": l.date.strftime("%Y-%m-%d"),
            "original_sn": orig_sn,
            "current_sn": curr_sn,
            "from": l.from_location or l.from_aircraft or "-",
            "to": l.to_location or l.to_aircraft or "-",
            "tt": l.snapshot_tt,
            "tc": l.snapshot_tc,
            "remarks": l.comments,
        })
    return res


# --- UTILIZATION PARAMETERS ENDPOINTS ---

@app.get("/api/utilization-parameters")
def get_utilization_parameters(db: Session = Depends(get_db)):
    """Get all utilization parameters from database"""
    params = db.query(models.UtilizationParameter).order_by(
        models.UtilizationParameter.date.desc()
    ).all()
    
    result = []
    for p in params:
        result.append({
            "id": p.id,
            "date": p.date.strftime("%Y-%m-%d") if p.date else None,
            "aircraft": p.aircraft,
            "ttsn": p.ttsn,
            "tcsn": p.tcsn,
            "period": p.period,
            "date_from": p.date_from.strftime("%Y-%m-%d") if p.date_from else None,
            "date_to": p.date_to.strftime("%Y-%m-%d") if p.date_to else None,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })
    return result


@app.post("/api/utilization-parameters")
def create_utilization_parameter(data: UtilizationParameterSchema, db: Session = Depends(get_db)):
    """Create new utilization parameter record"""
    parsed_date = parse_input_date(data.date)
    if not parsed_date:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    parsed_date_from = parse_input_date(data.date_from) if data.date_from else None
    parsed_date_to = parse_input_date(data.date_to) if data.date_to else None
    
    new_param = models.UtilizationParameter(
        date=parsed_date,
        aircraft=data.aircraft,
        ttsn=data.ttsn,
        tcsn=data.tcsn,
        period=data.period,
        date_from=parsed_date_from,
        date_to=parsed_date_to
    )
    
    db.add(new_param)
    db.commit()
    db.refresh(new_param)
    
    # Log action
    period_text = "Период" if data.period else "Обычный"
    create_notification(
        db,
        action_type="created",
        entity_type="utilization_parameter",
        entity_id=new_param.id,
        message=f"Были внесены данные пользователем User в группу Utilization Parameters: {period_text} параметры для самолета {data.aircraft}",
        performed_by="User"
    )
    
    return {
        "message": "Utilization parameter created successfully",
        "id": new_param.id
    }


@app.put("/api/utilization-parameters/{param_id}")
def update_utilization_parameter(param_id: int, data: UtilizationParameterSchema, db: Session = Depends(get_db)):
    """Update existing utilization parameter record"""
    param = db.query(models.UtilizationParameter).filter(
        models.UtilizationParameter.id == param_id
    ).first()
    
    if not param:
        raise HTTPException(status_code=404, detail="Utilization parameter not found")
    
    parsed_date = parse_input_date(data.date)
    if not parsed_date:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    parsed_date_from = parse_input_date(data.date_from) if data.date_from else None
    parsed_date_to = parse_input_date(data.date_to) if data.date_to else None
    
    param.date = parsed_date
    param.aircraft = data.aircraft
    param.ttsn = data.ttsn
    param.tcsn = data.tcsn
    param.period = data.period
    param.date_from = parsed_date_from
    param.date_to = parsed_date_to
    
    db.commit()
    db.refresh(param)
    
    # Log action
    period_text = "Период" if data.period else "Обычный"
    create_notification(
        db,
        action_type="updated",
        entity_type="utilization_parameter",
        entity_id=param.id,
        message=f"Были обновлены данные пользователем User в группу Utilization Parameters: {period_text} параметры для самолета {data.aircraft}",
        performed_by="User"
    )
    return {"message": "Utilization parameter updated successfully"}


@app.delete("/api/utilization-parameters/{param_id}")
def delete_utilization_parameter(param_id: int, db: Session = Depends(get_db)):
    """Delete utilization parameter record"""
    param = db.query(models.UtilizationParameter).filter(
        models.UtilizationParameter.id == param_id
    ).first()
    
    if not param:
        raise HTTPException(status_code=404, detail="Utilization parameter not found")
    
    # Capture details for log before delete
    aircraft = param.aircraft
    period_text = "Период" if param.period else "Обычный"

    db.delete(param)
    db.commit()

    # Log action
    create_notification(
        db,
        action_type="deleted",
        entity_type="utilization_parameter",
        entity_id=param_id,
        message=f"Были удалены данные пользователем User в группу Utilization Parameters: {period_text} параметры для самолета {aircraft}",
        performed_by="User"
    )

    return {"message": "Utilization parameter deleted successfully"}


# --- AUTHENTICATION & USER MANAGEMENT ENDPOINTS ---

@app.post("/api/auth/login")
def login(credentials: LoginSchema, db: Session = Depends(get_db)):
    """Login user"""
    user = db.query(models.User).filter(
        models.User.username == credentials.username
    ).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    if not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "position": user.position,
        "role": user.role,
        "photo_url": user.photo_url
    }


@app.get("/api/users")
def get_all_users(db: Session = Depends(get_db)):
    """Get all users (for admin)"""
    users = db.query(models.User).all()
    return [{
        "id": u.id,
        "username": u.username,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "position": u.position,
        "role": u.role,
        "photo_url": u.photo_url,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None
    } for u in users]


@app.post("/api/users")
def create_user(data: UserCreateSchema, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create new user (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create users")
    
    # Check if username exists
    existing = db.query(models.User).filter(
        models.User.username == data.username
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Create user
    new_user = models.User(
        username=data.username,
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        position=data.position,
        role=data.role,
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {
        "message": "User created successfully",
        "id": new_user.id,
        "username": new_user.username
    }


@app.put("/api/users/{user_id}")
def update_user(user_id: int, data: UserUpdateSchema, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update user (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update users")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update fields
    if data.first_name is not None:
        user.first_name = data.first_name
    if data.last_name is not None:
        user.last_name = data.last_name
    if data.position is not None:
        user.position = data.position
    if data.role is not None:
        user.role = data.role
    if data.photo_url is not None:
        user.photo_url = data.photo_url
    if data.is_active is not None:
        user.is_active = data.is_active
    
    db.commit()
    db.refresh(user)
    
    return {"message": "User updated successfully"}


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete user (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete users")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    db.delete(user)
    db.commit()
    
    return {"message": "User deleted successfully"}


@app.post("/api/users/{user_id}/change-password")
def change_password(user_id: int, data: ChangePasswordSchema, db: Session = Depends(get_db)):
    """Change user password"""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    
    user.password_hash = hash_password(data.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}


# --- NOTIFICATIONS ENDPOINTS ---

@app.get("/api/notifications")
def get_notifications(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Get notifications for user"""
    query = db.query(models.Notification)
    
    if user_id:
        # Get notifications for specific user OR for all admins
        query = query.filter(
            or_(
                models.Notification.user_id == user_id,
                models.Notification.user_id == None
            )
        )
    else:
        # Get all notifications for admins
        query = query.filter(models.Notification.user_id == None)
    
    notifications = query.order_by(models.Notification.created_at.desc()).limit(100).all()
    
    return [{
        "id": n.id,
        "action_type": n.action_type,
        "entity_type": n.entity_type,
        "entity_id": n.entity_id,
        "message": n.message,
        "performed_by": n.performed_by,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None
    } for n in notifications]


@app.get("/api/notifications/unread-count")
def get_unread_count(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Get unread notifications count"""
    query = db.query(models.Notification).filter(models.Notification.is_read == False)
    
    if user_id:
        query = query.filter(
            or_(
                models.Notification.user_id == user_id,
                models.Notification.user_id == None
            )
        )
    else:
        query = query.filter(models.Notification.user_id == None)
    
    count = query.count()
    return {"count": count}


@app.put("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, db: Session = Depends(get_db)):
    """Mark notification as read"""
    notification = db.query(models.Notification).filter(
        models.Notification.id == notification_id
    ).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notification.is_read = True
    db.commit()
    
    return {"message": "Notification marked as read"}


@app.put("/api/notifications/mark-all-read")
def mark_all_read(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Mark all notifications as read"""
    query = db.query(models.Notification).filter(models.Notification.is_read == False)
    
    if user_id:
        query = query.filter(
            or_(
                models.Notification.user_id == user_id,
                models.Notification.user_id == None
            )
        )
    else:
        query = query.filter(models.Notification.user_id == None)
    
    query.update({"is_read": True})
    db.commit()
    
    return {"message": "All notifications marked as read"}



