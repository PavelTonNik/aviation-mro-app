# backend/models.py
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text, Boolean, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
try:
    from .database import Base
except ImportError:  # Fallback when running as a module script
    from database import Base

# --- ENUMS (Списки допустимых значений) ---
class EngineStatus(str, enum.Enum):
    SV = "SV"               # Serviceable (Исправен)
    US = "US"               # Unserviceable (Неисправен)
    INSTALLED = "INSTALLED" # Установлен на самолет
    REMOVED = "REMOVED"     # Снят (обычно требует инспекции)

class ActionType(str, enum.Enum):
    INSTALL = "INSTALL"
    REMOVE = "REMOVE"
    SHIP = "SHIP"
    REPAIR = "REPAIR"
    INSPECT = "INSPECT"
    PART_ACTION = "PART_ACTION"
    FLIGHT = "FLIGHT"  # Для записей ATLB/Utilization
    
# --- TABLES (Таблицы) ---

class Location(Base):
    __tablename__ = "locations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False) # FRU, SHJ, Shop, etc.
    city = Column(String)
    
    # Связи для удобства (обратные)
    engines = relationship("Engine", back_populates="location")
    parts = relationship("Part", back_populates="location")

class Aircraft(Base):
    __tablename__ = "aircrafts"
    
    id = Column(Integer, primary_key=True, index=True)
    tail_number = Column(String, unique=True, nullable=False) # BAT, BAR, BAQ
    model = Column(String) # Например "Boeing 737-300"
    msn = Column(String, nullable=True) 
    total_time = Column(Float, default=0.0)
    total_cycles = Column(Integer, default=0)
    initial_total_time = Column(Float, default=0.0)
    initial_total_cycles = Column(Integer, default=0)
    last_atlb_ref = Column(String, nullable=True)

    engines = relationship("Engine", back_populates="aircraft")

class Engine(Base):
    __tablename__ = "engines"

    id = Column(Integer, primary_key=True, index=True)
    original_sn = Column(String, unique=True)
    gss_sn = Column(String, nullable=True)
    current_sn = Column(String, nullable=False) # Основной идентификатор
    model = Column(String, nullable=True) # Модель двигателя (CF6-80, CFM56 и т.д.)
    
    status = Column(Enum(EngineStatus), default=EngineStatus.SV
    )    
    # Наработка
    total_time = Column(Float, default=0.0)   # TT
    total_cycles = Column(Integer, default=0) # TC
    
    # Snapshot при установке (для расчета наработки на конкретном самолете)
    tsn_at_install = Column(Float, nullable=True)   # TSN на момент установки
    csn_at_install = Column(Integer, nullable=True) # CSN на момент установки
    install_date = Column(DateTime(timezone=True), nullable=True) # Дата установки
    
    # Логика местоположения
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    aircraft_id = Column(Integer, ForeignKey("aircrafts.id"), nullable=True)
    position = Column(Integer, nullable=True) # 1 (Left) или 2 (Right), если на самолете
    
    # Дополнительные поля
    photo_url = Column(String, nullable=True) # Ссылка на фото
    remarks = Column(String, nullable=True) # Примечания/комментарии
    removed_from = Column(String, nullable=True) # Место откуда снят двигатель
    
    # Параметры двигателя (для мониторинга)
    n1_takeoff = Column(Float, nullable=True)
    n1_cruise = Column(Float, nullable=True)
    n2_takeoff = Column(Float, nullable=True)
    n2_cruise = Column(Float, nullable=True)
    egt_takeoff = Column(Float, nullable=True)  # EGT при взлете
    egt_cruise = Column(Float, nullable=True)   # EGT при крейсерском режиме
    last_param_update = Column(DateTime(timezone=True), nullable=True)  # Дата последнего обновления параметров
    
    # Связи
    location = relationship("Location", back_populates="engines")
    aircraft = relationship("Aircraft", back_populates="engines")
    parts = relationship("Part", back_populates="engine") # Установленные запчасти
    logs = relationship("ActionLog", back_populates="engine")

class Part(Base):
    __tablename__ = "parts"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    part_number = Column(String, nullable=False)
    serial_number = Column(String, nullable=True) # Может быть null для расходников
    quantity = Column(Integer, default=1)
    
    # Где запчасть? Либо на складе, либо внутри двигателя
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)
    
    location = relationship("Location", back_populates="parts")
    engine = relationship("Engine", back_populates="parts")

