# backend/models.py
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text, Boolean
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
    UNASSIGNED = "-"        # Unassigned (Не назначен)

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
    current_sn = Column(String, nullable=True) # Текущий серийный номер (может отличаться от original)
    model = Column(String, nullable=True) # Модель двигателя (CF6-80, CFM56 и т.д.)
    
    # В бизнес-логике статус отражает установку/снятие.
    # Значения: INSTALLED, REMOVED, '-'.
    status = Column(String, default="-")
    condition_1 = Column(String, default="SV")  # Техсостояние: SV/US/Scrap
    condition_2 = Column(String, default="New")  # Физсостояние: New/Overhauled/Repaired/Inspected tested/AS
    
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
    from_location = Column(String, nullable=True) # Откуда перемещен (лок/шоп)
    price = Column(Float, nullable=True)  # Цена двигателя
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
    action_type = Column(String, nullable=False)
    
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
    
    # Для REMOVE: техсостояние при снятии
    condition_1_at_removal = Column(String, nullable=True)
    
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
    ttsn = Column(Float, nullable=True)  # TTSN (Engine) при снятии
    tcsn = Column(Integer, nullable=True)  # TCSN (Engine) при снятии
    ttsn_ac = Column(Float, nullable=True)  # TTSN (Aircraft) при снятии
    tcsn_ac = Column(Integer, nullable=True)  # TCSN (Aircraft) при снятии
    remarks_removal = Column(String, nullable=True)  # Дополнительные замечания при снятии
    supplier = Column(String, nullable=True)  # Поставщик (для Installation)
    is_active = Column(Boolean, default=True)  # Для INSTALL: активна ли установка (False если двигатель снят)
    engine = relationship("Engine", back_populates="logs")

class AircraftUtilizationHistory(Base):
    """История общего налета самолёта (TTSN/TCSN)"""
    __tablename__ = "aircraft_utilization_history"
    
    id = Column(Integer, primary_key=True, index=True)
    aircraft_id = Column(Integer, ForeignKey("aircrafts.id"), nullable=False)
    date = Column(DateTime(timezone=True), nullable=False)
    total_time = Column(Float, nullable=False)  # TTSN самолёта
    total_cycles = Column(Integer, nullable=False)  # TCSN самолёта
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    aircraft = relationship("Aircraft")

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
    comment = Column(String, nullable=True)
    work_type = Column(String, nullable=False, default='All Engine')  # HPT, LPT, All Engine
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PurchaseOrder(Base):
    """Purchase Orders - заказы на закупку"""
    __tablename__ = "purchase_orders"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, nullable=False)
    name = Column(String, nullable=False)
    part_number = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)
    price = Column(Float, nullable=True)
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
    position = Column(Integer, nullable=True)  # Позиция двигателя (1-4) или NULL для общей записи
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)  # FK на двигатель
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


class CustomColumn(Base):
    """Пользовательские колонки для таблиц"""
    __tablename__ = "custom_columns"
    
    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String, nullable=False)  # 'purchase_orders', etc.
    column_key = Column(String, nullable=False)  # 'custom_1', 'custom_2', etc.
    column_label = Column(String, nullable=False)  # Название, которое видит пользователь
    column_order = Column(Integer, default=0)  # Порядок отображения
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PurchaseOrderCustomData(Base):
    """Данные для пользовательских колонок Purchase Orders"""
    __tablename__ = "purchase_order_custom_data"
    
    id = Column(Integer, primary_key=True, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    column_key = Column(String, nullable=False)  # Ключ колонки из CustomColumn
    value = Column(Text, nullable=True)  # Значение
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FakeInstalled(Base):
    """Трекинг фейковых установок (документальные замены без фактических)"""
    __tablename__ = "fake_installed"
    
    id = Column(Integer, primary_key=True, index=True)
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)  # Какой двигатель
    engine_original_sn = Column(String, nullable=False)  # Оригинальный SN для быстрого поиска
    engine_current_sn = Column(String, nullable=False)  # Текущий SN
    aircraft_id = Column(Integer, ForeignKey("aircrafts.id"), nullable=True)
    aircraft_tail = Column(String, nullable=True)  # Для быстрого отображения
    position = Column(Integer, nullable=True)  # Позиция на самолёте (1 или 2)
    
    # Документальная информация
    documented_date = Column(String, nullable=False)  # Дата когда якобы заменили
    documented_reason = Column(String, nullable=True)  # Причина в документах
    
    # Что якобы было
    old_engine_sn = Column(String, nullable=True)
    new_engine_sn = Column(String, nullable=True)
    
    # Реальность
    is_fake = Column(Boolean, default=True)  # Флаг что это фейк
    actual_notes = Column(Text, nullable=True)  # Что на самом деле было/не было
    
    # Метаданные
    created_by = Column(String, nullable=True)  # Кто зарегистрировал
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FakeInstalledSettings(Base):
    """Settings for Fake Installed module (e.g., header labels)."""
    __tablename__ = "fake_installed_settings"

    id = Column(Integer, primary_key=True, index=True)
    # JSON serialized mapping of header keys to labels
    headers_json = Column(Text, nullable=True)


