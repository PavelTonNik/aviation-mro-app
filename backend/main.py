from fastapi import FastAPI, Depends, HTTPException, Query, status, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta, timezone, date as DateType
import json
from pathlib import Path
import hashlib
import secrets
import os
from passlib.context import CryptContext
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from . import models, database
except ImportError:  # fallback when running as a standalone script
    import models
    import database

def _sync_engine_status_from_history(db):
    """
    Синхронизирует физическое состояние двигателей (aircraft_id, position, status, condition_1)
    на основе истории Installation/Removal в action_logs.
    
    Логика:
    - Для каждого двигателя находит все INSTALL/REMOVE операции
    - Определяет последнюю операцию по дате
    - Если последняя = INSTALL: устанавливает aircraft_id, position, status=INSTALLED
    - Если последняя = REMOVE: очищает aircraft_id, position, устанавливает status и condition_1
                               используя значение из condition_1_at_removal (что выбрал пользователь)
    
    Возвращает словарь с результатами синхронизации.
    """
    try:
        from sqlalchemy import desc
        engines_to_sync = []
        changes_log = []
        
        # Получаем все двигатели
        all_engines = db.query(models.Engine).all()
        
        for engine in all_engines:
            # Получаем все INSTALL/REMOVE операции для этого двигателя, сортированные по дате (новые в конце)
            actions = db.query(models.ActionLog).filter(
                models.ActionLog.engine_id == engine.id,
                models.ActionLog.action_type.in_(["INSTALL", "REMOVE"])
            ).order_by(models.ActionLog.date.asc()).all()
            
            if not actions:
                # Нет истории - пропускаем
                continue
            
            # Последняя операция по дате (в конце списка, так как сортировали по asc)
            last_action = actions[-1]
            
            # Проверяем, нужна ли синхронизация
            current_state_matches = False
            
            if last_action.action_type == "INSTALL":
                # После INSTALL двигатель должен быть на борту
                # Получаем aircraft_id из to_aircraft (tail number)
                to_aircraft_str = last_action.to_aircraft  # например "ER-BAT"
                aircraft_obj = db.query(models.Aircraft).filter(
                    models.Aircraft.tail_number == to_aircraft_str
                ).first() if to_aircraft_str else None
                
                target_aircraft_id = aircraft_obj.id if aircraft_obj else None
                target_position = last_action.position
                
                if (engine.status == "INSTALLED" and 
                    engine.aircraft_id == target_aircraft_id and
                    engine.position == target_position):
                    current_state_matches = True
                else:
                    # Нужна синхронизация - двигатель должен быть на борту
                    old_state = f"status={engine.status}, aircraft_id={engine.aircraft_id}, pos={engine.position}"
                    
                    engine.status = "INSTALLED"
                    engine.aircraft_id = target_aircraft_id
                    engine.position = target_position
                    # Не меняем condition_1 для INSTALL
                    
                    new_state = f"status=INSTALLED, aircraft_id={target_aircraft_id}, pos={target_position}"
                    changes_log.append(f"Engine {engine.gss_sn or engine.id}: INSTALL - {old_state} → {new_state}")
                    engines_to_sync.append(engine)
                    
            elif last_action.action_type == "REMOVE":
                # После REMOVE двигатель должен быть снят с борта
                new_status = last_action.condition_1_at_removal or "SV"
                
                if (engine.status == new_status and 
                    engine.aircraft_id is None and
                    engine.position is None and
                    engine.condition_1 == new_status):
                    current_state_matches = True
                else:
                    # Нужна синхронизация - двигатель должен быть снят с борта
                    old_state = f"status={engine.status}, aircraft_id={engine.aircraft_id}, pos={engine.position}, cond_1={engine.condition_1}"
                    
                    engine.status = new_status
                    engine.condition_1 = new_status
                    engine.aircraft_id = None
                    engine.position = None
                    
                    new_state = f"status={new_status}, aircraft_id=None, pos=None, cond_1={new_status}"
                    changes_log.append(f"Engine {engine.gss_sn or engine.id}: REMOVE - {old_state} → {new_state}")
                    engines_to_sync.append(engine)
        
        # Если есть изменения - сохраняем их
        if engines_to_sync:
            db.commit()
            return {
                "synced_count": len(engines_to_sync),
                "changes": changes_log
            }
        else:
            return {
                "synced_count": 0,
                "changes": []
            }
            
    except Exception as e:
        print(f"❌ Ошибка при синхронизации: {e}")
        import traceback
        traceback.print_exc()
        return {
            "synced_count": 0,
            "changes": [f"Error: {e}"]
        }

# Создаем таблицы в БД (если их нет)
try:
    print("📋 Creating database tables...")
    models.Base.metadata.create_all(bind=database.engine)
    print("✅ Database tables created/verified")
except Exception as e:
    print(f"⚠️ Warning: Could not create tables: {e}")

app = FastAPI(title="Aviation MRO System")

# CORS Configuration
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    # Ensure all tables exist first (from models.py)
    try:
        print("� Creating/verifying all database tables...")
        print(f"🔗 Database: {database.DATABASE_URL[:50]}...")
        models.Base.metadata.create_all(bind=database.engine)
        print("✅ All tables created/verified successfully")
        
        # Add work_type column if missing
        from sqlalchemy import text
        with database.engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE borescope_inspections ADD COLUMN work_type VARCHAR DEFAULT 'All Engine' NOT NULL"))
                conn.commit()
                print("✅ Added work_type column")
            except:
                pass  # Column already exists

            # Add comment column if missing
            try:
                conn.execute(text("ALTER TABLE borescope_inspections ADD COLUMN comment TEXT"))
                conn.commit()
                print("✅ Added borescope comment column")
            except:
                pass  # Column already exists

            # Add inspection_report column if missing
            try:
                conn.execute(text("ALTER TABLE borescope_inspections ADD COLUMN inspection_report JSON"))
                conn.commit()
                print("✅ Added inspection_report column")
            except:
                pass  # Column already exists
        
        print("✅ Schema verification complete")
    except Exception as e:
        print(f"⚠️ Schema verification warning: {e}")
    
    # Add missing columns directly for PostgreSQL
    if not database.IS_SQLITE:
        try:
            print("🔧 Adding missing columns to PostgreSQL...")
            from sqlalchemy import text
            db = database.SessionLocal()
            try:
                # Add price column to engines if missing
                db.execute(text("""
                    DO $$ 
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='engines' AND column_name='price'
                        ) THEN
                            ALTER TABLE engines ADD COLUMN price DOUBLE PRECISION;
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='action_logs' AND column_name='ttsn'
                        ) THEN
                            ALTER TABLE action_logs ADD COLUMN ttsn DOUBLE PRECISION;
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='action_logs' AND column_name='tcsn'
                        ) THEN
                            ALTER TABLE action_logs ADD COLUMN tcsn INTEGER;
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='action_logs' AND column_name='ttsn_ac'
                        ) THEN
                            ALTER TABLE action_logs ADD COLUMN ttsn_ac DOUBLE PRECISION;
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='action_logs' AND column_name='tcsn_ac'
                        ) THEN
                            ALTER TABLE action_logs ADD COLUMN tcsn_ac INTEGER;
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='action_logs' AND column_name='remarks_removal'
                        ) THEN
                            ALTER TABLE action_logs ADD COLUMN remarks_removal TEXT;
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='action_logs' AND column_name='supplier'
                        ) THEN
                            ALTER TABLE action_logs ADD COLUMN supplier VARCHAR(255);
                        END IF;
                        -- Ensure new Shipment columns exist
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='shipments' AND column_name='engine_model'
                        ) THEN
                            ALTER TABLE shipments ADD COLUMN engine_model VARCHAR(100);
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='shipments' AND column_name='gss_id'
                        ) THEN
                            ALTER TABLE shipments ADD COLUMN gss_id VARCHAR(100);
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='purchase_orders' AND column_name='part_number'
                        ) THEN
                            ALTER TABLE purchase_orders ADD COLUMN part_number VARCHAR;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='purchase_orders' AND column_name='serial_number'
                        ) THEN
                            ALTER TABLE purchase_orders ADD COLUMN serial_number VARCHAR;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='purchase_orders' AND column_name='price'
                        ) THEN
                            ALTER TABLE purchase_orders ADD COLUMN price DOUBLE PRECISION;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='borescope_inspections' AND column_name='comment'
                        ) THEN
                            ALTER TABLE borescope_inspections ADD COLUMN comment TEXT;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='utilization_parameters' AND column_name='position'
                        ) THEN
                            ALTER TABLE utilization_parameters ADD COLUMN position INTEGER;
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='utilization_parameters' AND column_name='engine_id'
                        ) THEN
                            ALTER TABLE utilization_parameters ADD COLUMN engine_id INTEGER;
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='engines' AND column_name='condition_1'
                        ) THEN
                            ALTER TABLE engines ADD COLUMN condition_1 VARCHAR DEFAULT 'SV';
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='engines' AND column_name='condition_2'
                        ) THEN
                            ALTER TABLE engines ADD COLUMN condition_2 VARCHAR DEFAULT 'New';
                        END IF;
                        
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name='action_logs' AND column_name='condition_1_at_removal'
                        ) THEN
                            ALTER TABLE action_logs ADD COLUMN condition_1_at_removal VARCHAR;
                        END IF;
                    END $$;
                """))
                db.commit()
                print("✅ Missing columns added successfully")
            except Exception as col_e:
                print(f"ℹ️  Column update: {col_e}")
                db.rollback()
            finally:
                db.close()
        except Exception as e:
            print(f"ℹ️  Column sync skipped: {e}")
    
    ensure_sqlite_column("aircrafts", "initial_total_time FLOAT DEFAULT 0")
    ensure_sqlite_column("aircrafts", "initial_total_cycles INTEGER DEFAULT 0")
    ensure_sqlite_column("aircrafts", "last_atlb_ref TEXT")
    ensure_sqlite_column("action_logs", "is_maintenance BOOLEAN DEFAULT 0")
    ensure_sqlite_column("action_logs", "atlb_ref TEXT")
    ensure_sqlite_column("action_logs", "maintenance_type TEXT")
    ensure_sqlite_column("engines", "condition_1 TEXT DEFAULT 'SV'")
    ensure_sqlite_column("engines", "condition_2 TEXT DEFAULT 'New'")
    ensure_sqlite_column("action_logs", "condition_1_at_removal TEXT")
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
    ensure_sqlite_column("action_logs", "supplier TEXT")
    ensure_sqlite_column("utilization_parameters", "position INTEGER")
    ensure_sqlite_column("utilization_parameters", "engine_id INTEGER")
    ensure_sqlite_column("purchase_orders", "part_number TEXT")
    ensure_sqlite_column("purchase_orders", "serial_number TEXT")
    ensure_sqlite_column("purchase_orders", "price FLOAT DEFAULT 0")
    ensure_sqlite_column("action_logs", "performed_by TEXT")
    ensure_sqlite_column("action_logs", "ttsn FLOAT")
    ensure_sqlite_column("action_logs", "tcsn INTEGER")
    ensure_sqlite_column("action_logs", "ttsn_ac FLOAT")
    ensure_sqlite_column("action_logs", "tcsn_ac INTEGER")
    ensure_sqlite_column("action_logs", "remarks_removal TEXT")
    # Ensure new Shipment columns exist in local SQLite
    ensure_sqlite_column("shipments", "engine_model TEXT")
    ensure_sqlite_column("shipments", "gss_id TEXT")

    # Открываем сессию базы данных
    db = database.SessionLocal()
    try:
        # 0. Создаем админа если его нет
        admin_user = db.query(models.User).filter(models.User.username == "admin").first()
        if not admin_user:
            print("🚀 Creating default admin user...")
            hashed_password = hash_password("admin123")
            admin_user = models.User(
                username="admin",
                password_hash=hashed_password,
                first_name="Admin",
                last_name="User",
                role="admin",
                is_active=True
            )
            db.add(admin_user)
            db.commit()
            print("✅ Admin user created: admin / admin123")
        else:
            # Ensure admin account is valid (role, active, password hash)
            changed = False
            if not admin_user.is_active:
                admin_user.is_active = True
                changed = True
            if admin_user.role != "admin":
                admin_user.role = "admin"
                changed = True
            # Reset admin password to SHA-256(admin123) to avoid broken bcrypt backend
            admin_user.password_hash = hash_password("admin123")
            changed = True
            # Optional forced reset via environment for Render deployments
            reset_env = (os.getenv("RESET_ADMIN_PASSWORD", "0") or "0").lower()
            if reset_env in ("1", "true", "yes"):
                admin_user.password_hash = hash_password("admin123")
                changed = True
            if not admin_user.first_name:
                admin_user.first_name = "Admin"
                changed = True
            if not admin_user.last_name:
                admin_user.last_name = "User"
                changed = True
            if changed:
                db.commit()
                print("🔧 Admin user normalized (role/active/password reset to admin123).")
        
        # Create default test user Maxim
        maxim_user = db.query(models.User).filter(models.User.username == "Maxim").first()
        if not maxim_user:
            print("🚀 Creating default user: Maxim...")
            hashed_password = hashlib.sha256("123456".encode()).hexdigest()
            maxim_user = models.User(
                username="Maxim",
                password_hash=hashed_password,
                first_name="Maxim",
                last_name="User",
                role="user",
                is_active=True
            )
            db.add(maxim_user)
            db.commit()
            print("✅ User created: Maxim / 123456")
        
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
        
        # ⚡ Синхронизация статусов двигателей на основе Installation/Removal истории
        # Автоматически исправляет физическое состояние двигателя (aircraft_id, position, status)
        # в соответствии с последней операцией (Installation или Removal)
        try:
            print("🔄 Синхронизация статусов двигателей...")
            sync_result = _sync_engine_status_from_history(db)
            if sync_result["synced_count"] > 0:
                print(f"✅ Синхронизировано {sync_result['synced_count']} двигателей")
                for item in sync_result["changes"][:5]:  # Show first 5 changes
                    print(f"   • {item}")
            else:
                print("ℹ️  Все двигатели уже синхронизированы")
        except Exception as sync_e:
            print(f"⚠️ Ошибка синхронизации статусов: {sync_e}")
            
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

# Ensure 'from_location' column exists (auto-migrate lightweight for Render)
_column_checked = False