class ActionLog(Base):
    __tablename__ = "action_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime(timezone=True), server_default=func.now())
    action_type = Column(Enum(ActionType), nullable=False)
    
    # К чему относится запись
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)
    part_id = Column(Integer, ForeignKey("parts.id"), nullable=True)
    
    # Детали перемещения/действия
    from_location = Column(String, nullable=True) # Текстовое описание для истории
    to_location = Column(String, nullable=True)
    to_aircraft = Column(String, nullable=True)  # Для INSTALL: tail number самолета
    position = Column(Integer, nullable=True)     # Для INSTALL: позиция двигателя
    
    # Снапшот наработки на момент действия (ВАЖНО для истории!)
    snapshot_tt = Column(Float, nullable=True)
    snapshot_tc = Column(Integer, nullable=True)
    
    comments = Column(Text, nullable=True)
    file_url = Column(String, nullable=True) # Ссылка на Google Drive / S3
    is_maintenance = Column(Boolean, default=False)
    atlb_ref = Column(String, nullable=True)
    maintenance_type = Column(String, nullable=True)
    block_time_str = Column(String, nullable=True)
    flight_time_str = Column(String, nullable=True)
    block_out_str = Column(String, nullable=True)
    block_in_str = Column(String, nullable=True)
    flight_off_str = Column(String, nullable=True)
    flight_on_str = Column(String, nullable=True)
    from_apt = Column(String, nullable=True)
    to_apt = Column(String, nullable=True)
    oil_1 = Column(Float, nullable=True)
    oil_2 = Column(Float, nullable=True)
    oil_3 = Column(Float, nullable=True)
    oil_4 = Column(Float, nullable=True)
    oil_apu = Column(Float, nullable=True)
    hyd_1 = Column(Float, nullable=True)
    hyd_2 = Column(Float, nullable=True)
    hyd_3 = Column(Float, nullable=True)
    hyd_4 = Column(Float, nullable=True)
    performed_by = Column(String, nullable=True)
    
    engine = relationship("Engine", back_populates="logs")

class EngineParameterHistory(Base):
    """История ввода параметров двигателя (N1, N2, EGT)"""
    __tablename__ = "engine_parameter_history"
    
    id = Column(Integer, primary_key=True, index=True)
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=False)
    date = Column(DateTime(timezone=True), nullable=False)  # Дата записи параметров
    created_at = Column(DateTime(timezone=True), server_default=func.now())  # Когда была создана запись
    
    # Параметры двигателя
    n1_takeoff = Column(Float, nullable=True)
    n2_takeoff = Column(Float, nullable=True)
    egt_takeoff = Column(Float, nullable=True)
    n1_cruise = Column(Float, nullable=True)
    n2_cruise = Column(Float, nullable=True)
    egt_cruise = Column(Float, nullable=True)
    
    # Связь с двигателем
    engine = relationship("Engine")

class BoroscopeInspection(Base):
    """Borescope инспекции двигателей"""
    __tablename__ = "borescope_inspections"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, nullable=False)
    aircraft = Column(String, nullable=False)
    serial_number = Column(String, nullable=False)
    position = Column(String, nullable=False)
    gss_id = Column(String, nullable=True)
    inspector = Column(String, nullable=False)
    link = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PurchaseOrder(Base):
    """Purchase Orders - заказы на закупку"""
    __tablename__ = "purchase_orders"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, nullable=False)
    name = Column(String, nullable=False)
    purpose = Column(String, nullable=False)
    aircraft = Column(String, nullable=False)
    ro_number = Column(String, nullable=False)
    link = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StoreItem(Base):
    """Запасы склада (Store Balance)"""
    __tablename__ = "store_items"

    id = Column(Integer, primary_key=True, index=True)
    received_date = Column(DateTime(timezone=True), nullable=True)
    part_name = Column(String, nullable=False)
    part_number = Column(String, nullable=False)
    serial_number = Column(String, nullable=True)
    condition = Column(String, nullable=True)
    quantity = Column(Integer, default=1)
    unit = Column(String, nullable=True)
    location = Column(String, nullable=True)
    shelf = Column(String, nullable=True)
    owner = Column(String, nullable=True)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UtilizationParameter(Base):
    """Utilization Parameters - параметры использования самолета"""
    __tablename__ = "utilization_parameters"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime(timezone=True), nullable=False)
    aircraft = Column(String, nullable=False)
    ttsn = Column(Float, nullable=False)  # Total Time Since New
    tcsn = Column(Integer, nullable=False)  # Total Cycles Since New
    period = Column(Boolean, default=False)  # Флаг периода
    date_from = Column(DateTime(timezone=True), nullable=True)  # Начало периода
    date_to = Column(DateTime(timezone=True), nullable=True)  # Конец периода
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    """Пользователи системы"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)  # Хэш пароля
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    position = Column(String, nullable=True)  # Должность в компании
    role = Column(String, nullable=False, default="viewer")  # admin, user, viewer
    photo_url = Column(String, nullable=True)  # Ссылка на фото профиля
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)


class Notification(Base):
    """Уведомления для пользователей"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)  # Кому уведомление (None = всем админам)
    action_type = Column(String, nullable=False)  # 'created', 'updated', 'deleted'
    entity_type = Column(String, nullable=False)  # 'engine', 'parameter', 'utilization', etc.
    entity_id = Column(Integer, nullable=True)
    message = Column(Text, nullable=False)
    performed_by = Column(String, nullable=False)  # Кто совершил действие
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())