class NameplateTracker(Base):
    """Tracking nameplate (шильдик) history across engines and aircraft."""
    __tablename__ = "nameplate_tracker"
    
    id = Column(Integer, primary_key=True, index=True)
    nameplate_sn = Column(String, nullable=False, index=True)  # Серийник на шильдике
    engine_model = Column(String, nullable=True)  # CFM56-5B, PW, etc
    gss_id = Column(String, nullable=True, index=True)  # GSS ID физического двигателя
    engine_orig_sn = Column(String, nullable=True, index=True)  # Original SN двигателя
    aircraft_tail = Column(String, nullable=True)  # Где установлен (NULL = на складе)
    position = Column(Integer, nullable=True)  # 1,2,3,4
    installed_date = Column(String, nullable=False)  # Когда надели/установили
    removed_date = Column(String, nullable=True)  # Когда сняли (NULL = активно)
    location_type = Column(String, nullable=True)  # on_aircraft, on_engine_storage, detached
    action_note = Column(String, nullable=True)  # installed, swapped_under, removed, etc
    performed_by = Column(String, nullable=True)  # Кто делал
    notes = Column(Text, nullable=True)  # Дополнительные заметки
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ScheduledEvent(Base):
    """Запланированные события и встречи в календаре"""
    __tablename__ = "scheduled_events"
    
    id = Column(Integer, primary_key=True, index=True)
    event_date = Column(String, nullable=False, index=True)  # YYYY-MM-DD
    event_time = Column(String, nullable=True)  # HH:MM (опционально)
    event_type = Column(String, nullable=False)  # SHIPMENT, MEETING, INSPECTION, MAINTENANCE, DEADLINE, OTHER
    title = Column(String, nullable=False)  # "Engine shipment to Baku"
    description = Column(Text, nullable=True)  # Детали события
    
    # Связь с двигателем (опционально)
    engine_id = Column(Integer, ForeignKey('engines.id'), nullable=True)
    serial_number = Column(String, nullable=True)  # Для быстрого доступа
    
    # Локация/маршрут (опционально)
    location = Column(String, nullable=True)  # "Baku", "Dubai", etc.
    from_location = Column(String, nullable=True)
    to_location = Column(String, nullable=True)
    
    # Статус события
    status = Column(String, default='PLANNED')  # PLANNED, IN_PROGRESS, COMPLETED, CANCELLED
    
    # Приоритет и визуальное оформление
    priority = Column(String, default='MEDIUM')  # LOW, MEDIUM, HIGH, URGENT
    color = Column(String, default='#3788d8')  # Цвет плашки на календаре
    
    # Метаданные
    created_by = Column(String, nullable=True)  # Кто создал событие
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# SHIPMENT MODEL (Logistics & Schedules Tracking)
# ============================================================
class Shipment(Base):
    """
    Модель для отслеживания отправок двигателей и запчастей в пути.
    Поддерживает:
    - ENGINE type: отслеживание двигателей в транзите
    - PARTS type: отслеживание запчастей (включая pre-order - еще не в стоке)
    
    При статусе DELIVERED:
    - ENGINE: обновляет engines.location_id на "On Stock"
    - PARTS: создает новую запись в store_items (автоинвентаризация)
    """
    __tablename__ = "shipments"
    
    # Основные поля
    id = Column(Integer, primary_key=True, index=True)
    shipment_type = Column(String(50), nullable=False)  # ENGINE, PARTS
    status = Column(String(50), default='PLANNED')  # PLANNED, IN_TRANSIT, DELIVERED, DELAYED, CANCELLED
    
    # ДЛЯ ENGINE TYPE
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)
    engine_model = Column(String(100), nullable=True)  # Модель двигателя
    gss_id = Column(String(100), nullable=True)  # GSS ID двигателя
    destination_location = Column(String(255), nullable=True)  # Куда должен прибыть двигатель
    
    # ДЛЯ PARTS TYPE
    part_name = Column(String(255), nullable=True)  # Имя запчасти
    part_category = Column(String(100), nullable=True)  # Overhaul, Consumable, High-Value
    part_quantity = Column(Integer, nullable=True)  # Количество запчастей
    reserved_quantity = Column(Integer, default=0)  # Для pre-order (еще не в inventory)
    
    # Отправка и доставка
    departure_date = Column(DateTime, nullable=True)
    expected_delivery_date = Column(DateTime, nullable=False)
    actual_delivery_date = Column(DateTime, nullable=True)
    
    # Отслеживание
    supplier_name = Column(String(255), nullable=True)
    tracking_number = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Пользователь и время
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Связи
    engine = relationship("Engine", foreign_keys=[engine_id])


class ConditionStatus(Base):
    """Справочник статусов Condition для Store Balance"""
    __tablename__ = "condition_statuses"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    color = Column(String(20), nullable=False, default="#6c757d")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class WorkType(Base):
    """Справочник типов работ для Borescope Inspection"""
    __tablename__ = "work_types"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())