def ensure_from_location_column():
    global _column_checked
    if _column_checked:
        return
    try:
        with database.engine.connect() as conn:
            if database.IS_SQLITE:
                # Check from_location
                rows = conn.execute(text("PRAGMA table_info(engines);"))
                has_col = any(r[1] == 'from_location' for r in rows)
                if not has_col:
                    conn.execute(text("ALTER TABLE engines ADD COLUMN from_location VARCHAR"))
                
                # Check is_active in action_logs
                rows2 = conn.execute(text("PRAGMA table_info(action_logs);"))
                has_active = any(r[1] == 'is_active' for r in rows2)
                if not has_active:
                    conn.execute(text("ALTER TABLE action_logs ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                    # Умная логика: если есть REMOVE после INSTALL - помечаем INSTALL как неактивный
                    conn.execute(text("""
                        UPDATE action_logs SET is_active = 0 
                        WHERE action_type = 'INSTALL' 
                        AND EXISTS (
                            SELECT 1 FROM action_logs AS remove_log
                            WHERE remove_log.engine_id = action_logs.engine_id
                            AND remove_log.action_type = 'REMOVE'
                            AND remove_log.date > action_logs.date
                        )
                    """))
                    conn.execute(text("UPDATE action_logs SET is_active = 0 WHERE action_type != 'INSTALL'"))

                # Обнуляем aircraft_id для двигателей со статусом REMOVED
                conn.execute(text("UPDATE engines SET aircraft_id = NULL, position = NULL WHERE status = 'REMOVED'"))

                # Если последняя операция по двигателю REMOVE, снимаем его с борта (для старых данных)
                conn.execute(text("""
                    WITH last_action AS (
                        SELECT engine_id, MAX(date) AS maxd
                        FROM action_logs
                        GROUP BY engine_id
                    )
                    UPDATE engines
                    SET aircraft_id = NULL,
                        position = NULL,
                        status = 'REMOVED'
                    WHERE aircraft_id IS NOT NULL
                      AND id IN (
                        SELECT la.engine_id
                        FROM last_action la
                        JOIN action_logs a
                          ON a.engine_id = la.engine_id AND a.date = la.maxd
                        WHERE a.action_type = 'REMOVE'
                      );
                """))
            else:
                # Check from_location
                res = conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = 'engines' AND column_name = 'from_location'"))
                if res.scalar() is None:
                    conn.execute(text("ALTER TABLE engines ADD COLUMN from_location VARCHAR"))
                
                # Check is_active
                res2 = conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = 'action_logs' AND column_name = 'is_active'"))
                if res2.scalar() is None:
                    conn.execute(text("ALTER TABLE action_logs ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
                    # Умная логика: если есть REMOVE после INSTALL - помечаем INSTALL как неактивный
                    conn.execute(text("""
                        UPDATE action_logs SET is_active = FALSE 
                        WHERE action_type = 'INSTALL' 
                        AND EXISTS (
                            SELECT 1 FROM action_logs AS remove_log
                            WHERE remove_log.engine_id = action_logs.engine_id
                            AND remove_log.action_type = 'REMOVE'
                            AND remove_log.date > action_logs.date
                        )
                    """))
                    conn.execute(text("UPDATE action_logs SET is_active = FALSE WHERE action_type != 'INSTALL'"))
                
                # Обнуляем aircraft_id для двигателей со статусом REMOVED
                conn.execute(text("UPDATE engines SET aircraft_id = NULL, position = NULL WHERE status = 'REMOVED'"))

                # Если последняя операция по двигателю REMOVE, снимаем его с борта (для старых данных)
                conn.execute(text("""
                    WITH last_action AS (
                        SELECT engine_id, MAX(date) AS maxd
                        FROM action_logs
                        GROUP BY engine_id
                    )
                    UPDATE engines
                    SET aircraft_id = NULL,
                        position = NULL,
                        status = 'REMOVED'
                    WHERE aircraft_id IS NOT NULL
                      AND id IN (
                        SELECT la.engine_id
                        FROM last_action la
                        JOIN action_logs a
                          ON a.engine_id = la.engine_id AND a.date = la.maxd
                        WHERE a.action_type = 'REMOVE'
                      );
                """))
            conn.commit()
        _column_checked = True
    except Exception as e:
        print(f"⚠️ Failed to ensure columns: {e}")

# Dependency (получение сессии БД)
def get_db():
    ensure_from_location_column()
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Diagnostics API ---
@app.get("/api/_diag/db")
def diag_db(db: Session = Depends(get_db)):
    """Lightweight DB diagnostics to verify which database is active.

    Returns safe details only (no passwords):
    - backend database driver (sqlite/postgresql)
    - database host (masked)
    - key table counts
    """
    try:
        url = str(database.DATABASE_URL)
        is_sqlite = database.IS_SQLITE
        # mask credentials if present
        masked = url
        if "@" in url:
            try:
                prefix, host = url.split("@", 1)
                # keep scheme and username only
                scheme = prefix.split("://", 1)[0]
                user = prefix.split("://", 1)[1].split(":", 1)[0]
                masked = f"{scheme}://{user}:***@{host}"
            except Exception:
                masked = url

        counts = {
            "engines": db.query(models.Engine).count(),
            "users": db.query(models.User).count(),
            "action_logs": db.query(models.ActionLog).count(),
        }
        return {
            "driver": "sqlite" if is_sqlite else "postgresql",
            "database_url": masked,
            "counts": counts,
        }
    except Exception as e:
        raise HTTPException(500, f"diag failed: {e}")



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
    ac_ttsn: Optional[float] = None
    ac_tcsn: Optional[int] = None
    remarks: Optional[str] = ""
    supplier: Optional[str] = None  # Поставщик
    current_sn: Optional[str] = None  # Current SN при установке


class ShipmentSchema(BaseModel):
    date: str
    engine_id: int
    engine_model: Optional[str] = None
    gss_id: Optional[str] = None
    to_location_id: int  # Куда отправляем (ID локации)
    waybill: Optional[str] = "" # Номер накладной
    remarks: Optional[str] = ""

class RemoveSchema(BaseModel):
    date: str
    engine_id: int
    to_location_id: int # Куда положили снятый двигатель
    condition_1: Optional[str] = "SV"  # Техсостояние при снятии
    reason: Optional[str] = ""
    ttsn: Optional[float] = None
    tcsn: Optional[int] = None
    ttsn_ac: Optional[float] = None
    tcsn_ac: Optional[int] = None
    remarks: Optional[str] = ""


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
    from_esn: Optional[str] = None
    to_esn: Optional[str] = None
    location: Optional[str] = None
    reason: Optional[str] = None


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
    work_type: str = 'All Engine'
    gss_id: Optional[str] = ""
    inspector: str
    comment: Optional[str] = ""
    link: Optional[str] = ""
    inspection_report: Optional[dict] = None  # Данные фото и другие отчеты

# ============================================
# GSS ASSIGNMENT SCHEMAS
# ============================================
class GSSAssignmentCreate(BaseModel):
    gss_id: int
    engine_id: int
    current_sn: Optional[str] = None
    photo_url: Optional[str] = None
    remarks: Optional[str] = None

class GSSAssignmentUpdate(BaseModel):
    current_sn: Optional[str] = None
    photo_url: Optional[str] = None
    remarks: Optional[str] = None

class GSSAssignmentResponse(BaseModel):
    id: int
    gss_id: int
    engine_id: int
    original_sn: str
    current_sn: Optional[str]
    photo_url: Optional[str]
    photo_filename: Optional[str]
    remarks: Optional[str]
    assigned_by: int
    assigned_by_name: str
    assigned_date: datetime
    engine_model: Optional[str]
    engine_location: Optional[str]
    
    class Config:
        from_attributes = True

class GSSRangeItem(BaseModel):
    gss_id: int
    is_assigned: bool
    engine_info: Optional[dict] = None

class BoroscopeScheduleCreateSchema(BaseModel):
    """Schema для создания запланированного боroскопа"""
    date: str  # YYYY-MM-DD format
    aircraft_tail_number: str  # ER-BAT, ER-BAR, ER-BAQ
    position: int  # 1, 2, 3, 4
    inspector: str
    remarks: Optional[str] = None
    location: Optional[str] = None

class BoroscopeScheduleUpdateSchema(BaseModel):
    """Schema для обновления запланированного боroскопа"""
    date: Optional[str] = None
    position: Optional[int] = None
    inspector: Optional[str] = None
    remarks: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None  # Scheduled, Completed, Cancelled

class BoroscopeScheduleResponseSchema(BaseModel):
    """Schema для возврата запланированного боroскопа"""
    id: int
    date: str
    aircraft_tail_number: str
    position: int
    inspector: str
    remarks: Optional[str] = None
    location: Optional[str] = None
    status: str
    created_at: str
    completed_at: Optional[str] = None
    
    class Config:
        from_attributes = True

class PurchaseOrderSchema(BaseModel):
    date: str
    name: str
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    price: Optional[float] = None
    purpose: str
    aircraft: str
    ro_number: str
    link: Optional[str] = ""


class ScheduledEventSchema(BaseModel):
    """Schema for scheduled events in calendar"""
    event_date: str  # YYYY-MM-DD
    event_time: Optional[str] = None  # HH:MM
    event_type: str  # SHIPMENT, MEETING, INSPECTION, MAINTENANCE, DEADLINE, OTHER
    title: str
    description: Optional[str] = None
    engine_id: Optional[int] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    status: Optional[str] = "PLANNED"  # PLANNED, IN_PROGRESS, COMPLETED, CANCELLED
    priority: Optional[str] = "MEDIUM"  # LOW, MEDIUM, HIGH, URGENT
    color: Optional[str] = "#3788d8"
    created_by: Optional[str] = None


class LogisticsShipmentSchema(BaseModel):
    """Schema for Logistics & Schedules tracking (shipments in transit)"""
    shipment_type: str  # ENGINE, PARTS
    status: Optional[str] = "PLANNED"  # PLANNED, IN_TRANSIT, DELIVERED, DELAYED, CANCELLED
    
    # For ENGINE type
    engine_id: Optional[int] = None
    destination_location: Optional[str] = None
    
    # For PARTS type
    part_name: Optional[str] = None
    part_category: Optional[str] = None
    part_quantity: Optional[int] = None
    reserved_quantity: Optional[int] = 0
    
    # Shipping and delivery
    departure_date: Optional[str] = None  # ISO datetime string
    expected_delivery_date: str  # ISO datetime string (required)
    actual_delivery_date: Optional[str] = None
    
    # Tracking
    supplier_name: Optional[str] = None
    tracking_number: Optional[str] = None
    notes: Optional[str] = None
    
    # User metadata
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


class CustomColumnSchema(BaseModel):
    column_label: str
    column_order: Optional[int] = 0


class CustomColumnUpdateSchema(BaseModel):
    column_label: str


class UtilizationParameterSchema(BaseModel):
    """Schema for Utilization Parameters"""
    date: str
    aircraft: str
    position: int  # Позиция двигателя (1-4) обязательна
    ttsn: float
    tcsn: int
    period: bool = True  # Теперь всегда True по умолчанию
    date_from: str  # Обязательная дата начала периода
    date_to: str  # Обязательная дата конца периода


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


class LocationCreateSchema(BaseModel):
    """Schema for creating a new location"""
    name: str
    city: str


# === UTILITY FUNCTIONS FOR AUTH ===

# Initialize password context for bcrypt (kept for compatibility if hashes exist)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash password using SHA-256 (bcrypt backend is currently broken in env)."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password; prefer SHA-256, fallback to bcrypt if hash isn't SHA."""
    if not hashed_password:
        return False
    # If looks like SHA-256 hex, check directly (avoids broken bcrypt backend)
    if len(hashed_password) == 64:
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def resolve_actor_name(db: Session, user_id: Optional[int], fallback: str = "User") -> str:
    """Resolve actor username by id with graceful fallback."""
    if not user_id:
        return fallback
    user_obj = db.query(models.User).filter(models.User.id == user_id).first()
    return user_obj.username if user_obj and user_obj.username else fallback


def create_notification(db: Session, action_type: str, entity_type: str, 
                       entity_id: int, message: str, performed_by: str,
                       user_id: Optional[int] = None,
                       performed_by_user_id: Optional[int] = None):
    """Create notification for admins (performed_by_user_id overrides performed_by)."""
    # Support dict messages by encoding to JSON for rich details
    if isinstance(message, (dict, list)):
        try:
            message = json.dumps(message, ensure_ascii=False)
        except Exception:
            message = str(message)
    actor_name = performed_by
    if performed_by_user_id is not None:
        actor_name = resolve_actor_name(db, performed_by_user_id, performed_by)
    notification = models.Notification(
        user_id=user_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        message=message,
        performed_by=actor_name,
        is_read=False
    )
    db.add(notification)
    db.commit()


# --- API (GET DATA) ---

@app.get("/api/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    try:
        return {
            "SV": db.query(models.Engine).filter(models.Engine.condition_1 == "SV").count(),
            "US": db.query(models.Engine).filter(models.Engine.condition_1 == "US").count(),
            "SCRAP": db.query(models.Engine).filter(models.Engine.condition_1 == "Scrap").count(),
            "INSTALLED": db.query(models.Engine).filter(models.Engine.status == "INSTALLED").count(),
            "REMOVED": db.query(models.Engine).filter(models.Engine.status == "REMOVED").count()
        }
    except Exception as e:
        print(f"❌ Error in get_dashboard_stats: {e}")
        return {
            "SV": 0,
            "US": 0,
            "SCRAP": 0,
            "INSTALLED": 0,
            "REMOVED": 0
        }

# Condition 2 breakdown for US/REMOVED cards
@app.get("/api/dashboard/condition2")
def get_condition2_breakdown(base: str, db: Session = Depends(get_db)):
    try:
        if base == "US":
            q = db.query(models.Engine).filter(models.Engine.condition_1 == "US")
        elif base == "REMOVED":
            q = db.query(models.Engine).filter(models.Engine.status == "REMOVED")
        elif base == "SCRAP":
            q = db.query(models.Engine).filter(models.Engine.condition_1 == "Scrap")
        else:
            return {}
        engines = q.all()
        stats = {}
        for e in engines:
            key = (e.condition_2 or "-")
            stats[key] = stats.get(key, 0) + 1
        return stats
    except Exception as e:
        print(f"❌ Error in get_condition2_breakdown: {e}")
        return {}

@app.get("/api/locations")
def get_locations_overview(db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        print(f"❌ Error in get_locations_overview: {e}")
        return []

@app.post("/api/locations")
def create_location(data: LocationCreateSchema, user_id: int = Query(...), db: Session = Depends(get_db)):
    """Create new location (admin only)"""
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user or user.role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can create locations")
        
        name = data.name.upper()
        city = data.city.strip()
        
        if not name or not city:
            raise HTTPException(status_code=400, detail="Name and city are required")
        
        # Check if location already exists
        existing = db.query(models.Location).filter(models.Location.name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Location {name} already exists")
        
        # Create new location
        new_location = models.Location(name=name, city=city)
        db.add(new_location)
        db.commit()
        db.refresh(new_location)
        
        print(f"✅ Location created: {name} ({city})")
        return {
            "id": new_location.id,
            "name": new_location.name,
            "city": new_location.city,
            "message": f"Location {name} created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error creating location: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating location: {e}")

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
    try:
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
    except Exception as e:
        print(f"❌ Error in get_fleet_status: {e}")
        return []

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
    total_time: Optional[float] = None
    total_cycles: Optional[int] = None

@app.post("/api/aircrafts")
def create_aircraft(data: AircraftCreateSchema, current_user_id: int = Query(..., alias="user_id"), db: Session = Depends(get_db)):
    """Create new aircraft"""
    user = db.query(models.User).filter(models.User.id == current_user_id).first()
    if not user or user.role != "admin":
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
    if data.total_time is not None:
        aircraft.total_time = data.total_time
    if data.total_cycles is not None:
        aircraft.total_cycles = data.total_cycles
    
    db.commit()
    db.refresh(aircraft)
    
    return {
        "message": "Aircraft updated successfully",
        "id": aircraft.id,
        "tail_number": aircraft.tail_number,
        "total_time": aircraft.total_time,
        "total_cycles": aircraft.total_cycles
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
    try:
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
    except Exception as e:
        print(f"❌ Error in get_recent_actions: {e}")
        return []

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
        cutoff = datetime.now(timezone.utc) - timedelta(days=ranges[range_key])
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
    try:
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

            # Все двигатели на самолете (берем самый свежий на позицию, чтобы не показывать старый)
            engines_on_wing = db.query(models.Engine).filter(
                models.Engine.aircraft_id == ac.id,
                models.Engine.aircraft_id != None,
                models.Engine.status == "INSTALLED"
            ).order_by(
                models.Engine.install_date.desc().nullslast(),
                models.Engine.id.desc()
            ).all()
            
            # Создаем 4 позиции (1, 2, 3, 4)
            positions = {}
            for pos in [1, 2, 3, 4]:
                positions[pos] = None
                
            # Заполняем реальными двигателями
            for eng in engines_on_wing:
                if eng.position and 1 <= eng.position <= 4:
                    # Если на позицию уже поставили более свежий двигатель, пропускаем старые записи
                    if positions.get(eng.position):
                        continue
                    # Вычисляем налет на конкретном самолете по согласованной логике
                    tsn_on_aircraft = 0.0
                    csn_on_aircraft = 0
                    
                    # Находим последнюю запись INSTALL для этого двигателя
                    last_install = db.query(models.ActionLog).filter(
                        models.ActionLog.engine_id == eng.id,
                        models.ActionLog.action_type == "INSTALL"
                    ).order_by(models.ActionLog.date.desc()).first()
                    
                    if last_install:
                        # Текущий налёт самолёта
                        current_ac_ttsn = ac.total_time or 0.0
                        current_ac_tcsn = ac.total_cycles or 0
                        
                        # Налёт самолёта на момент установки хранится в строковых полях block_time_str/block_in_str
                        def _to_float(v):
                            try:
                                return float(v) if v is not None and str(v).strip() != "" else 0.0
                            except Exception:
                                return 0.0
                        def _to_int(v):
                            try:
                                return int(v) if v is not None and str(v).strip() != "" else 0
                            except Exception:
                                return 0
                        ac_ttsn_at_install = _to_float(getattr(last_install, "block_time_str", None))
                        ac_tcsn_at_install = _to_int(getattr(last_install, "block_in_str", None))
                        
                        # Налёт двигателя на момент установки берём из snapshot_tt/snapshot_tc
                        engine_tsn_at_install = last_install.snapshot_tt or 0.0
                        engine_csn_at_install = last_install.snapshot_tc or 0
                        
                        tsn_on_aircraft = current_ac_ttsn - ac_ttsn_at_install - engine_tsn_at_install
                        csn_on_aircraft = current_ac_tcsn - ac_tcsn_at_install - engine_csn_at_install
                        
                        # Защита от отрицательных значений
                        if tsn_on_aircraft < 0:
                            tsn_on_aircraft = 0.0
                        if csn_on_aircraft < 0:
                            csn_on_aircraft = 0
                    
                    # Находим последнюю запись ATLB для определения даты обновления
                    last_atlb = db.query(models.ActionLog).filter(
                        models.ActionLog.action_type == "FLIGHT"
                    ).order_by(models.ActionLog.date.desc()).first()
                    
                    last_update = last_atlb.date.strftime("%Y-%m-%d %H:%M") if last_atlb else "N/A"
                    
                    supplier = last_install.supplier if last_install and last_install.supplier else None
                    
                    # Находим последнюю периодическую запись для этой позиции
                    util_param = db.query(models.UtilizationParameter).filter(
                        models.UtilizationParameter.aircraft == ac.tail_number,
                        models.UtilizationParameter.position == eng.position,
                        models.UtilizationParameter.period == True
                    ).order_by(
                        models.UtilizationParameter.created_at.desc(),
                        models.UtilizationParameter.date.desc(),
                        models.UtilizationParameter.id.desc()
                    ).first()
                    
                    # Данные периода для этой позиции
                    position_util_ttsn = util_param.ttsn if util_param else None
                    position_util_tcsn = util_param.tcsn if util_param else None
                    position_date_from = util_param.date_from.strftime("%Y-%m-%d") if util_param and util_param.date_from else None
                    position_date_to = util_param.date_to.strftime("%Y-%m-%d") if util_param and util_param.date_to else None
                    
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
                        "supplier": supplier,
                        "param_date": eng.last_param_update.strftime("%d.%m.%Y") if eng.last_param_update else None,
                        # Данные периода для этой конкретной позиции
                        "util_ttsn": position_util_ttsn,
                        "util_tcsn": position_util_tcsn,
                        "util_date_from": position_date_from,
                        "util_date_to": position_date_to
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
    except Exception as e:
        print(f"❌ Error in get_aircraft_dashboard_details: {e}")
        return []


@app.get("/api/aircraft/{tail_number}")
def get_aircraft_by_tail_number(tail_number: str, db: Session = Depends(get_db)):
    """Get aircraft details with engines for a specific aircraft"""
    try:
        ac = db.query(models.Aircraft).filter(
            models.Aircraft.tail_number == tail_number
        ).first()
        
        if not ac:
            return {"error": "Aircraft not found"}, 404
        
        # Get all installed engines
        engines_on_wing = db.query(models.Engine).filter(
            models.Engine.aircraft_id == ac.id,
            models.Engine.status == "INSTALLED"
        ).all()
        
        # Create 4 positions (1, 2, 3, 4)
        positions = {}
        for pos in [1, 2, 3, 4]:
            positions[pos] = None
        
        # Fill with real engines
        for eng in engines_on_wing:
            if eng.position and 1 <= eng.position <= 4:
                positions[eng.position] = {
                    "engine_id": eng.id,
                    "position": eng.position,
                    "original_sn": eng.original_sn,
                    "gss_sn": eng.gss_sn or eng.original_sn,
                    "current_sn": eng.current_sn,
                    "model": eng.model,
                    "total_time": round(eng.total_time, 1) if eng.total_time else 0.0,
                    "total_cycles": eng.total_cycles or 0,
                    "status": eng.status
                }
        
        return {
            "aircraft_id": ac.id,
            "tail_number": ac.tail_number,
            "model": ac.model,
            "engines": [
                positions[1],
                positions[2],
                positions[3],
                positions[4]
            ]
        }
    except Exception as e:
        print(f"❌ Error in get_aircraft_by_tail_number: {e}")
        return {"error": str(e)}, 500

@app.get("/api/aircraft/{aircraft_id}/engines")
def get_aircraft_engines(aircraft_id: int, db: Session = Depends(get_db)):
    """Get detailed engine information for a specific aircraft by ID"""
    try:
        # Get aircraft
        aircraft = db.query(models.Aircraft).filter(
            models.Aircraft.id == aircraft_id
        ).first()
        
        if not aircraft:
            raise HTTPException(status_code=404, detail="Aircraft not found")
        
        # Get all installed engines for this aircraft
        engines_on_wing = db.query(models.Engine).filter(
            models.Engine.aircraft_id == aircraft.id,
            models.Engine.status == "INSTALLED"
        ).order_by(models.Engine.position).all()
        
        # Create 4 positions (ENG 1-4)
        engine_positions = []
        for pos in [1, 2, 3, 4]:
            # Find engine at this position
            engine = next((e for e in engines_on_wing if e.position == pos), None)
            
            if engine:
                # Get latest borescope inspection (safely)
                latest_borescope = None
                try:
                    latest_borescope = db.query(models.BoroscopeSchedule).filter(
                        models.BoroscopeSchedule.engine_id == engine.id
                    ).order_by(models.BoroscopeSchedule.inspection_date.desc()).first()
                except:
                    pass
                
                # Get GSS assignment (safely)
                gss_assignment = None
                try:
                    gss_assignment = db.query(models.GSSAssignment).filter(
                        models.GSSAssignment.original_sn == engine.original_sn
                    ).first()
                except:
                    pass
                
                # Calculate utilization from install snapshot
                utilization = None
                if engine.total_time is not None and engine.tsn_at_install is not None:
                    utilization = round(engine.total_time - engine.tsn_at_install, 1)
                
                engine_positions.append({
                    "position": f"ENG {pos}",
                    "engine_id": engine.id,
                    "original_sn": engine.original_sn or "N/A",
                    "current_sn": engine.current_sn or engine.original_sn or "N/A",
                    "gss_id": gss_assignment.gss_sn if gss_assignment else None,
                    "model": engine.model or "N/A",
                    "total_time": round(engine.total_time, 1) if engine.total_time else 0.0,
                    "total_cycles": engine.total_cycles or 0,
                    "utilization": f"{utilization} hrs" if utilization else "N/A",
                    "install_date": engine.install_date.strftime("%Y-%m-%d") if engine.install_date else "N/A",
                    "supplier": "N/A",
                    "last_borescope": latest_borescope.inspection_date.strftime("%Y-%m-%d") if latest_borescope else "N/A",
                    "status": engine.status
                })
            else:
                # Empty position
                engine_positions.append({
                    "position": f"ENG {pos} ({'L' if pos in [1, 3] else 'R'})",
                    "engine_id": None,
                    "original_sn": None,
                    "current_sn": None,
                    "gss_id": None,
                    "model": None,
                    "total_time": 0,
                    "total_cycles": 0,
                    "utilization": "N/A",
                    "install_date": "N/A",
                    "supplier": None,
                    "last_borescope": "N/A",
                    "status": "EMPTY"
                })
        
        return {
            "aircraft_id": aircraft.id,
            "tail_number": aircraft.tail_number,
            "model": aircraft.model,
            "engines": engine_positions
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in get_aircraft_engines: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/aircraft/{tail_number}")
def update_aircraft_by_tail_number(tail_number: str, data: AircraftUpdateSchema, db: Session = Depends(get_db)):
    """Update aircraft by tail_number - PATCH"""
    aircraft = db.query(models.Aircraft).filter(models.Aircraft.tail_number == tail_number).first()
    
    if not aircraft:
        raise HTTPException(status_code=404, detail=f"Aircraft {tail_number} not found")
    
    if data.tail_number:
        aircraft.tail_number = data.tail_number
    if data.model:
        aircraft.model = data.model
    if data.msn:
        aircraft.msn = data.msn
    if data.total_time is not None:
        aircraft.total_time = data.total_time
    if data.total_cycles is not None:
        aircraft.total_cycles = data.total_cycles
    
    db.commit()
    db.refresh(aircraft)
    
    return {
        "message": "Aircraft updated successfully",
        "tail_number": aircraft.tail_number,
        "total_time": aircraft.total_time,
        "total_cycles": aircraft.total_cycles
    }

# ===== AIRCRAFT UTILIZATION HISTORY =====
class AircraftUtilizationSchema(BaseModel):
    aircraft: str  # tail_number
    date: str
    total_time: float
    total_cycles: int

@app.post("/api/aircraft-utilization")
def save_aircraft_utilization(data: AircraftUtilizationSchema, db: Session = Depends(get_db)):
    """Save aircraft total time/cycles and update aircraft record"""
    try:
        # Find aircraft by tail_number
        aircraft = db.query(models.Aircraft).filter(
            models.Aircraft.tail_number == data.aircraft
        ).first()
        
        if not aircraft:
            raise HTTPException(status_code=404, detail=f"Aircraft {data.aircraft} not found")
        
        # Parse date
        parsed_date = parse_input_date(data.date)
        if not parsed_date:
            parsed_date = datetime.now(timezone.utc)
        
        # Update aircraft totals
        aircraft.total_time = data.total_time
        aircraft.total_cycles = data.total_cycles
        
        # Save to history
        history = models.AircraftUtilizationHistory(
            aircraft_id=aircraft.id,
            date=parsed_date,
            total_time=data.total_time,
            total_cycles=data.total_cycles
        )
        
        db.add(history)
        db.commit()
        db.refresh(history)
        
        return {
            "message": "Aircraft utilization saved successfully",
            "id": history.id,
            "aircraft": aircraft.tail_number,
            "total_time": aircraft.total_time,
            "total_cycles": aircraft.total_cycles
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/aircraft-utilization-history")
def get_aircraft_utilization_history(aircraft: str = None, db: Session = Depends(get_db)):
    """Get aircraft utilization history"""
    try:
        query = db.query(models.AircraftUtilizationHistory)
        
        if aircraft:
            query = query.join(models.Aircraft).filter(
                models.Aircraft.tail_number == aircraft
            )
        
        records = query.order_by(models.AircraftUtilizationHistory.date.desc()).all()
        
        result = []
        for record in records:
            result.append({
                "id": record.id,
                "aircraft_id": record.aircraft_id,
                "aircraft": record.aircraft.tail_number if record.aircraft else "N/A",
                "aircraft_tail_number": record.aircraft.tail_number if record.aircraft else "N/A",
                "date": record.date.isoformat() if record.date else None,
                "total_time": record.total_time,
                "total_cycles": record.total_cycles,
                "created_at": record.created_at.isoformat() if record.created_at else None
            })
        
        return result
    except Exception as e:
        print(f"Error getting aircraft utilization history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- ВОТ ИСПРАВЛЕННАЯ ФУНКЦИЯ (ПОКАЗЫВАЕТ ВСЕ ДВИГАТЕЛИ) ---
@app.get("/api/engines")
def get_all_engines(status: str = None, condition2: str = None, db: Session = Depends(get_db)):
    try:
        # 1. Запрашиваем ВСЕ двигатели из базы
        query = db.query(models.Engine)
        if status:
            # SV/US/SCRAP фильтруем по condition_1, остальные по status
            if status in ["SV", "US", "SCRAP", "Scrap"]:
                normalized = "Scrap" if status in ("SCRAP", "Scrap") else status
                query = query.filter(models.Engine.condition_1 == normalized)
            else:
                query = query.filter(models.Engine.status == status)
        if condition2:
            query = query.filter(models.Engine.condition_2 == condition2)
        
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

            # 2.1 Дата установки: если пусто, берем первую дату из истории двигателя
            display_date = eng.install_date
            if not display_date and eng.logs:
                try:
                    log_dates = [log.date for log in eng.logs if getattr(log, "date", None)]
                    if log_dates:
                        display_date = sorted(log_dates)[0]
                except Exception:
                    display_date = None

            # 3. Собираем данные, заменяя пустые (None) на текст или нули
            # 3.1 Если двигатель установлен, добавляем данные о самолете
            ac_ttsn = None
            ac_tcsn = None
            if eng.aircraft:
                ac_ttsn = eng.aircraft.total_time if eng.aircraft.total_time is not None else None
                ac_tcsn = eng.aircraft.total_cycles if eng.aircraft.total_cycles is not None else None
            
            result.append({
                "id": eng.id,
                "original_sn": eng.original_sn or "Нет данных",
                "gss_sn": eng.gss_sn if eng.gss_sn else "-",
                "current_sn": eng.current_sn if eng.current_sn else "-",
                "model": eng.model or "-",
                "status": eng.status,
                "location": loc_name,
                "location_id": eng.location_id,
                "tt": eng.total_time if eng.total_time is not None else 0,
                "tc": eng.total_cycles if eng.total_cycles is not None else 0,
                "price": getattr(eng, "price", None),
                "aircraft_id": eng.aircraft_id,
                "aircraft": eng.aircraft.tail_number if eng.aircraft else None,
                "position": eng.position,
                "photo_url": eng.photo_url,
                "remarks": eng.remarks or "",
                # Separate: current location vs moved-from vs removed-from
                "from_location": eng.from_location or "",
                "removed_from": eng.removed_from or "",
                "install_date": display_date.strftime('%Y-%m-%d') if display_date else None,
                "ac_ttsn": ac_ttsn,
                "ac_tcsn": ac_tcsn,
                "condition_1": eng.condition_1 or "SV",
                "condition_2": eng.condition_2 or "New"
            })
        
        return result
    except Exception as e:
        print(f"❌ Error in get_all_engines: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Error loading engines: {str(e)}")

# --- API (ACTIONS & HISTORY) ---

# СОЗДАНИЕ НОВОГО ДВИГАТЕЛЯ
class EngineCreateSchema(BaseModel):
    date: Optional[str] = None
    original_sn: str
    gss_sn: Optional[str] = None
    current_sn: str
    model: Optional[str] = None
    status: Optional[str] = ""
    condition_1: str = "SV"
    condition_2: str = "New"
    location_id: Optional[int] = None
    total_time: float = 0.0
    total_cycles: int = 0
    price: Optional[float] = None
    photo_url: Optional[str] = None
    remarks: Optional[str] = None
    from_location: Optional[str] = None
    removed_from: Optional[str] = None

@app.post("/api/engines")
def create_engine(data: EngineCreateSchema, current_user_id: int = Query(..., alias="user_id"), db: Session = Depends(get_db)):
    try:
        user = db.query(models.User).filter(models.User.id == current_user_id).first()
        if not user or user.role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can create engines")
        actor_name = resolve_actor_name(db, current_user_id, "Admin")
        
        # Проверяем, существует ли уже двигатель с таким original_sn
        existing = db.query(models.Engine).filter(models.Engine.original_sn == data.original_sn).first()
        if existing:
            raise HTTPException(400, f"Engine with ESN {data.original_sn} already exists")
        
        # Парсим дату если передана
        install_date = None
        if data.date and data.date.strip():
            try:
                # Пробуем разные форматы
                date_str = data.date.strip()
                if 'T' in date_str:  # ISO формат с временем
                    install_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:  # Простой формат YYYY-MM-DD
                    install_date = datetime.strptime(date_str, '%Y-%m-%d')
            except Exception as e:
                print(f"[create_engine] date parse error for '{data.date}': {e}")
                print(f"[create_engine] Skipping date, will use None")
                install_date = None
        
        # Создаем новый двигатель
        new_engine = models.Engine(
            original_sn=data.original_sn,
            gss_sn=data.gss_sn or data.original_sn,
            current_sn=data.current_sn,
            model=data.model,
            status=(data.status if data.status and data.status.strip() and data.status in ["INSTALLED", "REMOVED", "-"] else "-"),
            condition_1=data.condition_1 if data.condition_1 and data.condition_1.strip() and data.condition_1 != '-' else "SV",
            condition_2=data.condition_2 if data.condition_2 and data.condition_2.strip() and data.condition_2 != '-' else "New",
            location_id=data.location_id,
            total_time=data.total_time or 0.0,
            total_cycles=data.total_cycles or 0,
            price=data.price,
            photo_url=data.photo_url,
            remarks=data.remarks,
            from_location=data.from_location,
            removed_from=data.removed_from,
            install_date=install_date
        )
        
        db.add(new_engine)
        db.commit()
        db.refresh(new_engine)
        
        # Создаем только notification для Recent Actions (БЕЗ ActionLog - это не действие, а просто добавление записи)
        location = db.query(models.Location).filter(models.Location.id == data.location_id).first()
        loc_name = location.name if location else "Unknown"
        
        create_notification(db, 
                           action_type="created",
                           entity_type="engine",
                           entity_id=new_engine.id,
                           message=f"Был добавлен новый двигатель {new_engine.current_sn} (ESN: {new_engine.original_sn}) в локацию {loc_name} пользователем {actor_name}",
                           performed_by=actor_name,
                           performed_by_user_id=current_user_id)
        
        return {"message": "Engine created successfully", "id": new_engine.id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        print(f"❌ Error in create_engine: {e}")
        print(f"❌ Traceback: {traceback.format_exc()}")
        print(f"❌ Data received: original_sn={data.original_sn}, location_id={data.location_id}, status={data.status}")
        raise HTTPException(status_code=500, detail=f"Failed to create engine: {str(e)}")

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
    try:
        # Находим двигатель
        engine = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
        if not engine:
            raise HTTPException(404, "Engine not found")
        
        # Парсим дату если передана
        install_date = None
        if data.date and data.date.strip():
            try:
                # Пробуем разные форматы
                date_str = data.date.strip()
                if 'T' in date_str:  # ISO формат с временем
                    install_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:  # Простой формат YYYY-MM-DD
                    install_date = datetime.strptime(date_str, '%Y-%m-%d')
            except Exception as e:
                print(f"[update_engine] date parse error for '{data.date}': {e}")
                install_date = None
        
        # Обновляем поля
        engine.original_sn = data.original_sn
        engine.model = data.model
        engine.gss_sn = data.gss_sn or data.original_sn
        engine.current_sn = data.current_sn
        engine.condition_1 = data.condition_1 if data.condition_1 and data.condition_1.strip() and data.condition_1 != '-' else "SV"
        engine.condition_2 = data.condition_2 if data.condition_2 and data.condition_2.strip() and data.condition_2 != '-' else "New"
        
        # НЕ меняем status и location если двигатель в "системном" статусе (INSTALLED, REMOVED, REPAIRED)
        protected_statuses = ["INSTALLED", "REMOVED", "REPAIRED"]
        if engine.status not in protected_statuses:
            # Разрешаем только INSTALLED/REMOVED/'-'. Любые другие значения маппим на '-'.
            status_value = data.status if data.status and data.status.strip() else "-"
            allowed_statuses = ["INSTALLED", "REMOVED", "-"]
            engine.status = status_value if status_value in allowed_statuses else "-"
            if data.location_id:
                engine.location_id = data.location_id
        engine.total_time = data.total_time
        engine.total_cycles = data.total_cycles
        engine.price = data.price
        engine.photo_url = data.photo_url
        engine.remarks = data.remarks
        engine.from_location = data.from_location
        engine.removed_from = data.removed_from
        engine.install_date = install_date
        
        db.commit()
        db.refresh(engine)
        
        return {"message": "Engine updated successfully", "id": engine.id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error updating engine {engine_id}: {e}")
        import traceback
        print(traceback.format_exc())
        raise HTTPException(500, f"Failed to update engine: {str(e)}")

# ПОЛУЧЕНИЕ ОДНОГО ДВИГАТЕЛЯ ПО ID
@app.get("/api/engines/{engine_id}")
def get_engine_by_id(engine_id: int, db: Session = Depends(get_db)):
    engine = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
    if not engine:
        raise HTTPException(404, "Engine not found")
    
    loc_name = "Unknown"
    try:
        if engine.location:
            loc_name = engine.location.name
        elif engine.aircraft:
            tail = engine.aircraft.tail_number if engine.aircraft.tail_number else "No Tail"
            loc_name = f"{tail} (Pos {engine.position})"
    except Exception:
        loc_name = "Data Error"
    
    return {
        "id": engine.id,
        "original_sn": engine.original_sn or "N/A",
        "gss_sn": engine.gss_sn or engine.original_sn,
        "current_sn": engine.current_sn or "N/A",
        "model": engine.model or "-",
        "status": engine.status,
        "location": loc_name,
        "location_id": engine.location_id,
        "tt": engine.total_time if engine.total_time is not None else 0,
        "tc": engine.total_cycles if engine.total_cycles is not None else 0,
        "aircraft_id": engine.aircraft_id,
        "aircraft": engine.aircraft.tail_number if engine.aircraft else None,
        "position": engine.position,
        "photo_url": engine.photo_url,
        "remarks": engine.remarks or "",
        "from_location": engine.from_location or "",
        "removed_from": engine.removed_from or "",
        "install_date": engine.install_date.strftime('%Y-%m-%d') if engine.install_date else None,
        "condition_1": engine.condition_1 or "SV",
        "condition_2": engine.condition_2 or "New"
    }

# ПОЛУЧЕНИЕ ПОЛНОЙ ИСТОРИИ ДВИГАТЕЛЯ
@app.get("/api/engines/{engine_id}/history")
def get_engine_history(engine_id: int, db: Session = Depends(get_db)):
    engine = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
    if not engine:
        raise HTTPException(404, "Engine not found")
    
    # Получаем все логи действий для данного двигателя (сортируем от старых к новым - хронологически)
    # Фильтруем только реальные действия из ACTIONS (не utilization, parameters и т.д.)
    logs = db.query(models.ActionLog).filter(
        models.ActionLog.engine_id == engine_id,
        models.ActionLog.action_type.in_(["INSTALL", "REMOVE", "SHIP", "REPAIR"])
    ).order_by(models.ActionLog.date.asc()).all()  # ASC для хронологического порядка (старые сверху)
    
    result = []
    for log in logs:
        try:
            # Базовые поля
            event = {
                "id": log.id,
                "date": log.date.strftime('%Y-%m-%d') if log.date else "N/A",
                "action_type": log.action_type,
                "engine_original_sn": engine.original_sn,
                "engine_current_sn": engine.current_sn,
                "remarks": log.comments or ""
            }
            
            # Специфичные поля для разных типов действий
            if log.action_type == "INSTALL":
                event.update({
                    "install_to": log.to_aircraft,
                    "position": log.position,
                    "location_from": log.from_location,
                    "tt": log.snapshot_tt or 0,
                    "tc": log.snapshot_tc or 0
                })
            elif log.action_type == "REMOVE":
                event.update({
                    "aircraft": log.from_location,
                    "destination": log.to_location,
                    "tt": log.snapshot_tt or 0,
                    "tc": log.snapshot_tc or 0
                })
            elif log.action_type == "REPAIR":
                event.update({
                    "station": log.from_location,
                    "defect": log.to_location,
                    "correction": log.to_aircraft
                })
            elif log.action_type == "SHIP":
                event.update({
                    "aircraft": log.from_location,
                    "destination": log.to_location,
                    "tt": log.snapshot_tt or 0,
                    "tc": log.snapshot_tc or 0
                })
            
            result.append(event)
        except Exception as e:
            print(f"[engine_history] skip log {getattr(log,'id',None)} due to error: {e}")
            continue
    
    # Также получаем все parts которые установлены на этом двигателе
    parts = db.query(models.Part).filter(models.Part.engine_id == engine_id).all()
    for part in parts:
        if part.id:  # Только если part имеет ID (установлен)
            part_event = {
                "id": f"part_{part.id}",
                "date": "N/A",  # Parts не имеют даты установки в отдельном поле
                "action_type": "PART_INSTALLED",
                "engine_original_sn": engine.original_sn,
                "engine_current_sn": engine.current_sn,
                "remarks": f"Part installed on engine",
                "part_number": part.part_number,
                "part_name": part.name,
                "part_sn": part.serial_number or "N/A"
            }
            result.append(part_event)
    
    return result

# ОБНОВЛЕНИЕ ЗАПИСИ В ИСТОРИИ (ActionLog)
class ActionLogUpdateSchema(BaseModel):
    date: Optional[str] = None
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    to_aircraft: Optional[str] = None
    position: Optional[int] = None
    ac_ttsn: Optional[float] = None
    ac_tcsn: Optional[int] = None
    snapshot_tt: Optional[float] = None
    snapshot_tc: Optional[int] = None
    comments: Optional[str] = None
    supplier: Optional[str] = None
    file_url: Optional[str] = None
    original_sn: Optional[str] = None
    current_sn: Optional[str] = None
    work_type: Optional[str] = None
    inspector: Optional[str] = None
    comment: Optional[str] = None

class ActionLogCreateSchema(BaseModel):
    date: Optional[str] = None
    engine_original_sn: Optional[str] = None
    engine_current_sn: Optional[str] = None
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    to_aircraft: Optional[str] = None
    position: Optional[int] = None
    ac_ttsn: Optional[float] = None
    ac_tcsn: Optional[int] = None
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
            inspection.aircraft = data.to_aircraft
        if data.from_location:  # serial_number
            inspection.serial_number = data.from_location
        if data.position:
            inspection.position = data.position
        if data.to_location:  # gss_id
            inspection.gss_id = data.to_location
        if data.work_type:
            inspection.work_type = data.work_type
        if data.inspector:
            inspection.inspector = data.inspector
        if data.comment is not None:
            inspection.comment = data.comment
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

        # Сохраняем налёт самолета в логе (НЕ обновляем Aircraft.total_time/cycles)
        if data.ac_ttsn is not None:
            log.block_time_str = str(data.ac_ttsn)
        if data.ac_tcsn is not None:
            log.block_in_str = str(data.ac_tcsn)

        if data.comments is not None:
            log.comments = data.comments

        if data.supplier is not None:
            log.supplier = data.supplier

        if data.file_url is not None:
            log.file_url = data.file_url

        if data.original_sn is not None:
            engine.original_sn = data.original_sn
            # Дублируем в логе для отображения в истории
            log.engine_original_sn = data.original_sn

        if data.current_sn is not None:
            engine.current_sn = data.current_sn
            # Дублируем в логе, чтобы сразу отображалось в истории
            log.engine_current_sn = data.current_sn

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
    if data.supplier is not None:
        log.supplier = data.supplier
    if data.file_url is not None:
        log.file_url = data.file_url
    
    db.commit()
    db.refresh(log)
    
    return {"message": f"History record updated successfully (ID: {log_id})"}

# УДАЛЕНИЕ ЗАПИСИ ИЗ ИСТОРИИ (ActionLog)
@app.delete("/api/history/{action_type}/{log_id}")
def delete_history_record(action_type: str, log_id: int, deleted_by: str = Query("User"), db: Session = Depends(get_db)):
    try:
        # Специальная обработка для Reports
        if action_type == "BORESCOPE":
            inspection = db.query(models.BoroscopeInspection).filter(models.BoroscopeInspection.id == log_id).first()
            if not inspection:
                raise HTTPException(404, f"Borescope inspection not found (ID: {log_id})")
            
            # Create notification
            create_notification(
                db,
                action_type="deleted",
                entity_type="borescope",
                entity_id=log_id,
                message=f"Бороскопия: борт {inspection.aircraft}, двигатель {inspection.serial_number}, позиция {inspection.position or '-'}",
                performed_by=deleted_by
            )
            
            db.delete(inspection)
            db.commit()
            return {"message": f"Borescope inspection deleted successfully (ID: {log_id})"}
        
        if action_type == "PURCHASE_ORDER":
            order = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == log_id).first()
            if not order:
                raise HTTPException(404, f"Purchase order not found (ID: {log_id})")
            
            # Create notification
            create_notification(
                db,
                action_type="deleted",
                entity_type="purchase_order",
                entity_id=log_id,
                message=f"Purchase Order '{order.name}' для борта {order.aircraft or '-'} (RO: {order.ro_number or '-'})",
                performed_by=deleted_by
            )
            
            db.delete(order)
            db.commit()
            return {"message": f"Purchase order deleted successfully (ID: {log_id})"}
        
        if action_type == "PARAMETER":
            param = db.query(models.EngineParameterHistory).filter(models.EngineParameterHistory.id == log_id).first()
            if not param:
                raise HTTPException(404, f"Engine parameter record not found (ID: {log_id})")
            
            # Get engine and aircraft info
            engine_sn = param.engine.original_sn or param.engine.current_sn or "Unknown" if param.engine else "Unknown engine"
            engine_info = f"двигатель {engine_sn}"
            aircraft_info = f"борт {param.engine.aircraft.tail_number}" if param.engine and param.engine.aircraft else "N/A"
            date_info = param.date.strftime("%Y-%m-%d") if param.date else "Unknown date"
            
            # Create notification
            create_notification(
                db,
                action_type="deleted",
                entity_type="engine_parameter",
                entity_id=log_id,
                message=f"Engine Parameters: {engine_info}, {aircraft_info}, дата {date_info}",
                performed_by=deleted_by
            )
            
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
        
        # Если это INSTALL, отменяем установку: возвращаем двигатель в статус '-'
        if action_type == "INSTALL" and log.engine:
            engine = log.engine
            engine.status = models.EngineStatus.UNASSIGNED  # Возвращаем статус '-'
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
                # Если нет предыдущей установки, просто меняем статус на '-'
                engine.status = models.EngineStatus.UNASSIGNED
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
        
        # Формируем сообщение для уведомления
        engine_sn = log.engine.original_sn or log.engine.current_sn or "Unknown" if log.engine else ""
        engine_info = f" двигатель {engine_sn}" if log.engine else ""
        aircraft_info = f" с борта {log.to_aircraft or log.from_location or '-'}" if action_type in ["INSTALL", "REMOVE", "SHIP"] else ""
        message = f"{action_type}: {engine_info}{aircraft_info}"
        
        # Create notification перед удалением
        create_notification(
            db,
            action_type="deleted",
            entity_type="history_log",
            entity_id=log_id,
            message=message,
            performed_by=deleted_by
        )
        
        # Удаляем запись
        db.delete(log)
        db.commit()
        
        return {"message": f"History record deleted successfully (ID: {log_id})"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error in delete_history_record ({action_type}, ID: {log_id}): {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to delete {action_type} record: {str(e)}")

# ВАЖНО: Сначала специфичные маршруты (INSTALL), потом общие ({action_type})

# 1. Получить историю установок (Вся информация)
@app.get("/api/history/INSTALL")
def get_install_history(db: Session = Depends(get_db)):
    try:
        # Берем логи только типа INSTALL
        logs = db.query(models.ActionLog).filter(models.ActionLog.action_type == "INSTALL").order_by(models.ActionLog.date.desc()).all()
        def _safe_float(val):
            try:
                return float(val) if val not in (None, "") else None
            except Exception:
                return None

        def _safe_int(val):
            try:
                return int(val) if val not in (None, "") else None
            except Exception:
                return None

        res = []
        for l in logs:
            # Если двигатель удален, пишем заглушку
            orig_sn = l.engine.original_sn if l.engine else "Deleted"
            curr_sn = l.engine.current_sn if l.engine else "-"
            
            # Определяем статус установки
            install_status = "INSTALLED" if l.is_active else "REMOVED"
            
            res.append({
                "id": l.id,
                "date": l.date.strftime("%Y-%m-%d"),
                "original_sn": orig_sn,
                "current_sn": curr_sn,
                "install_to": l.to_aircraft, 
                "position": l.position,
                "location_from": l.from_location,
                "status": install_status,
                "tt": l.snapshot_tt,
                "tc": l.snapshot_tc,
                "ac_ttsn": _safe_float(getattr(l, "block_time_str", None)),
                "ac_tcsn": _safe_int(getattr(l, "block_in_str", None)),
                "supplier": getattr(l, "supplier", None),
                "remarks": l.comments
            })
        return res
    except Exception as e:
        print(f"❌ Error in get_install_history: {e}")
        return []

# 3. Сохранить Установку (INSTALL)
@app.post("/api/actions/install")
def install_engine(data: InstallSchema, db: Session = Depends(get_db)):
    # Ищем двигатель
    eng = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
    if not eng:
        return {
            "status": "warning",
            "code": "ENGINE_NOT_FOUND",
            "message": "⚠️ Двигатель не найден в базе данных",
            "hint": "Пожалуйста, сначала добавьте двигатель в Master Engine List",
            "action": "create_engine"
        }
    
    # Ищем самолет
    ac = db.query(models.Aircraft).filter(models.Aircraft.id == data.aircraft_id).first()
    if not ac:
        return {
            "status": "warning",
            "code": "AIRCRAFT_NOT_FOUND",
            "message": "⚠️ Самолет не найден в базе данных",
            "hint": "Пожалуйста, сначала добавьте самолет в Fleet",
            "action": "create_aircraft"
        }
    
    # Проверяем нет ли уже двигателя на этой позиции
    existing_engine = db.query(models.Engine).filter(
        models.Engine.aircraft_id == data.aircraft_id,
        models.Engine.position == data.position,
        models.Engine.status == "INSTALLED"
    ).first()
    
    if existing_engine:
        # УМНАЯ ПРОВЕРКА: Проверяем есть ли removal для этого двигателя с датой >= новой installation
        install_date = parse_input_date(data.date) or datetime.now()
        
        removal_after = db.query(models.ActionLog).filter(
            models.ActionLog.action_type == "REMOVE",
            models.ActionLog.engine_id == existing_engine.id,
            models.ActionLog.to_aircraft == ac.tail_number,
            models.ActionLog.date >= install_date
        ).first()
        
        if not removal_after:
            return {
                "status": "warning",
                "code": "POSITION_OCCUPIED",
                "message": f"⚠️ Позиция {data.position} на {ac.tail_number} уже занята",
                "hint": f"Двигатель {existing_engine.current_sn or existing_engine.original_sn} установлен на этой позиции. Сначала снимите его.",
                "action": "remove_engine_first"
            }
    
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
    
    # Обновляем Current SN если передан при установке
    if data.current_sn and data.current_sn.strip():
        eng.current_sn = data.current_sn.strip()

    # НЕ обновляем aircraft.total_time/cycles здесь - только через Utilization Parameters
    
    # SNAPSHOT для отслеживания наработки на конкретном самолете
    eng.tsn_at_install = data.tt
    eng.csn_at_install = data.tc
    eng.install_date = install_dt or datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(eng)  # Обновляем объект двигателя после commit
    
    # Пишем историю
    new_log = models.ActionLog(
        action_type="INSTALL",
        engine_id=eng.id,
        from_location=from_loc,
        to_aircraft=ac.tail_number,
        position=data.position,
        snapshot_tt=data.tt,
        snapshot_tc=data.tc,
        block_time_str=str(data.ac_ttsn) if data.ac_ttsn is not None else None,
        block_in_str=str(data.ac_tcsn) if data.ac_tcsn is not None else None,
        comments=data.remarks,
        supplier=data.supplier,
        date=install_dt or datetime.now()
    )
    new_log.is_active = True  # Помечаем установку как активную
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
    return {
        "status": "success",
        "message": f"✅ Двигатель {eng.current_sn} успешно установлен на {ac.tail_number} (позиция {data.position})",
        "data": {"engine_id": eng.id, "aircraft_id": ac.id, "log_id": new_log.id}
    }

# 4. История перемещений (SHIP)
@app.get("/api/history/SHIP")
def get_shipment_history(db: Session = Depends(get_db)):
    try:
        logs = db.query(models.ActionLog).filter(models.ActionLog.action_type == "SHIP").order_by(models.ActionLog.date.desc()).all()
        res = []
        for l in logs:
            orig_sn = l.engine.original_sn if l.engine else "Deleted"
            curr_sn = l.engine.current_sn if l.engine else "-"
            engine_model = (getattr(l.engine, "model", None) if l.engine else None) or "-"
            gss_id = (
                getattr(l.engine, "gss_id", None) if l.engine else None
            ) or (getattr(l.engine, "gss_sn", None) if l.engine else None) or "-"

            res.append({
                "id": l.id,
                "date": l.date.strftime("%Y-%m-%d"),
                "original_sn": orig_sn,
                "current_sn": curr_sn,
                "engine_model": engine_model,
                "gss_id": gss_id,
                "from": l.from_location or "-",
                "to": l.to_location or "-",
                "remarks": l.comments
            })
        return res
    except Exception as e:
        print(f"❌ Error in get_shipment_history: {e}")
        return []

# 5. Сохранить Перемещение (SHIPMENT)
@app.post("/api/actions/ship")
def ship_engine(data: ShipmentSchema, db: Session = Depends(get_db)):
    # Ищем двигатель
    eng = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
    if not eng:
        return {
            "status": "warning",
            "code": "ENGINE_NOT_FOUND",
            "message": "⚠️ Двигатель не найден в базе данных",
            "hint": "Пожалуйста, сначала добавьте двигатель в Master Engine List",
            "action": "create_engine"
        }
    
    # Проверка: INSTALLED двигатели нельзя отправлять (они на крыльях)
    if eng.status == "INSTALLED":
        return {
            "status": "warning",
            "code": "ENGINE_INSTALLED",
            "message": f"⚠️ Невозможно отправить двигатель {eng.original_sn}",
            "hint": "Двигатель установлен на самолете. Сначала снимите его с самолета",
            "action": "remove_engine_first"
        }
    
    # Ищем локацию назначения
    dest_loc = db.query(models.Location).filter(models.Location.id == data.to_location_id).first()
    if not dest_loc:
        return {
            "status": "warning",
            "code": "LOCATION_NOT_FOUND",
            "message": "⚠️ Локация назначения не найдена",
            "hint": "Пожалуйста, проверьте выбранную локацию",
            "action": "check_location"
        }

    # Откуда забираем (для истории)
    from_loc_txt = "Unknown"
    if eng.location:
        from_loc_txt = eng.location.name
    elif eng.aircraft:
        from_loc_txt = f"AC: {eng.aircraft.tail_number}"

    # Логика перемещения:
    # Shipment - это отправка двигателя в другую локацию, но он остается на самолете
    # Если двигатель был на самолете (INSTALLED), он остается на самолете (сохраняем aircraft_id)
    # Если двигатель был на складе (SV), он остается на складе
    # Меняется только location_id - место назначения отправки
    eng.location_id = dest_loc.id
    # Статус НЕ меняется при shipment - двигатель остается в том же статусе
    # (если был INSTALLED, остается INSTALLED; если SV, остается SV и т.д.)

    # Пишем лог
    new_log = models.ActionLog(
        action_type="SHIP",
        engine_id=eng.id,
        from_location=from_loc_txt,
        to_location=dest_loc.name,
        comments=f"WB: {data.waybill} | {data.remarks}",
        date=datetime.now()
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
    return {
        "status": "success",
        "message": f"✅ Двигатель {eng.current_sn} успешно отправлен в {dest_loc.name}",
        "data": {"engine_id": eng.id, "location_id": dest_loc.id, "log_id": new_log.id}
    }

# 6. История снятий (REMOVE)
@app.get("/api/history/REMOVE")
def get_remove_history(db: Session = Depends(get_db)):
    try:
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
                "remarks": l.comments,
                "ttsn": l.ttsn,
                "tcsn": l.tcsn,
                "ttsn_ac": l.ttsn_ac,
                "tcsn_ac": l.tcsn_ac,
                "remarks_removal": l.remarks_removal
            })
        return res
    except Exception as e:
        print(f"❌ Error in get_remove_history: {e}")
        return []

# 7. Сохранить Снятие (REMOVE)
@app.post("/api/actions/remove")
def remove_engine(data: RemoveSchema, db: Session = Depends(get_db)):
    eng = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
    if not eng:
        return {
            "status": "warning",
            "code": "ENGINE_NOT_FOUND",
            "message": "⚠️ Двигатель не найден в базе данных",
            "hint": "Пожалуйста, сначала добавьте двигатель в Master Engine List",
            "action": "create_engine"
        }
    
    # Проверяем что двигатель установлен на самолете
    if eng.status != models.EngineStatus.INSTALLED:
        return {
            "status": "warning",
            "code": "ENGINE_NOT_INSTALLED",
            "message": f"⚠️ Невозможно снять двигатель {eng.original_sn}",
            "hint": f"Текущий статус: {eng.status}. Можно снимать только установленные двигатели (INSTALLED)",
            "action": "install_first"
        }
    
    if not eng.aircraft_id:
        return {
            "status": "warning",
            "code": "ENGINE_NO_AIRCRAFT",
            "message": f"⚠️ Двигатель {eng.original_sn} не установлен на самолете",
            "hint": "Проверьте статус двигателя в системе",
            "action": "check_status"
        }
    
    dest_loc = db.query(models.Location).filter(models.Location.id == data.to_location_id).first()
    if not dest_loc:
        return {
            "status": "warning",
            "code": "LOCATION_NOT_FOUND",
            "message": "⚠️ Локация назначения не найдена",
            "hint": "Пожалуйста, проверьте выбранную локацию",
            "action": "check_location"
        }

    # Запоминаем, откуда сняли (с самолета)
    from_txt = "Unknown"
    if eng.aircraft:
        from_txt = f"AC: {eng.aircraft.tail_number} (Pos {eng.position})"

    # Логика: Отвязываем от самолета, привязываем к локации
    eng.aircraft_id = None
    eng.position = None
    eng.location_id = dest_loc.id
    eng.status = "REMOVED" # Меняем статус
    eng.condition_1 = data.condition_1  # Обновляем техсостояние

    # Закрываем активную установку (is_active = False) для этого двигателя
    active_install = db.query(models.ActionLog).filter(
        models.ActionLog.engine_id == eng.id,
        models.ActionLog.action_type == "INSTALL",
        models.ActionLog.is_active == True
    ).order_by(models.ActionLog.date.desc()).first()
    
    if active_install:
        active_install.is_active = False

    # Пишем лог (с полными данными для истории)
    new_log = models.ActionLog(
        action_type="REMOVE",
        engine_id=eng.id,
        from_location=from_txt,
        to_location=dest_loc.name,
        condition_1_at_removal=data.condition_1,
        comments=data.reason,
        date=datetime.now(),
        snapshot_tt=eng.total_time,
        snapshot_tc=eng.total_cycles,
        ttsn=data.ttsn,
        tcsn=data.tcsn,
        ttsn_ac=data.ttsn_ac,
        tcsn_ac=data.tcsn_ac,
        remarks_removal=data.remarks
    )
    db.add(new_log)
    db.commit()
    db.refresh(eng)  # Обновляем объект двигателя после commit

    # Log action
    create_notification(
        db,
        action_type="created",
        entity_type="remove",
        entity_id=new_log.id,
        message=f"Были внесены данные пользователем User в группу Remove: двигатель {eng.current_sn} снят с {from_txt} и перемещен в {dest_loc.name}",
        performed_by="User"
    )
    return {
        "status": "success",
        "message": f"✅ Двигатель {eng.current_sn} успешно снят и перемещен в {dest_loc.name}",
        "data": {"engine_id": eng.id, "location_id": dest_loc.id, "log_id": new_log.id}
    }
    
    # 9. История ремонтов (REPAIR)
@app.get("/api/history/REPAIR")
def get_repair_history(db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        print(f"❌ Error in get_repair_history: {e}")
        return []

# 10. Сохранить Ремонт (REPAIR)
@app.post("/api/actions/repair")
def repair_engine(data: RepairSchema, db: Session = Depends(get_db)):
    eng = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
    if not eng:
        return {
            "status": "warning",
            "code": "ENGINE_NOT_FOUND",
            "message": "⚠️ Двигатель не найден в базе данных",
            "hint": "Пожалуйста, сначала добавьте двигатель в Master Engine List",
            "action": "create_engine"
        }
    
    # Проверка: SV двигатели нельзя отремонтировать
    if eng.status == "SV":
        return {
            "status": "warning",
            "code": "ENGINE_ALREADY_SV",
            "message": f"⚠️ Двигатель {eng.original_sn} уже исправен (SV)",
            "hint": "Ремонтировать можно только двигатели в статусе US, REMOVED и т.д.",
            "action": "check_status"
        }
    
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
        comments=data.remarks,
        date=datetime.now()
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
    return {
        "status": "success",
        "message": f"✅ Ремонт двигателя {eng.current_sn} успешно зарегистрирован (вендор: {data.vendor})",
        "data": {"engine_id": eng.id, "vendor": data.vendor, "log_id": new_log.id}
    } 
# 13. История запчастей (PARTS LOGISTICS / STORE BALANCE)
@app.get("/api/parts/history")
def get_parts_history(db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        print(f"❌ Error in get_parts_history: {e}")
        return []

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
    try:
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
    except Exception as e:
        print(f"❌ Error in get_store_balance: {e}")
        return []


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
    try:
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

            log_date = log.date or datetime.now(timezone.utc)

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
    except Exception as e:
        print(f"❌ Error in get_flight_history: {e}")
        return []


@app.get("/api/utilization/summary")
def get_utilization_summary(db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        print(f"❌ Error in get_utilization_summary: {e}")
        return []

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

    log_date = parse_input_date(data.date) or datetime.now(timezone.utc)

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
    try:
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

            log_date = log.date or datetime.now(timezone.utc)

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
    except Exception as e:
        print(f"❌ Error in get_atlb_history: {e}")
        return []

# 18. Сохранить ATLB (и обновить счетчики)
@app.post("/api/actions/atlb")
def save_atlb(data: ATLBSchema, db: Session = Depends(get_db)):
    # 1. Ищем самолет
    ac = db.query(models.Aircraft).filter(models.Aircraft.id == data.aircraft_id).first()
    if not ac: raise HTTPException(404, "Aircraft not found")
    
    atlb_no = (data.atlb_no or "").strip()
    if not atlb_no:
        raise HTTPException(status_code=400, detail="ATLB sheet number is required")

    log_date = parse_input_date(data.date) or datetime.now(timezone.utc)

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
    try:
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
    except Exception as e:
        print(f"❌ Error in get_parameter_history: {e}")
        return []


# Alias endpoint to avoid conflicts with dynamic engine routes
@app.get("/api/engine-parameters/history")
def get_parameter_history_alias(engine_id: int = None, db: Session = Depends(get_db)):
    return get_parameter_history(engine_id=engine_id, db=db)

# --- BORESCOPE INSPECTIONS API ---

@app.get("/api/history/BORESCOPE")
def get_borescope_history(db: Session = Depends(get_db)):
    try:
        inspections = db.query(models.BoroscopeInspection).order_by(models.BoroscopeInspection.date.desc()).all()
        result = []
        print("\n" + "="*60)
        print(f"📥 LOADING BORESCOPE HISTORY ({len(inspections)} records)")
        print("="*60)
        for insp in inspections:
            report = insp.inspection_report
            print(f"\nID {insp.id}:")
            print(f"  inspection_report type: {type(report)}")
            print(f"  inspection_report value: {report}")
            if report:
                if isinstance(report, dict):
                    photos = report.get('photos', [])
                    print(f"  Photos: {len(photos) if isinstance(photos, list) else 'NOT A LIST'}")
                elif isinstance(report, str):
                    print(f"  WARNING: inspection_report is STRING, not DICT!")
            result.append({
                "id": insp.id,
                "date": insp.date,
                "aircraft": insp.aircraft,
                "serial_number": insp.serial_number,
                "position": insp.position,
                "work_type": insp.work_type,
                "gss_id": insp.gss_id,
                "inspector": insp.inspector,
                "comment": insp.comment,
                "link": insp.link,
                "inspection_report": insp.inspection_report or {"photos": []}  # Если NULL, возвращаем пустой объект с фото массивом
            })
        return result
    except Exception as e:
        print(f"❌ Error in get_borescope_history: {e}")
        return []

@app.post("/api/history/BORESCOPE")
async def create_borescope_inspection(
    date: str = Form(...),
    aircraft: str = Form(...),
    serial_number: str = Form(...),
    position: str = Form(""),
    work_type: str = Form("All Engine"),
    gss_id: str = Form(""),
    inspector: str = Form(...),
    comment: str = Form(""),
    link: str = Form(""),
    photo_labels: str = Form("[]"),  # JSON string with labels
    photos: list[UploadFile] = File([]),  # List of uploaded photo files
    db: Session = Depends(get_db)
):
    """
    Create borescope inspection with photos uploaded to R2
    Photos are stored in Cloudflare R2, only URLs saved in database
    """
    try:
        from backend.r2_storage import upload_photo_to_r2, test_r2_connection
        import json
        
        print("\n" + "="*60)
        print("📝 SAVING BORESCOPE INSPECTION (R2 STORAGE)")
        print("="*60)
        print(f"Date: {date}")
        print(f"Aircraft: {aircraft}")
        print(f"Serial: {serial_number}")
        print(f"Inspector: {inspector}")
        print(f"Photos received: {len(photos)}")
        print(f"Photo labels: {photo_labels}")
        
        # Validate required fields
        if not all([date, aircraft, serial_number, work_type, inspector]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        # Create inspection record first (to get ID)
        new_inspection = models.BoroscopeInspection(
            date=date,
            aircraft=aircraft,
            serial_number=serial_number,
            position=position,
            work_type=work_type,
            gss_id=gss_id,
            inspector=inspector,
            comment=comment,
            link=link,
            inspection_report=None  # Will be updated after photo upload
        )
        db.add(new_inspection)
        db.commit()
        db.refresh(new_inspection)
        
        inspection_id = new_inspection.id
        print(f"✅ Inspection created with ID: {inspection_id}")
        
        # Parse photo labels
        try:
            labels = json.loads(photo_labels) if photo_labels else []
        except:
            labels = []
        
        # Upload photos to R2 and build inspection_report
        photo_data = []
        if photos and len(photos) > 0:
            print(f"\n📤 Uploading {len(photos)} photos to R2...")
            
            # Test R2 connection
            if not test_r2_connection():
                raise HTTPException(status_code=500, detail="R2 storage connection failed")
            
            # Upload each photo
            for idx, file in enumerate(photos):
                if file and file.filename:
                    # Read file bytes
                    file_bytes = await file.read()
                    
                    # Determine photo row and position
                    photo_row_idx = idx // 2  # 0, 0, 1, 1, 2, 2...
                    photo_num = (idx % 2) + 1  # 1, 2, 1, 2, 1, 2...
                    
                    # Get label for this row
                    label = labels[photo_row_idx] if photo_row_idx < len(labels) else f"Photo {photo_row_idx + 1}"
                    
                    # Upload to R2
                    photo_url = upload_photo_to_r2(file_bytes, inspection_id, photo_row_idx, photo_num)
                    
                    # Add to photo_data
                    # Ensure row exists
                    while len(photo_data) <= photo_row_idx:
                        photo_data.append({"label": "", "photo1": None, "photo2": None})
                    
                    photo_data[photo_row_idx]["label"] = label
                    if photo_num == 1:
                        photo_data[photo_row_idx]["photo1"] = photo_url
                    else:
                        photo_data[photo_row_idx]["photo2"] = photo_url
                    
                    print(f"  ✅ Photo {idx + 1}: {file.filename} → {photo_url}")
        
        # Update inspection_report with photo URLs
        inspection_report = {"photos": photo_data}
        new_inspection.inspection_report = inspection_report
        db.commit()
        db.refresh(new_inspection)
        
        print(f"\n✅ SAVED TO DATABASE:")
        print(f"   ID: {inspection_id}")
        print(f"   Photos in R2: {len(photo_data)}")
        print("="*60 + "\n")
        
        return {"id": inspection_id, "message": "Borescope inspection created successfully", "photos": len(photo_data)}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error creating borescope inspection: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create inspection: {str(e)}")

@app.delete("/api/history/BORESCOPE/{inspection_id}")
def delete_borescope_inspection(inspection_id: int, db: Session = Depends(get_db)):
    """
    Delete borescope inspection and remove photos from R2 storage
    """
    try:
        from backend.r2_storage import delete_photo_from_r2
        
        # Find inspection
        inspection = db.query(models.BoroscopeInspection).filter(models.BoroscopeInspection.id == inspection_id).first()
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection not found")
        
        print(f"\n🗑️ Deleting borescope inspection ID: {inspection_id}")
        
        # Delete photos from R2 if they exist
        deleted_photos = 0
        if inspection.inspection_report and isinstance(inspection.inspection_report, dict):
            photos = inspection.inspection_report.get('photos', [])
            if isinstance(photos, list):
                for photo_row in photos:
                    if isinstance(photo_row, dict):
                        for key in ['photo1', 'photo2']:
                            photo_url = photo_row.get(key)
                            if photo_url and photo_url.startswith('http'):
                                if delete_photo_from_r2(photo_url):
                                    deleted_photos += 1
        
        # Delete from database
        db.delete(inspection)
        db.commit()
        
        print(f"✅ Deleted inspection {inspection_id} and {deleted_photos} photos from R2\n")
        return {"message": f"Inspection deleted successfully ({deleted_photos} photos removed from R2)"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error deleting borescope inspection: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete inspection: {str(e)}")

# --- BOROSCOPE SCHEDULE API ---

@app.post("/api/boroscope/schedule")
def create_boroscope_schedule(data: BoroscopeScheduleCreateSchema, db: Session = Depends(get_db)):
    """Создать новый запланированный боroскоп"""
    try:
        from datetime import datetime
        
        # Парсим дату
        schedule_date = datetime.strptime(data.date, "%Y-%m-%d").date()
        
        # Проверяем, существует ли уже запись на эту дату/самолет/позицию
        existing = db.query(models.BoroscopeSchedule).filter(
            models.BoroscopeSchedule.date == schedule_date,
            models.BoroscopeSchedule.aircraft_tail_number == data.aircraft_tail_number,
            models.BoroscopeSchedule.position == data.position
        ).first()
        
        if existing:
            return {
                "status": "warning",
                "message": f"Boroscope already scheduled for {data.aircraft_tail_number} Position {data.position} on {data.date}"
            }
        
        # Создаем новую запись
        new_schedule = models.BoroscopeSchedule(
            date=schedule_date,
            aircraft_tail_number=data.aircraft_tail_number,
            position=data.position,
            inspector=data.inspector,
            remarks=data.remarks,
            location=data.location,
            status="Scheduled"
        )
        
        db.add(new_schedule)
        db.commit()
        db.refresh(new_schedule)
        
        create_notification(
            db,
            action_type="created",
            entity_type="boroscope_schedule",
            entity_id=new_schedule.id,
            message=f"Boroscope scheduled for {data.aircraft_tail_number} Position {data.position} on {data.date}",
            performed_by="User"
        )
        
        return {
            "status": "success",
            "message": f"Boroscope scheduled successfully for {data.aircraft_tail_number} Position {data.position}",
            "data": {"id": new_schedule.id}
        }
    except Exception as e:
        print(f"❌ Error creating boroscope schedule: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/boroscope/schedule")
def get_boroscope_schedules(
    aircraft: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Получить список запланированных боroскопов с фильтрацией"""
    try:
        from datetime import datetime
        
        query = db.query(models.BoroscopeSchedule)
        
        # Фильтры
        if aircraft:
            query = query.filter(models.BoroscopeSchedule.aircraft_tail_number == aircraft)
        
        if date_from:
            start_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            query = query.filter(models.BoroscopeSchedule.date >= start_date)
        
        if date_to:
            end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            query = query.filter(models.BoroscopeSchedule.date <= end_date)
        
        if status:
            query = query.filter(models.BoroscopeSchedule.status == status)
        
        schedules = query.order_by(models.BoroscopeSchedule.date.asc()).all()
        
        result = []
        for schedule in schedules:
            result.append({
                "id": schedule.id,
                "date": schedule.date.strftime("%Y-%m-%d") if schedule.date else None,
                "aircraft_tail_number": schedule.aircraft_tail_number,
                "position": schedule.position,
                "inspector": schedule.inspector,
                "remarks": schedule.remarks,
                "location": schedule.location,
                "status": schedule.status,
                "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
                "completed_at": schedule.completed_at.isoformat() if schedule.completed_at else None
            })
        
        return result
    except Exception as e:
        print(f"❌ Error fetching boroscope schedules: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/boroscope/schedule/{schedule_id}")
def get_boroscope_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """Получить одну запись о запланированном боroскопе"""
    schedule = db.query(models.BoroscopeSchedule).filter(models.BoroscopeSchedule.id == schedule_id).first()
    
    if not schedule:
        raise HTTPException(status_code=404, detail="Boroscope schedule not found")
    
    return {
        "id": schedule.id,
        "date": schedule.date.strftime("%Y-%m-%d") if schedule.date else None,
        "aircraft_tail_number": schedule.aircraft_tail_number,
        "position": schedule.position,
        "inspector": schedule.inspector,
        "remarks": schedule.remarks,
        "location": schedule.location,
        "status": schedule.status,
        "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
        "completed_at": schedule.completed_at.isoformat() if schedule.completed_at else None
    }

@app.put("/api/boroscope/schedule/{schedule_id}")
def update_boroscope_schedule(
    schedule_id: int,
    data: BoroscopeScheduleUpdateSchema,
    db: Session = Depends(get_db)
):
    """Обновить запланированный боroскоп"""
    try:
        from datetime import datetime
        
        schedule = db.query(models.BoroscopeSchedule).filter(models.BoroscopeSchedule.id == schedule_id).first()
        
        if not schedule:
            raise HTTPException(status_code=404, detail="Boroscope schedule not found")
        
        # Обновляем поля
        if data.date:
            schedule.date = datetime.strptime(data.date, "%Y-%m-%d").date()
        if data.position:
            schedule.position = data.position
        if data.inspector:
            schedule.inspector = data.inspector
        if data.remarks is not None:
            schedule.remarks = data.remarks
        if data.location is not None:
            schedule.location = data.location
        if data.status:
            schedule.status = data.status
            if data.status == "Completed":
                schedule.completed_at = datetime.now()
        
        db.commit()
        db.refresh(schedule)
        
        return {
            "status": "success",
            "message": "Boroscope schedule updated successfully"
        }
    except Exception as e:
        print(f"❌ Error updating boroscope schedule: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/boroscope/schedule/{schedule_id}")
def delete_boroscope_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """Удалить запланированный боroскоп"""
    try:
        schedule = db.query(models.BoroscopeSchedule).filter(models.BoroscopeSchedule.id == schedule_id).first()
        
        if not schedule:
            raise HTTPException(status_code=404, detail="Boroscope schedule not found")
        
        db.delete(schedule)
        db.commit()
        
        return {"status": "success", "message": "Boroscope schedule deleted successfully"}
    except Exception as e:
        print(f"❌ Error deleting boroscope schedule: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/boroscope/schedule/upcoming/reminders")
def get_boroscope_reminders(db: Session = Depends(get_db)):
    """Получить напоминания о боroскопах на сегодня/завтра"""
    try:
        from datetime import datetime, timedelta
        
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        
        # Запланированные на сегодня и завтра со статусом Scheduled
        reminders = db.query(models.BoroscopeSchedule).filter(
            models.BoroscopeSchedule.date.in_([today, tomorrow]),
            models.BoroscopeSchedule.status == "Scheduled"
        ).order_by(models.BoroscopeSchedule.date.asc()).all()
        
        result = []
        for reminder in reminders:
            days_until = (reminder.date - today).days
            reminder_type = "Today" if days_until == 0 else "Tomorrow"
            
            result.append({
                "id": reminder.id,
                "reminder_type": reminder_type,
                "date": reminder.date.strftime("%Y-%m-%d"),
                "aircraft": reminder.aircraft_tail_number,
                "position": reminder.position,
                "inspector": reminder.inspector,
                "location": reminder.location
            })
        
        return result
    except Exception as e:
        print(f"❌ Error getting boroscope reminders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- PURCHASE ORDERS API ---

@app.get("/api/history/PURCHASE_ORDER")
def get_purchase_orders_history(db: Session = Depends(get_db)):
    try:
        orders = db.query(models.PurchaseOrder).order_by(models.PurchaseOrder.date.desc()).all()
        print(f"📦 Found {len(orders)} purchase orders in DB")
        
        # Получаем все пользовательские колонки для purchase_orders
        custom_columns = db.query(models.CustomColumn).filter(
            models.CustomColumn.table_name == "purchase_orders"
        ).order_by(models.CustomColumn.column_order).all()
        
        result = []
        for order in orders:
            order_data = {
                "id": order.id,
                "date": order.date,
                "name": order.name,
                "part_number": order.part_number,
                "serial_number": order.serial_number,
                "price": order.price,
                "purpose": order.purpose,
                "aircraft": order.aircraft,
                "ro_number": order.ro_number,
                "link": order.link
            }
            
            # Добавляем данные для пользовательских колонок
            for col in custom_columns:
                custom_data = db.query(models.PurchaseOrderCustomData).filter(
                    models.PurchaseOrderCustomData.purchase_order_id == order.id,
                    models.PurchaseOrderCustomData.column_key == col.column_key
                ).first()
                order_data[col.column_key] = custom_data.value if custom_data else None
            
            result.append(order_data)
        
        print(f"✅ Returning {len(result)} purchase orders")
        return JSONResponse(
            content=result,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    except Exception as e:
        print(f"❌ Error in get_purchase_orders_history: {e}")
        import traceback
        traceback.print_exc()
        return []

@app.post("/api/history/PURCHASE_ORDER")
def create_purchase_order(data: PurchaseOrderSchema, db: Session = Depends(get_db)):
    try:
        print(f"📝 Creating purchase order:")
        print(f"  - date: {data.date}")
        print(f"  - name: {data.name}")
        print(f"  - aircraft: {data.aircraft}")
        print(f"  - ro_number: {data.ro_number}")
        print(f"  - purpose: {data.purpose}")
        
        price_val = None
        try:
            price_val = float(data.price) if data.price is not None else None
        except Exception as e:
            print(f"  ⚠️ Price parse error: {e}")
            price_val = None

        new_order = models.PurchaseOrder(
            date=data.date,
            name=data.name,
            part_number=data.part_number,
            serial_number=data.serial_number,
            price=price_val,
            purpose=data.purpose,
            aircraft=data.aircraft,
            ro_number=data.ro_number,
            link=data.link
        )
        db.add(new_order)
        db.flush()
        print(f"  ✓ Flushed to DB")
        db.commit()
        print(f"  ✓ Committed to DB")
        db.refresh(new_order)
        print(f"✅ Purchase order saved: ID={new_order.id}, name={new_order.name}")

        # Log action
        create_notification(
            db,
            action_type="created",
            entity_type="purchase_order",
            entity_id=new_order.id,
            message=f"Purchase Order '{data.name}' для борта {data.aircraft or '-'} (RO: {data.ro_number or '-'}) создан",
            performed_by="User"
        )
        return {"status": "ok", "id": new_order.id, "message": f"Purchase order '{data.name}' saved successfully"}
    except Exception as e:
        print(f"❌ Error in create_purchase_order: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return {"status": "error", "detail": f"Failed to create purchase order: {str(e)}"}


# --- SCHEDULED EVENTS API (Calendar) ---

@app.get("/api/events")
def get_all_events(db: Session = Depends(get_db)):
    """Получить все запланированные события"""
    try:
        events = db.query(models.ScheduledEvent).order_by(models.ScheduledEvent.event_date.asc()).all()
        result = []
        for event in events:
            result.append({
                "id": event.id,
                "event_date": event.event_date,
                "event_time": event.event_time,
                "event_type": event.event_type,
                "title": event.title,
                "description": event.description,
                "engine_id": event.engine_id,
                "serial_number": event.serial_number,
                "location": event.location,
                "from_location": event.from_location,
                "to_location": event.to_location,
                "status": event.status,
                "priority": event.priority,
                "color": event.color,
                "created_by": event.created_by,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "updated_at": event.updated_at.isoformat() if event.updated_at else None
            })
        return result
    except Exception as e:
        print(f"❌ Error in get_all_events: {e}")
        import traceback
        traceback.print_exc()
        return []


@app.get("/api/events/calendar/{year}/{month}")
def get_events_by_month(year: int, month: int, db: Session = Depends(get_db)):
    """Получить события за конкретный месяц (для календаря)"""
    try:
        # Формируем диапазон дат для месяца (YYYY-MM)
        month_str = f"{year:04d}-{month:02d}"
        
        events = db.query(models.ScheduledEvent).filter(
            models.ScheduledEvent.event_date.like(f"{month_str}%")
        ).order_by(models.ScheduledEvent.event_date.asc()).all()
        
        result = []
        for event in events:
            result.append({
                "id": event.id,
                "event_date": event.event_date,
                "event_time": event.event_time,
                "event_type": event.event_type,
                "title": event.title,
                "description": event.description,
                "engine_id": event.engine_id,
                "serial_number": event.serial_number,
                "location": event.location,
                "from_location": event.from_location,
                "to_location": event.to_location,
                "status": event.status,
                "priority": event.priority,
                "color": event.color,
                "created_by": event.created_by
            })
        return result
    except Exception as e:
        print(f"❌ Error in get_events_by_month: {e}")
        import traceback
        traceback.print_exc()
        return []


@app.get("/api/events/{event_id}")
def get_event_by_id(event_id: int, db: Session = Depends(get_db)):
    """Получить детали конкретного события"""
    try:
        event = db.query(models.ScheduledEvent).filter(models.ScheduledEvent.id == event_id).first()
        if not event:
            raise HTTPException(404, f"Event not found (ID: {event_id})")
        
        return {
            "id": event.id,
            "event_date": event.event_date,
            "event_time": event.event_time,
            "event_type": event.event_type,
            "title": event.title,
            "description": event.description,
            "engine_id": event.engine_id,
            "serial_number": event.serial_number,
            "location": event.location,
            "from_location": event.from_location,
            "to_location": event.to_location,
            "status": event.status,
            "priority": event.priority,
            "color": event.color,
            "created_by": event.created_by,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "updated_at": event.updated_at.isoformat() if event.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in get_event_by_id: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to get event: {str(e)}")


@app.post("/api/events")
def create_event(data: ScheduledEventSchema, db: Session = Depends(get_db)):
    """Создать новое событие в календаре"""
    try:
        new_event = models.ScheduledEvent(
            event_date=data.event_date,
            event_time=data.event_time,
            event_type=data.event_type,
            title=data.title,
            description=data.description,
            engine_id=data.engine_id,
            serial_number=data.serial_number,
            location=data.location,
            from_location=data.from_location,
            to_location=data.to_location,
            status=data.status or "PLANNED",
            priority=data.priority or "MEDIUM",
            color=data.color or "#3788d8",
            created_by=data.created_by
        )
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        
        # Log notification with details
        location_info = f" в {data.location}" if data.location else ""
        engine_info = f" (S/N: {data.serial_number})" if data.serial_number else ""
        create_notification(
            db,
            action_type="created",
            entity_type="scheduled_event",
            entity_id=new_event.id,
            message=f"📅 Событие '{data.title}' запланировано на {data.event_date}{location_info}{engine_info} ({data.event_type})",
            performed_by=data.created_by or "User"
        )
        
        return {"status": "ok", "id": new_event.id}
    except Exception as e:
        db.rollback()
        print(f"❌ Error in create_event: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to create event: {str(e)}")


@app.put("/api/events/{event_id}")
def update_event(event_id: int, data: ScheduledEventSchema, db: Session = Depends(get_db)):
    """Обновить существующее событие"""
    try:
        event = db.query(models.ScheduledEvent).filter(models.ScheduledEvent.id == event_id).first()
        if not event:
            raise HTTPException(404, f"Event not found (ID: {event_id})")
        
        # Обновляем поля
        event.event_date = data.event_date
        event.event_time = data.event_time
        event.event_type = data.event_type
        event.title = data.title
        event.description = data.description
        event.engine_id = data.engine_id
        event.serial_number = data.serial_number
        event.location = data.location
        event.from_location = data.from_location
        event.to_location = data.to_location
        event.status = data.status or event.status
        event.priority = data.priority or event.priority
        event.color = data.color or event.color
        
        db.commit()
        
        # Log notification with status
        status_info = f" [Статус: {data.status}]" if data.status != "PLANNED" else ""
        create_notification(
            db,
            action_type="updated",
            entity_type="scheduled_event",
            entity_id=event.id,
            message=f"📅 Событие '{data.title}' обновлено ({data.event_date}){status_info}",
            performed_by=data.created_by or "User"
        )
        
        return {"status": "ok", "id": event.id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error in update_event: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to update event: {str(e)}")


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int, deleted_by: str = Query("User"), db: Session = Depends(get_db)):
    """Удалить событие из календаря"""
    try:
        event = db.query(models.ScheduledEvent).filter(models.ScheduledEvent.id == event_id).first()
        if not event:
            raise HTTPException(404, f"Event not found (ID: {event_id})")
        
        event_title = event.title
        event_date = event.event_date
        
        # Create notification before deletion
        create_notification(
            db,
            action_type="deleted",
            entity_type="scheduled_event",
            entity_id=event_id,
            message=f"📅 Событие '{event_title}' удалено (было запланировано на {event_date})",
            performed_by=deleted_by
        )
        
        db.delete(event)
        db.commit()
        
        return {"message": f"Event '{event_title}' deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error in delete_event: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to delete event: {str(e)}")


# --- CUSTOM COLUMNS API ---

@app.get("/api/custom-columns/{table_name}")
def get_custom_columns(table_name: str, db: Session = Depends(get_db)):
    """Получить список пользовательских колонок для таблицы"""
    try:
        columns = db.query(models.CustomColumn).filter(
            models.CustomColumn.table_name == table_name
        ).order_by(models.CustomColumn.column_order).all()
        
        return [{
            "id": col.id,
            "column_key": col.column_key,
            "column_label": col.column_label,
            "column_order": col.column_order
        } for col in columns]
    except Exception as e:
        print(f"Error in get_custom_columns: {e}")
        return []


@app.post("/api/custom-columns/{table_name}")
def create_custom_column(table_name: str, data: CustomColumnSchema, db: Session = Depends(get_db)):
    """Создать новую пользовательскую колонку"""
    # Генерируем уникальный ключ для новой колонки
    existing_cols = db.query(models.CustomColumn).filter(
        models.CustomColumn.table_name == table_name
    ).all()
    
    max_num = 0
    for col in existing_cols:
        if col.column_key.startswith("custom_"):
            try:
                num = int(col.column_key.replace("custom_", ""))
                max_num = max(max_num, num)
            except:
                pass
    
    new_key = f"custom_{max_num + 1}"
    
    new_column = models.CustomColumn(
        table_name=table_name,
        column_key=new_key,
        column_label=data.column_label,
        column_order=data.column_order if data.column_order else len(existing_cols)
    )
    
    db.add(new_column)
    db.commit()
    db.refresh(new_column)
    
    return {
        "id": new_column.id,
        "column_key": new_column.column_key,
        "column_label": new_column.column_label,
        "column_order": new_column.column_order
    }


@app.put("/api/custom-columns/{column_id}")
def update_custom_column(column_id: int, data: CustomColumnUpdateSchema, db: Session = Depends(get_db)):
    """Обновить название пользовательской колонки"""
    column = db.query(models.CustomColumn).filter(models.CustomColumn.id == column_id).first()
    if not column:
        raise HTTPException(404, "Column not found")
    
    column.column_label = data.column_label
    db.commit()
    db.refresh(column)
    
    return {
        "id": column.id,
        "column_key": column.column_key,
        "column_label": column.column_label,
        "column_order": column.column_order
    }


@app.delete("/api/custom-columns/{column_id}")
def delete_custom_column(column_id: int, db: Session = Depends(get_db)):
    """Удалить пользовательскую колонку"""
    column = db.query(models.CustomColumn).filter(models.CustomColumn.id == column_id).first()
    if not column:
        raise HTTPException(404, "Column not found")
    
    # Удаляем все данные для этой колонки
    if column.table_name == "purchase_orders":
        db.query(models.PurchaseOrderCustomData).filter(
            models.PurchaseOrderCustomData.column_key == column.column_key
        ).delete()
    
    db.delete(column)
    db.commit()
    
    return {"message": "Column deleted successfully"}


@app.get("/api/purchase-order-custom-data")
def get_all_purchase_order_custom_data(db: Session = Depends(get_db)):
    """Получить все данные пользовательских колонок для всех Purchase Orders"""
    custom_data = db.query(models.PurchaseOrderCustomData).all()
    return [
        {
            "purchase_order_id": item.purchase_order_id,
            "column_key": item.column_key,
            "value": item.value
        }
        for item in custom_data
    ]


@app.post("/api/purchase-order-custom-data")
def save_purchase_order_custom_data(data: dict, db: Session = Depends(get_db)):
    """Сохранить данные для пользовательских колонок"""
    purchase_order_id = data.get("purchase_order_id")
    custom_data = data.get("custom_data", {})
    
    if not purchase_order_id:
        raise HTTPException(400, "purchase_order_id is required")
    
    # Для каждой пользовательской колонки сохраняем или обновляем значение
    for column_key, value in custom_data.items():
        existing = db.query(models.PurchaseOrderCustomData).filter(
            models.PurchaseOrderCustomData.purchase_order_id == purchase_order_id,
            models.PurchaseOrderCustomData.column_key == column_key
        ).first()
        
        if existing:
            existing.value = value
        else:
            new_data = models.PurchaseOrderCustomData(
                purchase_order_id=purchase_order_id,
                column_key=column_key,
                value=value
            )
            db.add(new_data)
    
    db.commit()
    return {"message": "Custom data saved successfully"}


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
        engine.install_date = parsed_date or datetime.now(timezone.utc)

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
            "from": l.from_location or "-",
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
    try:
        params = db.query(models.UtilizationParameter).order_by(
            models.UtilizationParameter.date.desc()
        ).all()
        
        result = []
        for p in params:
            # Получаем Orig SN и GSS ID если указана позиция
            orig_sn = None
            gss_sn = None
            if p.position and p.engine_id:
                eng = db.query(models.Engine).filter(models.Engine.id == p.engine_id).first()
                if eng:
                    orig_sn = eng.original_sn
                    gss_sn = eng.gss_sn or eng.original_sn
            
            result.append({
                "id": p.id,
                "date": p.date.strftime("%Y-%m-%d") if p.date else None,
                "aircraft": p.aircraft,
                "position": p.position,
                "orig_sn": orig_sn,
                "gss_sn": gss_sn,
                "ttsn": p.ttsn,
                "tcsn": p.tcsn,
                "period": p.period,
                "date_from": p.date_from.strftime("%Y-%m-%d") if p.date_from else None,
                "date_to": p.date_to.strftime("%Y-%m-%d") if p.date_to else None,
                "created_at": p.created_at.isoformat() if p.created_at else None
            })
        
        return result
    except Exception as e:
        print(f"❌ Error in get_utilization_parameters: {e}")
        return []


@app.post("/api/utilization-parameters")
def create_utilization_parameter(data: UtilizationParameterSchema, db: Session = Depends(get_db)):
    """Create new utilization parameter record"""
    parsed_date = parse_input_date(data.date)
    if not parsed_date:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    # Валидация обязательных полей
    if not data.position or data.position < 1 or data.position > 4:
        raise HTTPException(status_code=400, detail="Position is required and must be between 1 and 4")
    
    if not data.date_from or not data.date_to:
        raise HTTPException(status_code=400, detail="Date From and Date To are required")
    
    parsed_date_from = parse_input_date(data.date_from)
    parsed_date_to = parse_input_date(data.date_to)
    
    if not parsed_date_from or not parsed_date_to:
        raise HTTPException(status_code=400, detail="Invalid date format for date_from or date_to")
    
    # Позиция обязательна - ищем двигатель на этой позиции
    ac = db.query(models.Aircraft).filter(
        models.Aircraft.tail_number == data.aircraft
    ).first()
    
    if not ac:
        raise HTTPException(status_code=404, detail=f"Aircraft {data.aircraft} not found")
    
    engine = db.query(models.Engine).filter(
        models.Engine.aircraft_id == ac.id,
        models.Engine.position == data.position,
        models.Engine.status == "INSTALLED"
    ).first()
    
    engine_id = engine.id if engine else None
    
    new_param = models.UtilizationParameter(
        date=parsed_date,
        aircraft=data.aircraft,
        position=data.position,
        engine_id=engine_id,
        ttsn=data.ttsn,
        tcsn=data.tcsn,
        period=data.period,
        date_from=parsed_date_from,
        date_to=parsed_date_to
    )
    
    db.add(new_param)
    db.commit()
    db.refresh(new_param)

    # Если привязали к конкретному двигателю, обновляем его текущие TT/TC и дату обновления параметров
    if engine_id:
        eng = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
        if eng:
            if data.ttsn is not None:
                eng.total_time = data.ttsn
            if data.tcsn is not None:
                eng.total_cycles = data.tcsn
            eng.last_param_update = datetime.now(timezone.utc)
            db.commit()
            db.refresh(eng)
    
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
    
    # Валидация обязательных полей
    if not data.position or data.position < 1 or data.position > 4:
        raise HTTPException(status_code=400, detail="Position is required and must be between 1 and 4")
    
    if not data.date_from or not data.date_to:
        raise HTTPException(status_code=400, detail="Date From and Date To are required")
    
    parsed_date_from = parse_input_date(data.date_from)
    parsed_date_to = parse_input_date(data.date_to)
    
    if not parsed_date_from or not parsed_date_to:
        raise HTTPException(status_code=400, detail="Invalid date format for date_from or date_to")
    
    # Позиция обязательна - ищем двигатель на этой позиции
    ac = db.query(models.Aircraft).filter(models.Aircraft.tail_number == data.aircraft).first()
    if not ac:
        raise HTTPException(status_code=404, detail=f"Aircraft {data.aircraft} not found")
    
    engine = db.query(models.Engine).filter(
        models.Engine.aircraft_id == ac.id,
        models.Engine.position == data.position,
        models.Engine.status == "INSTALLED"
    ).first()
    engine_id = engine.id if engine else None
    
    param.date = parsed_date
    param.aircraft = data.aircraft
    param.position = data.position
    param.engine_id = engine_id
    param.ttsn = data.ttsn
    param.tcsn = data.tcsn
    param.period = data.period
    param.date_from = parsed_date_from
    param.date_to = parsed_date_to
    
    db.commit()
    db.refresh(param)

    # Если привязали к конкретному двигателю, обновляем его текущие TT/TC и дату обновления параметров
    if engine_id:
        eng = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
        if eng:
            if data.ttsn is not None:
                eng.total_time = data.ttsn
            if data.tcsn is not None:
                eng.total_cycles = data.tcsn
            eng.last_param_update = datetime.now(timezone.utc)
            db.commit()
            db.refresh(eng)
    
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
    
    # Update last login (store naive UTC to match DB schema)
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
def create_user(data: UserCreateSchema, current_user_id: int = Query(..., alias="user_id"), db: Session = Depends(get_db)):
    """Create new user (admin only)"""
    user = db.query(models.User).filter(models.User.id == current_user_id).first()
    if not user or user.role != "admin":
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
def update_user(user_id: int, data: UserUpdateSchema, request: Request, current_user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """Update user (admin only)"""
    # Allow frontend to pass acting admin via ?user_id= without name conflicts
    if current_user_id is None:
        actor_q = request.query_params.get("user_id")
        if actor_q is None:
            raise HTTPException(status_code=422, detail="Missing user_id")
        try:
            current_user_id = int(actor_q)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid user_id")

    user = db.query(models.User).filter(models.User.id == current_user_id).first()
    if not user or user.role != "admin":
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
def delete_user(user_id: int, request: Request, current_user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """Delete user (admin only)"""
    if current_user_id is None:
        actor_q = request.query_params.get("user_id")
        if actor_q is None:
            raise HTTPException(status_code=422, detail="Missing user_id")
        try:
            current_user_id = int(actor_q)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid user_id")

    user = db.query(models.User).filter(models.User.id == current_user_id).first()
    if not user or user.role != "admin":
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


# ============================================================================
# === FAKE INSTALLED API ENDPOINTS (независимый модуль, не трогаем логику) ===
# ============================================================================

@app.get("/api/fake-installed")
def get_fake_installed(engine_sn: Optional[str] = None, db: Session = Depends(get_db)):
    """Получить все записи Fake Installed, опционально отфильтровать по SN двигателя"""
    try:
        if not hasattr(models, "FakeInstalled"):
            print("FakeInstalled model missing")
            return []
        query = db.query(models.FakeInstalled)
        
        if engine_sn:
            query = query.filter(
                or_(
                    models.FakeInstalled.engine_original_sn.ilike(f"%{engine_sn}%"),
                    models.FakeInstalled.engine_current_sn.ilike(f"%{engine_sn}%")
                )
            )
        
        records = query.order_by(models.FakeInstalled.documented_date.desc()).all()
        
        return [
        {
            "id": r.id,
            "engine_id": r.engine_id,
            "engine_original_sn": r.engine_original_sn,
            "engine_current_sn": r.engine_current_sn,
            "aircraft_tail": r.aircraft_tail,
            "position": r.position,
            "documented_date": r.documented_date,
            "documented_reason": r.documented_reason,
            "old_engine_sn": r.old_engine_sn,
            "new_engine_sn": r.new_engine_sn,
            "is_fake": r.is_fake,
            "actual_notes": r.actual_notes,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
    except Exception as e:
        print(f"Error in get_fake_installed: {e}")
        return []


@app.post("/api/fake-installed")
def create_fake_installed(data: dict, db: Session = Depends(get_db)):
    """Добавить новую запись Fake Installed"""
    try:
        if not hasattr(models, "FakeInstalled"):
            raise HTTPException(status_code=500, detail="FakeInstalled model missing")
        record = models.FakeInstalled(
            engine_id=data.get("engine_id"),
            engine_original_sn=data.get("engine_original_sn", ""),
            engine_current_sn=data.get("engine_current_sn", ""),
            aircraft_id=data.get("aircraft_id"),
            aircraft_tail=data.get("aircraft_tail"),
            position=data.get("position"),
            documented_date=data.get("documented_date", ""),
            documented_reason=data.get("documented_reason"),
            old_engine_sn=data.get("old_engine_sn"),
            new_engine_sn=data.get("new_engine_sn"),
            is_fake=data.get("is_fake", True),
            actual_notes=data.get("actual_notes"),
            created_by=data.get("created_by"),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        
        return {
            "id": record.id,
            "message": "Record created successfully",
            "engine_original_sn": record.engine_original_sn
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/fake-installed/{fake_id}")
def update_fake_installed(fake_id: int, data: dict, db: Session = Depends(get_db)):
    """Обновить запись Fake Installed"""
    try:
        if not hasattr(models, "FakeInstalled"):
            raise HTTPException(status_code=500, detail="FakeInstalled model missing")
        record = db.query(models.FakeInstalled).filter(models.FakeInstalled.id == fake_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")
        
        for key, value in data.items():
            if hasattr(record, key):
                setattr(record, key, value)
        
        db.commit()
        db.refresh(record)
        return {"id": record.id, "message": "Record updated"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/fake-installed/{fake_id}")
def delete_fake_installed(fake_id: int, db: Session = Depends(get_db)):
    """Удалить запись Fake Installed"""
    try:
        if not hasattr(models, "FakeInstalled"):
            raise HTTPException(status_code=500, detail="FakeInstalled model missing")
        record = db.query(models.FakeInstalled).filter(models.FakeInstalled.id == fake_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")
        
        db.delete(record)
        db.commit()
        return {"message": "Record deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ----------------------------------------------------------------------------
# Fake Installed Headers Settings (independent of other logic)
# ----------------------------------------------------------------------------

DEFAULT_FAKE_HEADERS = {
    "idx": "#",
    "documented_date": "Date",
    "engine_original_sn": "Engine (Original SN)",
    "engine_current_sn": "Current SN",
    "aircraft_tail": "Aircraft",
    "position": "Pos",
    "documented_reason": "Reason",
    "documented_pair": "Documented",
    "actual_notes": "Reality",
    "actions": "Actions",
}


def _get_settings_row(db: Session):
    if not hasattr(models, "FakeInstalledSettings"):
        class _Dummy:
            headers_json = None
        return _Dummy()
    row = db.query(models.FakeInstalledSettings).first()
    if not row:
        row = models.FakeInstalledSettings(headers_json=None)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@app.get("/api/fake-installed/headers")
def get_fake_installed_headers(db: Session = Depends(get_db)):
    """Return header labels for Fake Installed table."""
    try:
        if not hasattr(models, "FakeInstalledSettings"):
            return DEFAULT_FAKE_HEADERS
        import json as _json
        row = _get_settings_row(db)
        if row.headers_json:
            try:
                data = _json.loads(row.headers_json)
                # ensure defaults present
                for k, v in DEFAULT_FAKE_HEADERS.items():
                    data.setdefault(k, v)
                return data
            except Exception:
                pass
        return DEFAULT_FAKE_HEADERS
    except Exception as e:
        print(f"Error in get_fake_installed_headers: {e}")
        return DEFAULT_FAKE_HEADERS


@app.put("/api/fake-installed/headers")
def update_fake_installed_headers(payload: dict, db: Session = Depends(get_db)):
    """Update header labels mapping. Accepts partial dict of keys->labels."""
    import json as _json
    try:
        if not hasattr(models, "FakeInstalledSettings"):
            raise HTTPException(status_code=500, detail="FakeInstalledSettings model missing")
        current = get_fake_installed_headers(db)
        current.update({k: str(v) for k, v in payload.items() if k in DEFAULT_FAKE_HEADERS})
        row = _get_settings_row(db)
        row.headers_json = _json.dumps(current, ensure_ascii=False)
        db.commit()
        return {"message": "Headers updated", "headers": current}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# === NAMEPLATE TRACKER API (независимый модуль) ===
# ============================================================================

@app.get("/api/engine-by-sn/{sn}")
def get_engine_by_sn(sn: str, db: Session = Depends(get_db)):
    """Lookup engine by serial number for autocomplete form fields."""
    try:
        sn = sn.strip()
        eng = db.query(models.Engine).filter(
            (models.Engine.original_sn.ilike(f"%{sn}%")) | (models.Engine.current_sn.ilike(f"%{sn}%"))
        ).first()
        
        if not eng:
            raise HTTPException(status_code=404, detail="Engine not found")
        
        return {
            "id": eng.id,
            "model": eng.model,
            "gss_id": eng.gss_sn,
            "original_sn": eng.original_sn,
            "current_sn": eng.current_sn,
            "aircraft_tail": eng.aircraft.tail if eng.aircraft else None,
            "position": eng.position,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/nameplate-tracker")
def get_nameplate_tracker(
    nameplate_sn: Optional[str] = None,
    gss_id: Optional[str] = None,
    active_only: Optional[bool] = False,
    db: Session = Depends(get_db)
):
    """Get all nameplate tracker records with optional filters."""
    try:
        if not hasattr(models, "NameplateTracker"):
            print("NameplateTracker model missing")
            return []
        query = db.query(models.NameplateTracker)
        
        if nameplate_sn:
            query = query.filter(models.NameplateTracker.nameplate_sn.ilike(f"%{nameplate_sn}%"))
        
        if gss_id:
            query = query.filter(models.NameplateTracker.gss_id.ilike(f"%{gss_id}%"))
        
        if active_only:
            query = query.filter(models.NameplateTracker.removed_date.is_(None))
        
        records = query.order_by(models.NameplateTracker.installed_date.desc()).all()
        
        return [
        {
            "id": r.id,
            "nameplate_sn": r.nameplate_sn,
            "engine_model": r.engine_model,
            "gss_id": r.gss_id,
            "engine_orig_sn": r.engine_orig_sn,
            "aircraft_tail": r.aircraft_tail,
            "position": r.position,
            "installed_date": r.installed_date,
            "removed_date": r.removed_date,
            "location_type": r.location_type,
            "action_note": r.action_note,
            "performed_by": r.performed_by,
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
    except Exception as e:
        print(f"Error in get_nameplate_tracker: {e}")
        return []


@app.post("/api/nameplate-tracker")
def create_nameplate_tracker(data: dict, db: Session = Depends(get_db)):
    """Create new nameplate tracker record."""
    try:
        record = models.NameplateTracker(
            nameplate_sn=data.get("nameplate_sn", ""),
            engine_model=data.get("engine_model"),
            gss_id=data.get("gss_id"),
            engine_orig_sn=data.get("engine_orig_sn"),
            aircraft_tail=data.get("aircraft_tail"),
            position=data.get("position"),
            installed_date=data.get("installed_date", ""),
            removed_date=data.get("removed_date"),
            location_type=data.get("location_type"),
            action_note=data.get("action_note"),
            performed_by=data.get("performed_by"),
            notes=data.get("notes"),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        
        return {
            "id": record.id,
            "message": "Nameplate record created",
            "nameplate_sn": record.nameplate_sn
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/nameplate-tracker/{record_id}")
def update_nameplate_tracker(record_id: int, data: dict, db: Session = Depends(get_db)):
    """Update nameplate tracker record."""
    try:
        record = db.query(models.NameplateTracker).filter(models.NameplateTracker.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")
        
        for key, value in data.items():
            if hasattr(record, key):
                setattr(record, key, value)
        
        db.commit()
        db.refresh(record)
        return {"id": record.id, "message": "Record updated"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/nameplate-tracker/{record_id}")
def delete_nameplate_tracker(record_id: int, db: Session = Depends(get_db)):
    """Delete nameplate tracker record."""
    try:
        record = db.query(models.NameplateTracker).filter(models.NameplateTracker.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")
        
        db.delete(record)
        db.commit()
        return {"message": "Record deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/nameplate-tracker/actions")
def apply_nameplate_action(data: dict, db: Session = Depends(get_db)):
    """Apply a nameplate action (install/remove/swap/move) and update engines accordingly.

    Uses existing NameplateTracker fields (action_note, gss_id, engine_orig_sn, aircraft_tail, position, location_type)
    to avoid schema migrations. Updates Engine.current_sn to reflect visible serial changes.
    """
    try:
        action_type = (data.get("action_type") or "").strip().lower()
        nameplate_sn = (data.get("nameplate_sn") or "").strip()
        primary_gss_id = (data.get("primary_gss_id") or "").strip()
        primary_engine_sn = (data.get("primary_engine_sn") or "").strip()
        secondary_gss_id = (data.get("secondary_gss_id") or "").strip()
        secondary_engine_sn = (data.get("secondary_engine_sn") or "").strip()
        installed_date = data.get("installed_date")
        removed_date = data.get("removed_date")
        location_type = data.get("location_type")
        target_aircraft_tail = data.get("target_aircraft_tail")
        target_position = data.get("target_position")
        performed_by = data.get("performed_by")
        note = data.get("note")

        if action_type not in {"install", "remove", "swap", "move"}:
            raise HTTPException(status_code=400, detail="Unsupported action_type")

        def _find_engine(gss_id: str, engine_sn: str):
            q = db.query(models.Engine)
            if gss_id:
                eng = q.filter(models.Engine.gss_sn == gss_id).first()
                if eng:
                    return eng
            if engine_sn:
                # Match either original_sn or current_sn
                eng = q.filter((models.Engine.original_sn == engine_sn) | (models.Engine.current_sn == engine_sn)).first()
                if eng:
                    return eng
            return None

        if action_type == "install":
            if not nameplate_sn:
                raise HTTPException(status_code=400, detail="nameplate_sn required for install")
            eng = _find_engine(primary_gss_id, primary_engine_sn)
            if not eng:
                raise HTTPException(status_code=404, detail="Target engine not found")

            # Update engine current serial to nameplate SN
            before_sn = eng.current_sn
            eng.current_sn = nameplate_sn
            db.add(eng)

            # Record tracker
            rec = models.NameplateTracker(
                nameplate_sn=nameplate_sn,
                engine_model=eng.model,
                gss_id=eng.gss_sn,
                engine_orig_sn=eng.original_sn,
                aircraft_tail=target_aircraft_tail,
                position=target_position,
                installed_date=installed_date or datetime.now(timezone.utc).date().isoformat(),
                removed_date=None,
                location_type=location_type,
                action_note="install",
                performed_by=performed_by,
                notes=note,
            )
            db.add(rec)


            db.commit()
            db.refresh(eng)
            return {"message": "Installed", "engine_id": eng.id, "current_sn": eng.current_sn}

        if action_type == "remove":
            # Create a removal record; do not alter engine.current_sn by default
            rec = models.NameplateTracker(
                nameplate_sn=nameplate_sn,
                gss_id=primary_gss_id or None,
                engine_orig_sn=primary_engine_sn or None,
                removed_date=removed_date or datetime.now(timezone.utc).date().isoformat(),
                location_type=location_type,
                action_note="remove",
                performed_by=performed_by,
                notes=note,
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            return {"message": "Removed", "record_id": rec.id}

        if action_type == "move":
            # Movement context update without serial change
            rec = models.NameplateTracker(
                nameplate_sn=nameplate_sn,
                gss_id=primary_gss_id or None,
                engine_orig_sn=primary_engine_sn or None,
                installed_date=installed_date or datetime.now(timezone.utc).date().isoformat(),
                location_type=location_type,
                aircraft_tail=target_aircraft_tail,
                position=target_position,
                action_note="move",
                performed_by=performed_by,
                notes=note,
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            return {"message": "Moved", "record_id": rec.id}

        if action_type == "swap":
            # Swap current_sn between two engines
            eng1 = _find_engine(primary_gss_id, primary_engine_sn)
            eng2 = _find_engine(secondary_gss_id, secondary_engine_sn)
            if not eng1 or not eng2:
                raise HTTPException(status_code=404, detail="Both engines must exist for swap")
            if eng1.id == eng2.id:
                raise HTTPException(status_code=400, detail="Cannot swap within the same engine")

            sn1, sn2 = eng1.current_sn, eng2.current_sn
            eng1.current_sn, eng2.current_sn = sn2, sn1
            db.add(eng1); db.add(eng2)

            # Record a single swap tracker entry (concise) for audit
            rec = models.NameplateTracker(
                nameplate_sn=nameplate_sn or sn1,
                engine_model=eng1.model,
                gss_id=eng1.gss_sn,
                engine_orig_sn=eng1.original_sn,
                installed_date=installed_date or datetime.now(timezone.utc).date().isoformat(),
                location_type=location_type,
                action_note="swap",
                performed_by=performed_by,
                notes=(note or f"swap: {eng1.gss_sn or eng1.id}({sn1}) <-> {eng2.gss_sn or eng2.id}({sn2})"),
            )
            db.add(rec)

            # Note: not writing ActionLog here to avoid enum/type mismatches; NameplateTracker notes capture swap details.

            db.commit()
            return {"message": "Swapped", "engine1_id": eng1.id, "engine2_id": eng2.id}

        raise HTTPException(status_code=400, detail="Unhandled action type")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/nameplate-tracker/execute-action")
def execute_nameplate_action(data: dict, db: Session = Depends(get_db)):
    """Execute swap/remove/install action with transaction safety.
    Updates Engine.current_sn for swap/install and creates NameplateTracker records."""
    try:
        action = (data.get("action") or "").strip().lower()
        
        if action not in {"swap", "remove", "install"}:
            raise HTTPException(status_code=400, detail="Invalid action")
        
        # Helper to find engine by SN
        def _find_eng_by_sn(sn):
            return db.query(models.Engine).filter(
                (models.Engine.original_sn == sn) | (models.Engine.current_sn == sn)
            ).first()
        
        if action == "swap":
            plate1_sn = (data.get("plate1_sn") or "").strip()
            plate2_sn = (data.get("plate2_sn") or "").strip()
            
            if not plate1_sn or not plate2_sn or plate1_sn == plate2_sn:
                raise HTTPException(status_code=400, detail="Both plate SNs required and must be different")
            
            eng1 = _find_eng_by_sn(plate1_sn)
            eng2 = _find_eng_by_sn(plate2_sn)
            
            if not eng1 or not eng2:
                raise HTTPException(status_code=404, detail="One or both engines not found")
            
            # Swap current_sn
            old_sn1, old_sn2 = eng1.current_sn, eng2.current_sn
            eng1.current_sn = old_sn2
            eng2.current_sn = old_sn1
            db.add(eng1)
            db.add(eng2)
            
            # Record swap in tracker
            rec = models.NameplateTracker(
                nameplate_sn=plate1_sn,
                engine_model=eng1.model,
                gss_id=eng1.gss_sn,
                engine_orig_sn=eng1.original_sn,
                aircraft_tail=data.get("aircraft_from"),
                position=data.get("position_from"),
                installed_date=data.get("date") or datetime.now(timezone.utc).date().isoformat(),
                action_note="swap",
                performed_by=data.get("performed_by"),
                notes=f"Swapped: {eng1.gss_sn}({old_sn1}↔{old_sn2}) with {eng2.gss_sn}({old_sn2}↔{old_sn1})",
            )
            db.add(rec)
            db.commit()
            
            return {
                "status": "ok",
                "action": "swap",
                "engine1": {"id": eng1.id, "gss_id": eng1.gss_sn, "new_sn": eng1.current_sn},
                "engine2": {"id": eng2.id, "gss_id": eng2.gss_sn, "new_sn": eng2.current_sn},
            }
        
        if action == "remove":
            plate_sn = (data.get("plate1_sn") or "").strip()
            if not plate_sn:
                raise HTTPException(status_code=400, detail="Plate SN required")
            
            eng = _find_eng_by_sn(plate_sn)
            if not eng:
                raise HTTPException(status_code=404, detail="Engine not found")
            
            rec = models.NameplateTracker(
                nameplate_sn=plate_sn,
                engine_model=eng.model,
                gss_id=eng.gss_sn,
                engine_orig_sn=eng.original_sn,
                aircraft_tail=data.get("aircraft_from"),
                position=data.get("position_from"),
                removed_date=data.get("date") or datetime.now(timezone.utc).date().isoformat(),
                location_type=data.get("sent_to"),
                action_note="remove",
                performed_by=data.get("performed_by"),
                notes=data.get("reason"),
            )
            db.add(rec)
            db.commit()
            
            return {
                "status": "ok",
                "action": "remove",
                "engine_id": eng.id,
            }
        
        if action == "install":
            plate_sn = (data.get("plate1_sn") or "").strip()
            if not plate_sn:
                raise HTTPException(status_code=400, detail="Plate SN required")
            
            eng = _find_eng_by_sn(plate_sn)
            if not eng:
                raise HTTPException(status_code=404, detail="Engine not found")
            
            ac_to = data.get("aircraft_to")
            pos_to = data.get("position_to")
            
            # Update engine location
            if ac_to:
                ac_obj = db.query(models.Aircraft).filter(models.Aircraft.tail == ac_to).first()
                if ac_obj:
                    eng.aircraft_id = ac_obj.id
                    eng.position = pos_to
            
            db.add(eng)
            
            rec = models.NameplateTracker(
                nameplate_sn=plate_sn,
                engine_model=eng.model,
                gss_id=eng.gss_sn,
                engine_orig_sn=eng.original_sn,
                aircraft_tail=ac_to,
                position=pos_to,
                installed_date=data.get("date") or datetime.now(timezone.utc).date().isoformat(),
                location_type="Aircraft",
                action_note="install",
                performed_by=data.get("performed_by"),
                notes=data.get("reason"),
            )
            db.add(rec)
            db.commit()
            
            return {
                "status": "ok",
                "action": "install",
                "engine_id": eng.id,
                "aircraft": ac_to,
                "position": pos_to,
            }
    
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================
# LOGISTICS & SCHEDULES API ENDPOINTS
# ============================================================

@app.get("/api/schedules")
def get_all_schedules(
    shipment_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get all shipments with optional filtering"""
    try:
        query = db.query(models.Shipment)
        
        if shipment_type and shipment_type != 'ALL':
            query = query.filter(models.Shipment.shipment_type == shipment_type)
        
        if status and status != 'ALL':
            query = query.filter(models.Shipment.status == status)
        
        shipments = query.order_by(models.Shipment.expected_delivery_date.desc()).all()
        
        result = []
        for s in shipments:
            result.append({
                "id": s.id,
                "shipment_type": s.shipment_type,
                "status": s.status,
                "engine_id": s.engine_id,
                "destination_location": s.destination_location,
                "part_name": s.part_name,
                "part_category": s.part_category,
                "part_quantity": s.part_quantity,
                "reserved_quantity": s.reserved_quantity,
                "departure_date": s.departure_date.isoformat() if s.departure_date else None,
                "expected_delivery_date": s.expected_delivery_date.isoformat() if s.expected_delivery_date else None,
                "actual_delivery_date": s.actual_delivery_date.isoformat() if s.actual_delivery_date else None,
                "supplier_name": s.supplier_name,
                "tracking_number": s.tracking_number,
                "notes": s.notes,
                "created_by": s.created_by,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_by": s.updated_by,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None
            })
        
        return result
    except Exception as e:
        print(f"❌ Error in get_all_schedules: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to fetch schedules: {str(e)}")


@app.get("/api/schedules/stats")
def get_schedule_stats(db: Session = Depends(get_db)):
    """Get schedule statistics for dashboard"""
    try:
        from datetime import datetime, timedelta
        
        # On order (PLANNED)
        on_order = db.query(models.Shipment).filter(
            models.Shipment.status == "PLANNED"
        ).count()
        
        # In transit
        in_transit = db.query(models.Shipment).filter(
            models.Shipment.status == "IN_TRANSIT"
        ).count()
        
        # Arriving soon (next 7 days)
        now = datetime.now(timezone.utc)
        next_week = now + timedelta(days=7)
        
        # Use separate conditions to handle potential type issues
        arriving_soon_query = db.query(models.Shipment).filter(
            models.Shipment.status.in_(["PLANNED", "IN_TRANSIT"])
        ).all()
        
        arriving_soon = 0
        for s in arriving_soon_query:
            if s.expected_delivery_date:
                try:
                    if isinstance(s.expected_delivery_date, str):
                        exp_dt = datetime.fromisoformat(s.expected_delivery_date)
                    else:
                        exp_dt = s.expected_delivery_date
                    if now <= exp_dt <= next_week:
                        arriving_soon += 1
                except:
                    pass
        
        # Total active
        total_active = db.query(models.Shipment).filter(
            ~models.Shipment.status.in_(["DELIVERED", "CANCELLED"])
        ).count()
        
        # Pending deliveries
        pending = db.query(models.Shipment).filter(
            models.Shipment.status.in_(["PLANNED", "IN_TRANSIT", "DELAYED"])
        ).count()
        
        # Completed this month
        start_of_month = datetime(now.year, now.month, 1)
        completed_month_query = db.query(models.Shipment).filter(
            models.Shipment.status == "DELIVERED"
        ).all()
        
        completed_month = 0
        for s in completed_month_query:
            if s.actual_delivery_date:
                try:
                    if isinstance(s.actual_delivery_date, str):
                        del_dt = datetime.fromisoformat(s.actual_delivery_date)
                    else:
                        del_dt = s.actual_delivery_date
                    if del_dt >= start_of_month:
                        completed_month += 1
                except:
                    pass
        
        print(f"✅ Schedule stats: on_order={on_order}, in_transit={in_transit}, arriving_soon={arriving_soon}")
        
        return {
            "on_order": on_order,
            "in_transit": in_transit,
            "arriving_soon": arriving_soon,
            "total_active": total_active,
            "pending": pending,
            "completed_month": completed_month
        }
    except Exception as e:
        print(f"❌ Error in get_schedule_stats: {e}")
        import traceback
        traceback.print_exc()
        return {
            "on_order": 0,
            "in_transit": 0,
            "arriving_soon": 0,
            "total_active": 0,
            "pending": 0,
            "completed_month": 0
        }


@app.get("/api/schedules/{shipment_id}")
def get_schedule_by_id(shipment_id: int, db: Session = Depends(get_db)):
    """Get single shipment by ID"""
    try:
        s = db.query(models.Shipment).filter(models.Shipment.id == shipment_id).first()
        if not s:
            raise HTTPException(404, f"Shipment not found (ID: {shipment_id})")
        
        return {
            "id": s.id,
            "shipment_type": s.shipment_type,
            "status": s.status,
            "engine_id": s.engine_id,
            "destination_location": s.destination_location,
            "part_name": s.part_name,
            "part_category": s.part_category,
            "part_quantity": s.part_quantity,
            "reserved_quantity": s.reserved_quantity,
            "departure_date": s.departure_date.isoformat() if s.departure_date else None,
            "expected_delivery_date": s.expected_delivery_date.isoformat() if s.expected_delivery_date else None,
            "actual_delivery_date": s.actual_delivery_date.isoformat() if s.actual_delivery_date else None,
            "supplier_name": s.supplier_name,
            "tracking_number": s.tracking_number,
            "notes": s.notes,
            "created_by": s.created_by,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_by": s.updated_by,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in get_schedule_by_id: {e}")
        raise HTTPException(500, f"Failed to fetch shipment: {str(e)}")


@app.post("/api/schedules")
def create_schedule(data: LogisticsShipmentSchema, db: Session = Depends(get_db)):
    """Create new shipment and auto-create calendar event"""
    try:
        # Parse dates
        departure = datetime.fromisoformat(data.departure_date) if data.departure_date else None
        expected = datetime.fromisoformat(data.expected_delivery_date)
        
        # Create shipment
        shipment = models.Shipment(
            shipment_type=data.shipment_type,
            status=data.status or "PLANNED",
            engine_id=data.engine_id,
            engine_model=data.engine_model,
            gss_id=data.gss_id,
            destination_location=data.destination_location,
            part_name=data.part_name,
            part_category=data.part_category,
            part_quantity=data.part_quantity,
            reserved_quantity=data.reserved_quantity or 0,
            departure_date=departure,
            expected_delivery_date=expected,
            supplier_name=data.supplier_name,
            tracking_number=data.tracking_number,
            notes=data.notes,
            created_by=data.created_by or "User"
        )
        db.add(shipment)
        db.flush()  # Get ID before commit
        
        # Auto-create calendar event
        if data.shipment_type == "ENGINE":
            engine = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
            engine_sn = engine.original_sn or engine.current_sn or 'Unknown' if engine else 'Unknown'
            event_title = f"🛫 Engine {engine_sn} Expected Arrival"
            event_desc = f"Supplier: {data.supplier_name}, Destination: {data.destination_location}"
        else:  # PARTS
            event_title = f"📦 Parts: {data.part_quantity}x {data.part_name} Expected"
            event_desc = f"Supplier: {data.supplier_name}, Category: {data.part_category}"
        
        calendar_event = models.ScheduledEvent(
            event_date=expected.strftime("%Y-%m-%d"),
            event_time=expected.strftime("%H:%M"),
            event_type="SHIPMENT",
            title=event_title,
            description=event_desc,
            status="PLANNED",
            priority="MEDIUM",
            color="#667eea" if data.shipment_type == "ENGINE" else "#9f7aea",
            created_by=data.created_by or "User"
        )
        db.add(calendar_event)
        
        # Create notification
        create_notification(
            db,
            action_type="created",
            entity_type="shipment",
            entity_id=shipment.id,
            message=f"📦 Shipment #{shipment.id} created: {event_title}",
            performed_by=data.created_by or "User"
        )
        
        db.commit()
        db.refresh(shipment)
        
        return {
            "id": shipment.id,
            "message": f"Shipment created successfully (ID: {shipment.id})",
            "calendar_event_created": True
        }
    except Exception as e:
        db.rollback()
        print(f"❌ Error in create_schedule: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to create shipment: {str(e)}")


@app.put("/api/schedules/{shipment_id}")
def update_schedule(shipment_id: int, data: dict, db: Session = Depends(get_db)):
    """Update shipment and trigger cascading updates on DELIVERED status"""
    try:
        shipment = db.query(models.Shipment).filter(models.Shipment.id == shipment_id).first()
        if not shipment:
            raise HTTPException(404, f"Shipment not found (ID: {shipment_id})")
        
        old_status = shipment.status
        new_status = data.get("status", shipment.status)
        
        # Update shipment fields
        if "status" in data:
            shipment.status = data["status"]
        if "departure_date" in data and data["departure_date"]:
            shipment.departure_date = datetime.fromisoformat(data["departure_date"])
        if "expected_delivery_date" in data and data["expected_delivery_date"]:
            shipment.expected_delivery_date = datetime.fromisoformat(data["expected_delivery_date"])
        if "actual_delivery_date" in data and data["actual_delivery_date"]:
            shipment.actual_delivery_date = datetime.fromisoformat(data["actual_delivery_date"])
        if "supplier_name" in data:
            shipment.supplier_name = data["supplier_name"]
        if "tracking_number" in data:
            shipment.tracking_number = data["tracking_number"]
        if "notes" in data:
            shipment.notes = data["notes"]
        if "updated_by" in data:
            shipment.updated_by = data["updated_by"]
        
        # CASCADE LOGIC: DELIVERED status
        if new_status == "DELIVERED" and old_status != "DELIVERED":
            if shipment.shipment_type == "ENGINE" and shipment.engine_id:
                # Update engine location to "On Stock"
                engine = db.query(models.Engine).filter(models.Engine.id == shipment.engine_id).first()
                if engine:
                    # Find or create "On Stock" location
                    on_stock_loc = db.query(models.Location).filter(models.Location.name == "On Stock").first()
                    if not on_stock_loc:
                        on_stock_loc = models.Location(name="On Stock", city="Warehouse")
                        db.add(on_stock_loc)
                        db.flush()
                    
                    engine.location_id = on_stock_loc.id
                    
                    # Create notification
                    create_notification(
                        db,
                        action_type="received",
                        entity_type="engine",
                        entity_id=engine.id,
                        message=f"🛬 Engine {engine.serial_number} RECEIVED - Location updated to On Stock",
                        performed_by=data.get("updated_by", "User")
                    )
            
            elif shipment.shipment_type == "PARTS":
                # Create store_items entry (auto-inventory)
                if shipment.part_name and shipment.part_quantity:
                    # Use only valid StoreItem fields
                    store_item = models.StoreItem(
                        part_name=shipment.part_name,
                        part_number=f"AUTO-{shipment.id}",
                        serial_number=None,
                        condition=shipment.part_category or None,
                        quantity=shipment.part_quantity,
                        unit=None,
                        location=shipment.destination_location or None,
                        shelf=None,
                        owner=shipment.supplier_name or "Unknown",
                        remarks=(
                            f"Auto-created from shipment #{shipment.id}; "
                            f"category={shipment.part_category or 'N/A'}; "
                            f"tracking={shipment.tracking_number or 'N/A'}"
                        ),
                        received_date=shipment.actual_delivery_date or datetime.now(timezone.utc)
                    )
                    db.add(store_item)
                    
                    # Clear reserved_quantity
                    shipment.reserved_quantity = 0
                    
                    # Create notification
                    create_notification(
                        db,
                        action_type="received",
                        entity_type="parts",
                        entity_id=store_item.id,
                        message=f"📦 {shipment.part_quantity}x {shipment.part_name} RECEIVED - Added to inventory",
                        performed_by=data.get("updated_by", "User")
                    )
            
            # Update calendar event to COMPLETED
            calendar_events = db.query(models.ScheduledEvent).filter(
                models.ScheduledEvent.event_type == "SHIPMENT",
                models.ScheduledEvent.title.like(f"%{shipment.id}%")
            ).all()
            for event in calendar_events:
                event.status = "COMPLETED"
        
        # Notification for status change
        if old_status != new_status:
            create_notification(
                db,
                action_type="updated",
                entity_type="shipment",
                entity_id=shipment.id,
                message=f"📦 Shipment #{shipment.id} status changed: {old_status} → {new_status}",
                performed_by=data.get("updated_by", "User")
            )
        
        db.commit()
        db.refresh(shipment)
        
        return {"message": f"Shipment #{shipment.id} updated successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error in update_schedule: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to update shipment: {str(e)}")


@app.delete("/api/schedules/{shipment_id}")
def delete_schedule(shipment_id: int, deleted_by: str = Query("User"), db: Session = Depends(get_db)):
    """Delete shipment and clear reserved quantities"""
    try:
        shipment = db.query(models.Shipment).filter(models.Shipment.id == shipment_id).first()
        if not shipment:
            raise HTTPException(404, f"Shipment not found (ID: {shipment_id})")
        
        shipment_type = shipment.shipment_type
        shipment_info = f"{shipment.part_name}" if shipment_type == "PARTS" else f"Engine ID {shipment.engine_id}"
        
        # Delete related calendar events
        calendar_events = db.query(models.ScheduledEvent).filter(
            models.ScheduledEvent.event_type == "SHIPMENT",
            models.ScheduledEvent.title.like(f"%{shipment.id}%")
        ).all()
        for event in calendar_events:
            db.delete(event)
        
        # Create notification
        create_notification(
            db,
            action_type="deleted",
            entity_type="shipment",
            entity_id=shipment_id,
            message=f"📦 Shipment #{shipment_id} ({shipment_info}) deleted",
            performed_by=deleted_by
        )
        
        db.delete(shipment)
        db.commit()
        
        return {"message": f"Shipment #{shipment_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error in delete_schedule: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to delete shipment: {str(e)}")


@app.get("/api/schedules/calendar/{year}/{month}")
def get_schedules_calendar(year: int, month: int, db: Session = Depends(get_db)):
    """Get shipments for calendar display"""
    try:
        # Get all shipments in this month
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)
        
        shipments = db.query(models.Shipment).filter(
            models.Shipment.expected_delivery_date >= start_date,
            models.Shipment.expected_delivery_date < end_date
        ).all()
        
        events = []
        for s in shipments:
            events.append({
                "id": s.id,
                "date": s.expected_delivery_date.strftime("%Y-%m-%d"),
                "type": s.shipment_type,
                "status": s.status,
                "title": f"{s.part_name if s.shipment_type == 'PARTS' else 'Engine'} - {s.supplier_name}",
                "supplier": s.supplier_name,
                "tracking": s.tracking_number
            })
        
        return events
    except Exception as e:
        print(f"❌ Error in get_schedules_calendar: {e}")
        raise HTTPException(500, f"Failed to fetch calendar data: {str(e)}")


# ============================================================
# STATISTICS ENDPOINTS FOR DASHBOARD
# ============================================================

@app.get("/api/store/balance")
def get_store_balance(db: Session = Depends(get_db)):
    """Get store balance statistics"""
    try:
        total = db.query(models.StoreItem).count()
        
        return {"total": total}
    except Exception as e:
        print(f"❌ Error in get_store_balance: {e}")
        return {"total": 0}


@app.get("/api/logistics/movements")
def get_logistics_movements(db: Session = Depends(get_db)):
    """Get logistics and movements statistics"""
    try:
        # Engines in transit
        engines_transit = db.query(models.Shipment).filter(
            models.Shipment.shipment_type == "ENGINE",
            models.Shipment.status == "IN_TRANSIT"
        ).count()
        
        # Parts shipments
        parts_transit = db.query(models.Shipment).filter(
            models.Shipment.shipment_type == "PARTS",
            models.Shipment.status == "IN_TRANSIT"
        ).count()
        
        # Location changes (last 24 hours)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        location_changes = db.query(models.ActionLog).filter(
            models.ActionLog.action_type == "SHIP",
            models.ActionLog.created_at >= yesterday
        ).count()
        
        total = engines_transit + parts_transit + location_changes
        
        return {
            "engines_transit": engines_transit,
            "parts_transit": parts_transit,
            "location_changes": location_changes,
            "total": total
        }
    except Exception as e:
        print(f"❌ Error in get_logistics_movements: {e}")
        return {
            "engines_transit": 0,
            "parts_transit": 0,
            "location_changes": 0,
            "total": 0
        }


# --- CONDITION STATUSES API (Store Balance) ---

@app.get("/api/condition-statuses")
def get_condition_statuses(db: Session = Depends(get_db)):
    """Получить все статусы Condition"""
    try:
        statuses = db.query(models.ConditionStatus).all()
        return [{"id": s.id, "name": s.name, "color": s.color} for s in statuses]
    except Exception as e:
        print(f"❌ Error in get_condition_statuses: {e}")
        return []

@app.post("/api/condition-statuses")
def create_condition_status(data: dict, db: Session = Depends(get_db)):
    """Создать новый статус Condition"""
    try:
        name = data.get("name", "").strip()
        color = data.get("color", "#6c757d")
        
        if not name:
            return {"status": "error", "message": "Name is required"}
        
        # Проверка на дубликат
        existing = db.query(models.ConditionStatus).filter(models.ConditionStatus.name == name).first()
        if existing:
            return {"status": "error", "message": "Status already exists"}
        
        new_status = models.ConditionStatus(name=name, color=color)
        db.add(new_status)
        db.commit()
        db.refresh(new_status)
        return {"status": "success", "id": new_status.id, "name": new_status.name, "color": new_status.color}
    except Exception as e:
        print(f"❌ Error in create_condition_status: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.delete("/api/condition-statuses/{status_id}")
def delete_condition_status(status_id: int, db: Session = Depends(get_db)):
    """Удалить статус Condition"""
    try:
        status = db.query(models.ConditionStatus).filter(models.ConditionStatus.id == status_id).first()
        if not status:
            return {"status": "error", "message": "Status not found"}
        
        db.delete(status)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Error in delete_condition_status: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}

# ========================================
# WORK TYPES (Borescope)
# ========================================

@app.get("/api/work-types")
def get_work_types(db: Session = Depends(get_db)):
    """Получить все типы работ для Borescope"""
    try:
        work_types = db.query(models.WorkType).all()
        return [{"id": wt.id, "name": wt.name} for wt in work_types]
    except Exception as e:
        print(f"❌ Error in get_work_types: {e}")
        return []

@app.post("/api/work-types")
def create_work_type(data: dict, db: Session = Depends(get_db)):
    """Создать новый тип работы"""
    try:
        name = data.get("name", "").strip()
        
        if not name:
            return {"status": "error", "message": "Name is required"}
        
        # Проверка на дубликат
        existing = db.query(models.WorkType).filter(models.WorkType.name == name).first()
        if existing:
            return {"status": "error", "message": "Work Type already exists"}
        
        new_work_type = models.WorkType(name=name)
        db.add(new_work_type)
        db.commit()
        db.refresh(new_work_type)
        return {"status": "success", "id": new_work_type.id, "name": new_work_type.name}
    except Exception as e:
        print(f"❌ Error in create_work_type: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.delete("/api/work-types/{work_type_id}")
def delete_work_type(work_type_id: int, db: Session = Depends(get_db)):
    """Удалить тип работы"""
    try:
        work_type = db.query(models.WorkType).filter(models.WorkType.id == work_type_id).first()
        if not work_type:
            return {"status": "error", "message": "Work Type not found"}
        
        db.delete(work_type)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Error in delete_work_type: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}

# ============================================
# GSS ASSIGNMENT ENDPOINTS
# ============================================
UPLOAD_DIR = Path("uploads/gss_photos")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_GSS_RANGE = 30

@app.get("/api/gss/range")
def get_gss_range(
    from_id: int = Query(..., ge=1),
    to_id: int = Query(..., ge=1),
    show_assigned: bool = Query(default=False),
    db: Session = Depends(get_db)
):
    """Получить диапазон GSS ID с информацией о доступности"""
    try:
        # Проверка ограничения
        if to_id - from_id + 1 > MAX_GSS_RANGE:
            raise HTTPException(400, f"Range too large! Maximum {MAX_GSS_RANGE} numbers at once")
        
        if from_id > to_id:
            raise HTTPException(400, "Invalid range: from_id > to_id")
        
        # Получаем занятые GSS ID в диапазоне
        assigned = db.query(models.GSSAssignment).filter(
            models.GSSAssignment.gss_id.between(from_id, to_id)
        ).all()
        
        assigned_map = {a.gss_id: a for a in assigned}
        
        result = []
        for gss_id in range(from_id, to_id + 1):
            is_assigned = gss_id in assigned_map
            
            # Если show_assigned=False, пропускаем занятые
            if not show_assigned and is_assigned:
                continue
            
            item = {
                "gss_id": gss_id,
                "is_assigned": is_assigned,
                "engine_info": None
            }
            
            if is_assigned:
                a = assigned_map[gss_id]
                item["engine_info"] = {
                    "original_sn": a.original_sn,
                    "current_sn": a.current_sn,
                    "model": a.engine.model if a.engine else None,
                    "assigned_by": a.user.username if a.user else "Unknown"
                }
            
            result.append(item)
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in get_gss_range: {e}")
        raise HTTPException(500, f"Server error: {str(e)}")

@app.post("/api/gss/assign")
def assign_gss_id(
    data: GSSAssignmentCreate,
    current_user_id: int = Query(..., alias="user_id"),
    db: Session = Depends(get_db)
):
    """Присвоить GSS ID к двигателю"""
    try:
        # Проверка: GSS ID уже занят?
        existing = db.query(models.GSSAssignment).filter(
            models.GSSAssignment.gss_id == data.gss_id
        ).first()
        
        if existing:
            raise HTTPException(400, f"GSS ID {data.gss_id} already assigned to engine {existing.original_sn}")
        
        # Получаем двигатель
        engine = db.query(models.Engine).filter(models.Engine.id == data.engine_id).first()
        if not engine:
            raise HTTPException(404, "Engine not found")
        
        # Создаем присвоение
        assignment = models.GSSAssignment(
            gss_id=data.gss_id,
            engine_id=engine.id,
            original_sn=engine.original_sn,
            current_sn=data.current_sn or engine.current_sn,
            photo_url=data.photo_url,
            remarks=data.remarks,
            assigned_by=current_user_id
        )
        
        # Обновляем gss_sn в Engine
        engine.gss_sn = str(data.gss_id)
        
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        
        return {"message": "GSS ID assigned successfully", "gss_id": data.gss_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in assign_gss_id: {e}")
        db.rollback()
        raise HTTPException(500, f"Server error: {str(e)}")

@app.put("/api/gss/edit/{gss_id}")
def edit_gss_assignment(
    gss_id: int,
    data: GSSAssignmentUpdate,
    db: Session = Depends(get_db)
):
    """Редактировать присвоение GSS ID"""
    try:
        assignment = db.query(models.GSSAssignment).filter(
            models.GSSAssignment.gss_id == gss_id
        ).first()
        
        if not assignment:
            raise HTTPException(404, "GSS assignment not found")
        
        # Обновляем поля
        if data.current_sn is not None:
            assignment.current_sn = data.current_sn
        if data.photo_url is not None:
            assignment.photo_url = data.photo_url
        if data.remarks is not None:
            assignment.remarks = data.remarks
        
        db.commit()
        db.refresh(assignment)
        
        return {"message": "GSS assignment updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in edit_gss_assignment: {e}")
        db.rollback()
        raise HTTPException(500, f"Server error: {str(e)}")

@app.post("/api/gss/upload-photo/{gss_id}")
async def upload_gss_photo(
    gss_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Загрузка фото для GSS ID"""
    try:
        from fastapi import UploadFile, File, Form
        form = await request.form()
        file = form.get("file")
        
        if not file:
            raise HTTPException(400, "No file provided")
        
        # Проверка расширения
        allowed_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        file_ext = Path(file.filename).suffix.lower()
        
        if file_ext not in allowed_ext:
            raise HTTPException(400, "Invalid file type")
        
        # Сохраняем файл
        filename = f"gss_{gss_id}_{int(datetime.now().timestamp())}{file_ext}"
        file_path = UPLOAD_DIR / filename
        
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        # Обновляем БД
        assignment = db.query(models.GSSAssignment).filter(
            models.GSSAssignment.gss_id == gss_id
        ).first()
        
        if assignment:
            assignment.photo_filename = filename
            db.commit()
        
        return {
            "message": "Photo uploaded successfully",
            "filename": filename,
            "url": f"/uploads/gss_photos/{filename}"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in upload_gss_photo: {e}")
        raise HTTPException(500, f"Server error: {str(e)}")

@app.get("/api/gss/history")
def get_gss_history(
    gss_id: Optional[int] = None,
    engine_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Получить историю присвоений GSS ID"""
    try:
        query = db.query(models.GSSAssignment)
        
        if gss_id:
            query = query.filter(models.GSSAssignment.gss_id == gss_id)
        
        if engine_id:
            query = query.filter(models.GSSAssignment.engine_id == engine_id)
        
        # Сортировка: старые внизу, новые вверху
        assignments = query.order_by(models.GSSAssignment.assigned_date.asc()).all()
        
        result = []
        for a in assignments:
            result.append({
                "id": a.id,
                "gss_id": a.gss_id,
                "engine_id": a.engine_id,
                "original_sn": a.original_sn,
                "current_sn": a.current_sn,
                "photo_url": a.photo_url,
                "photo_filename": a.photo_filename,
                "remarks": a.remarks,
                "assigned_by": a.assigned_by,
                "assigned_by_name": a.user.username if a.user else "Unknown",
                "assigned_date": a.assigned_date.isoformat() if a.assigned_date else None,
                "engine_model": a.engine.model if a.engine else None,
                "engine_location": a.engine.location.name if a.engine and a.engine.location else None
            })
        
        return result
    except Exception as e:
        print(f"❌ Error in get_gss_history: {e}")
        raise HTTPException(500, f"Server error: {str(e)}")

@app.delete("/api/gss/delete/{gss_id}")
def delete_gss_assignment(
    gss_id: int,
    db: Session = Depends(get_db)
):
    """Удалить присвоение GSS ID (освобождает номер)"""
    try:
        assignment = db.query(models.GSSAssignment).filter(
            models.GSSAssignment.gss_id == gss_id
        ).first()
        
        if not assignment:
            raise HTTPException(404, "GSS assignment not found")
        
        # Очищаем gss_sn в Engine
        if assignment.engine:
            assignment.engine.gss_sn = None
        
        # Удаляем запись
        db.delete(assignment)
        db.commit()
        
        return {"message": f"GSS ID {gss_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in delete_gss_assignment: {e}")
        db.rollback()
        raise HTTPException(500, f"Server error: {str(e)}")


# ==================== MODAL ENGINE HISTORY & ANALYTICS ====================

@app.get("/api/aircraft/{aircraft_id}/engines/{engine_id}/modal-history")
def get_engine_modal_history(aircraft_id: int, engine_id: int, db: Session = Depends(get_db)):
    """
    Возвращает историю двигателя для модального окна:
    - Установки/снятие с самолетов
    - Боroscope инспекции
    - Запчасти установленные
    """
    try:
        engine = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
        if not engine:
            raise HTTPException(404, "Engine not found")

        aircraft = db.query(models.Aircraft).filter(models.Aircraft.id == aircraft_id).first()
        if not aircraft:
            raise HTTPException(404, "Aircraft not found")

        # 1. ACTION LOGS (INSTALL, REMOVE)
        logs = db.query(models.ActionLog).filter(
            models.ActionLog.engine_id == engine_id,
            models.ActionLog.action_type.in_(["INSTALL", "REMOVE"])
        ).order_by(models.ActionLog.date.asc()).all()

        history_items = []
        for log in logs:
            if log.action_type == "INSTALL":
                history_items.append({
                    "date": log.date.strftime('%Y-%m-%d') if log.date else "N/A",
                    "action": "INSTALL",
                    "aircraft": log.to_aircraft or "Unknown",
                    "position": log.position,
                    "tt_at_install": log.snapshot_tt or 0,
                    "tc_at_install": log.snapshot_tc or 0,
                    "description": f"Installed on {log.to_aircraft} at position {log.position}"
                })
            elif log.action_type == "REMOVE":
                history_items.append({
                    "date": log.date.strftime('%Y-%m-%d') if log.date else "N/A",
                    "action": "REMOVE",
                    "aircraft": log.from_location or "Unknown",
                    "position": log.position,
                    "tt_at_removal": log.snapshot_tt or 0,
                    "tc_at_removal": log.snapshot_tc or 0,
                    "condition": log.condition_1_at_removal or "SV",
                    "description": f"Removed from {log.from_location} (Condition: {log.condition_1_at_removal or 'N/A'})"
                })

        # 2. BORESCOPE INSPECTIONS
        boroscopes = db.query(models.BoroscopeInspection).filter(
            models.BoroscopeInspection.serial_number == engine.original_sn
        ).order_by(models.BoroscopeInspection.date.desc()).all()

        for boroscope in boroscopes:
            history_items.append({
                "date": boroscope.date or "N/A",
                "action": "BOROSCOPE",
                "aircraft": boroscope.aircraft,
                "position": boroscope.position,
                "inspector": boroscope.inspector,
                "work_type": boroscope.work_type,
                "comment": boroscope.comment or "",
                "link": boroscope.link or "",
                "description": f"Borescope inspection by {boroscope.inspector} ({boroscope.work_type})"
            })

        # 3. PARTS INSTALLED
        parts = db.query(models.Part).filter(models.Part.engine_id == engine_id).all()
        for part in parts:
            history_items.append({
                "date": "N/A",
                "action": "PART_INSTALLED",
                "part_name": part.name,
                "part_number": part.part_number,
                "part_sn": part.serial_number or "N/A",
                "description": f"Part installed: {part.name} ({part.part_number})"
            })

        # Сортируем по дате (новые сверху)
        history_items.sort(key=lambda x: x.get('date', ''), reverse=True)

        return {
            "engine_sn": engine.original_sn,
            "engine_current_sn": engine.current_sn,
            "gss_id": engine.gss_sn or "N/A",
            "model": engine.model or "N/A",
            "status": engine.status or "N/A",
            "condition_1": engine.condition_1 or "N/A",
            "condition_2": engine.condition_2 or "N/A",
            "total_time": engine.total_time or 0,
            "total_cycles": engine.total_cycles or 0,
            "history": history_items
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in get_engine_modal_history: {e}")
        raise HTTPException(500, f"Server error: {str(e)}")


@app.get("/api/aircraft/{aircraft_id}/engines/{engine_id}/parameters-data")
def get_engine_parameters_data(aircraft_id: int, engine_id: int, months: int = 12, db: Session = Depends(get_db)):
    """
    Возвращает историю параметров двигателя для графиков:
    - N1 Takeoff/Cruise
    - N2 Takeoff/Cruise
    - EGT Takeoff/Cruise
    - Engine swap history за последние месяцы
    """
    try:
        engine = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
        if not engine:
            raise HTTPException(404, "Engine not found")

        aircraft = db.query(models.Aircraft).filter(models.Aircraft.id == aircraft_id).first()
        if not aircraft:
            raise HTTPException(404, "Aircraft not found")

        # 1. ENGINE PARAMETERS (N1, N2, EGT) - ВСЕ ДАННЫЕ
        # Убираем ограничение по месяцам - показываем полную историю
        
        param_history = db.query(models.EngineParameterHistory).filter(
            models.EngineParameterHistory.engine_id == engine_id
        ).order_by(models.EngineParameterHistory.date.asc()).all()

        parameters_data = []
        for param in param_history:
            parameters_data.append({
                "date": param.date.strftime('%Y-%m-%d') if param.date else "N/A",
                "n1_takeoff": param.n1_takeoff,
                "n1_cruise": param.n1_cruise,
                "n2_takeoff": param.n2_takeoff,
                "n2_cruise": param.n2_cruise,
                "egt_takeoff": param.egt_takeoff,
                "egt_cruise": param.egt_cruise
            })

        # 2. ENGINE SWAP HISTORY - вся история
        swap_history = db.query(models.ActionLog).filter(
            models.ActionLog.to_aircraft == aircraft.tail_number,
            models.ActionLog.action_type == "INSTALL"
        ).order_by(models.ActionLog.date.asc()).all()

        swap_timeline = {}
        for log in swap_history:
            date_key = log.date.strftime('%Y-%m-%d') if log.date else "N/A"
            if log.position not in swap_timeline:
                swap_timeline[log.position] = []
            swap_timeline[log.position].append(date_key)

        # Считаем количество swap'ов за месяцы
        monthly_swaps = {}
        for log in swap_history:
            if log.position == engine.position or log.position is None:
                month_key = log.date.strftime('%Y-%m') if log.date else "N/A"
                if month_key not in monthly_swaps:
                    monthly_swaps[month_key] = 0
                monthly_swaps[month_key] += 1

        return {
            "engine_sn": engine.original_sn,
            "engine_current_sn": engine.current_sn,
            "gss_id": engine.gss_sn or "N/A",
            "parameters": parameters_data,
            "swap_timeline": swap_timeline,
            "monthly_swaps": monthly_swaps,
            "total_swaps": len(swap_history)
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in get_engine_parameters_data: {e}")
        raise HTTPException(500, f"Server error: {str(e)}")


# ==================== EMAIL REPORTING ====================

class EmailReportRequest(BaseModel):
    recipient_email: str
    subject: str = "Engine Report"
    aircraft_id: int
    engine_id: int

@app.post("/api/aircraft/{aircraft_id}/engines/{engine_id}/send-report")
def send_engine_report_email(
    aircraft_id: int,
    engine_id: int,
    request_data: EmailReportRequest,
    db: Session = Depends(get_db)
):
    """
    Отправляет отчет о двигателе на email (Outlook/SMTP)
    """
    try:
        engine = db.query(models.Engine).filter(models.Engine.id == engine_id).first()
        if not engine:
            raise HTTPException(404, "Engine not found")

        aircraft = db.query(models.Aircraft).filter(models.Aircraft.id == aircraft_id).first()
        if not aircraft:
            raise HTTPException(404, "Aircraft not found")

        # Получаем историю
        logs = db.query(models.ActionLog).filter(
            models.ActionLog.engine_id == engine_id,
            models.ActionLog.action_type.in_(["INSTALL", "REMOVE"])
        ).order_by(models.ActionLog.date.asc()).all()

        # Формируем HTML письма
        history_html = "<ul style='color: #333;'>"
        for log in logs:
            if log.action_type == "INSTALL":
                history_html += f"<li><strong>{log.date.strftime('%Y-%m-%d')}</strong> - INSTALL на {log.to_aircraft} (Позиция {log.position})</li>"
            elif log.action_type == "REMOVE":
                history_html += f"<li><strong>{log.date.strftime('%Y-%m-%d')}</strong> - REMOVE с {log.from_location}</li>"

        history_html += "</ul>"

        email_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; background-color: #f5f5f5; }}
                    .container {{ background-color: white; padding: 20px; border-radius: 8px; max-width: 600px; margin: 0 auto; }}
                    h1 {{ color: #333; }}
                    h2 {{ color: #0066cc; }}
                    .info {{ background-color: #f0f8ff; padding: 10px; border-left: 4px solid #0066cc; margin: 10px 0; }}
                    .footer {{ color: #999; font-size: 12px; margin-top: 20px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Engine Report</h1>
                    
                    <h2>Aircraft Information</h2>
                    <div class="info">
                        <p><strong>Tail Number:</strong> {aircraft.tail_number}</p>
                        <p><strong>Model:</strong> {aircraft.model}</p>
                        <p><strong>Total Time:</strong> {aircraft.total_time} hrs</p>
                    </div>
                    
                    <h2>Engine Information</h2>
                    <div class="info">
                        <p><strong>Original SN:</strong> {engine.original_sn}</p>
                        <p><strong>Current SN:</strong> {engine.current_sn or 'N/A'}</p>
                        <p><strong>GSS ID:</strong> {engine.gss_sn or 'N/A'}</p>
                        <p><strong>Model:</strong> {engine.model or 'N/A'}</p>
                        <p><strong>Status:</strong> {engine.status or 'N/A'}</p>
                        <p><strong>Total Time:</strong> {engine.total_time} hrs</p>
                        <p><strong>Total Cycles:</strong> {engine.total_cycles}</p>
                    </div>
                    
                    <h2>Installation History</h2>
                    {history_html}
                    
                    <div class="footer">
                        <p>Report generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                        <p>Aviation Engine Management System</p>
                    </div>
                </div>
            </body>
        </html>
        """

        # SMTP конфигурация для Outlook
        # Примечание: Требуется включить "Allow less secure apps" или использовать App Password
        smtp_server = os.getenv("OUTLOOK_SMTP_SERVER", "smtp-mail.outlook.com")
        smtp_port = int(os.getenv("OUTLOOK_SMTP_PORT", "587"))
        sender_email = os.getenv("OUTLOOK_EMAIL", "")
        sender_password = os.getenv("OUTLOOK_PASSWORD", "")

        if not sender_email or not sender_password:
            print("⚠️ Outlook credentials not configured in environment variables")
            return {
                "status": "warning",
                "message": "Email not sent - OUTLOOK_EMAIL and OUTLOOK_PASSWORD not configured",
                "note": "Set environment variables to enable email sending"
            }

        # Отправляем письмо
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = request_data.subject
            msg['From'] = sender_email
            msg['To'] = request_data.recipient_email

            msg.attach(MIMEText(email_body, 'html'))

            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
            server.quit()

            print(f"✅ Email sent to {request_data.recipient_email}")
            return {
                "status": "success",
                "message": f"Report sent to {request_data.recipient_email}"
            }

        except smtplib.SMTPAuthenticationError:
            raise HTTPException(500, "SMTP authentication failed - check credentials")
        except smtplib.SMTPException as e:
            raise HTTPException(500, f"SMTP error: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in send_engine_report_email: {e}")
        raise HTTPException(500, f"Server error: {str(e)}")