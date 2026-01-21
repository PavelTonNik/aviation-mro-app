# backend/models.py
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text, Boolean, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
try:
    from .database import Base
except ImportError:  # Fallback when running as a module script
    from database import Base

# --- ENUMS (ðíð┐ð©Ðüð║ð© ð┤ð¥ð┐ÐâÐüÐéð©ð╝ÐïÐà ðÀð¢ð░ÐçðÁð¢ð©ð╣) ---
class EngineStatus(str, enum.Enum):
    SV = "SV"               # Serviceable (ðÿÐüð┐ÐÇð░ð▓ðÁð¢)
    US = "US"               # Unserviceable (ðØðÁð©Ðüð┐ÐÇð░ð▓ðÁð¢)
    INSTALLED = "INSTALLED" # ðúÐüÐéð░ð¢ð¥ð▓ð╗ðÁð¢ ð¢ð░ Ðüð░ð╝ð¥ð╗ðÁÐé
    REMOVED = "REMOVED"     # ðíð¢ÐÅÐé (ð¥ð▒ÐïÐçð¢ð¥ ÐéÐÇðÁð▒ÐâðÁÐé ð©ð¢Ðüð┐ðÁð║Ðåð©ð©)
    UNASSIGNED = "-"        # Unassigned (ðØðÁ ð¢ð░ðÀð¢ð░ÐçðÁð¢)

class ActionType(str, enum.Enum):
    INSTALL = "INSTALL"
    REMOVE = "REMOVE"
    SHIP = "SHIP"
    REPAIR = "REPAIR"
    INSPECT = "INSPECT"
    PART_ACTION = "PART_ACTION"
    FLIGHT = "FLIGHT"  # ðöð╗ÐÅ ðÀð░ð┐ð©ÐüðÁð╣ ATLB/Utilization
    
# --- TABLES (ðóð░ð▒ð╗ð©ÐåÐï) ---

class Location(Base):
    __tablename__ = "locations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False) # FRU, SHJ, Shop, etc.
    city = Column(String)
    
    # ðíð▓ÐÅðÀð© ð┤ð╗ÐÅ Ðâð┤ð¥ð▒ÐüÐéð▓ð░ (ð¥ð▒ÐÇð░Ðéð¢ÐïðÁ)
    engines = relationship("Engine", back_populates="location")
    parts = relationship("Part", back_populates="location")

class Aircraft(Base):
    __tablename__ = "aircrafts"
    
    id = Column(Integer, primary_key=True, index=True)
    tail_number = Column(String, unique=True, nullable=False) # BAT, BAR, BAQ
    model = Column(String) # ðØð░ð┐ÐÇð©ð╝ðÁÐÇ "Boeing 737-300"
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
    current_sn = Column(String, nullable=True) # ðóðÁð║ÐâÐëð©ð╣ ÐüðÁÐÇð©ð╣ð¢Ðïð╣ ð¢ð¥ð╝ðÁÐÇ (ð╝ð¥ðÂðÁÐé ð¥Ðéð╗ð©Ðçð░ÐéÐîÐüÐÅ ð¥Ðé original)
    model = Column(String, nullable=True) # ð£ð¥ð┤ðÁð╗Ðî ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ (CF6-80, CFM56 ð© Ðé.ð┤.)
    
    # ðÆ ð▒ð©ðÀð¢ðÁÐü-ð╗ð¥ð│ð©ð║ðÁ ÐüÐéð░ÐéÐâÐü ð¥ÐéÐÇð░ðÂð░ðÁÐé ÐâÐüÐéð░ð¢ð¥ð▓ð║Ðâ/Ðüð¢ÐÅÐéð©ðÁ.
    # ðùð¢ð░ÐçðÁð¢ð©ÐÅ: INSTALLED, REMOVED, '-'.
    status = Column(String, default="-")
    condition_1 = Column(String, default="SV")  # ðóðÁÐàÐüð¥ÐüÐéð¥ÐÅð¢ð©ðÁ: SV/US/Scrap
    condition_2 = Column(String, default="New")  # ðñð©ðÀÐüð¥ÐüÐéð¥ÐÅð¢ð©ðÁ: New/Overhauled/Repaired/Inspected tested/AS
    
    # ðØð░ÐÇð░ð▒ð¥Ðéð║ð░
    total_time = Column(Float, default=0.0)   # TT
    total_cycles = Column(Integer, default=0) # TC
    
    # Snapshot ð┐ÐÇð© ÐâÐüÐéð░ð¢ð¥ð▓ð║ðÁ (ð┤ð╗ÐÅ ÐÇð░ÐüÐçðÁÐéð░ ð¢ð░ÐÇð░ð▒ð¥Ðéð║ð© ð¢ð░ ð║ð¥ð¢ð║ÐÇðÁÐéð¢ð¥ð╝ Ðüð░ð╝ð¥ð╗ðÁÐéðÁ)
    tsn_at_install = Column(Float, nullable=True)   # TSN ð¢ð░ ð╝ð¥ð╝ðÁð¢Ðé ÐâÐüÐéð░ð¢ð¥ð▓ð║ð©
    csn_at_install = Column(Integer, nullable=True) # CSN ð¢ð░ ð╝ð¥ð╝ðÁð¢Ðé ÐâÐüÐéð░ð¢ð¥ð▓ð║ð©
    install_date = Column(DateTime(timezone=True), nullable=True) # ðöð░Ðéð░ ÐâÐüÐéð░ð¢ð¥ð▓ð║ð©
    
    # ðøð¥ð│ð©ð║ð░ ð╝ðÁÐüÐéð¥ð┐ð¥ð╗ð¥ðÂðÁð¢ð©ÐÅ
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    aircraft_id = Column(Integer, ForeignKey("aircrafts.id"), nullable=True)
    position = Column(Integer, nullable=True) # 1 (Left) ð©ð╗ð© 2 (Right), ðÁÐüð╗ð© ð¢ð░ Ðüð░ð╝ð¥ð╗ðÁÐéðÁ
    
    # ðöð¥ð┐ð¥ð╗ð¢ð©ÐéðÁð╗Ðîð¢ÐïðÁ ð┐ð¥ð╗ÐÅ
    from_location = Column(String, nullable=True) # ð×Ðéð║Ðâð┤ð░ ð┐ðÁÐÇðÁð╝ðÁÐëðÁð¢ (ð╗ð¥ð║/Ðêð¥ð┐)
    price = Column(Float, nullable=True)  # ðªðÁð¢ð░ ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ
    photo_url = Column(String, nullable=True) # ðíÐüÐïð╗ð║ð░ ð¢ð░ Ðäð¥Ðéð¥
    remarks = Column(String, nullable=True) # ðƒÐÇð©ð╝ðÁÐçð░ð¢ð©ÐÅ/ð║ð¥ð╝ð╝ðÁð¢Ðéð░ÐÇð©ð©
    removed_from = Column(String, nullable=True) # ð£ðÁÐüÐéð¥ ð¥Ðéð║Ðâð┤ð░ Ðüð¢ÐÅÐé ð┤ð▓ð©ð│ð░ÐéðÁð╗Ðî
    
    # ðƒð░ÐÇð░ð╝ðÁÐéÐÇÐï ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ (ð┤ð╗ÐÅ ð╝ð¥ð¢ð©Ðéð¥ÐÇð©ð¢ð│ð░)
    n1_takeoff = Column(Float, nullable=True)
    n1_cruise = Column(Float, nullable=True)
    n2_takeoff = Column(Float, nullable=True)
    n2_cruise = Column(Float, nullable=True)
    egt_takeoff = Column(Float, nullable=True)  # EGT ð┐ÐÇð© ð▓ðÀð╗ðÁÐéðÁ
    egt_cruise = Column(Float, nullable=True)   # EGT ð┐ÐÇð© ð║ÐÇðÁð╣ÐüðÁÐÇÐüð║ð¥ð╝ ÐÇðÁðÂð©ð╝ðÁ
    last_param_update = Column(DateTime(timezone=True), nullable=True)  # ðöð░Ðéð░ ð┐ð¥Ðüð╗ðÁð┤ð¢ðÁð│ð¥ ð¥ð▒ð¢ð¥ð▓ð╗ðÁð¢ð©ÐÅ ð┐ð░ÐÇð░ð╝ðÁÐéÐÇð¥ð▓
    
    # ðíð▓ÐÅðÀð©
    location = relationship("Location", back_populates="engines")
    aircraft = relationship("Aircraft", back_populates="engines")
    parts = relationship("Part", back_populates="engine") # ðúÐüÐéð░ð¢ð¥ð▓ð╗ðÁð¢ð¢ÐïðÁ ðÀð░ð┐Ðçð░ÐüÐéð©
    logs = relationship("ActionLog", back_populates="engine")

class Part(Base):
    __tablename__ = "parts"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    part_number = Column(String, nullable=False)
    serial_number = Column(String, nullable=True) # ð£ð¥ðÂðÁÐé ð▒ÐïÐéÐî null ð┤ð╗ÐÅ ÐÇð░ÐüÐàð¥ð┤ð¢ð©ð║ð¥ð▓
    quantity = Column(Integer, default=1)
    
    # ðôð┤ðÁ ðÀð░ð┐Ðçð░ÐüÐéÐî? ðøð©ð▒ð¥ ð¢ð░ Ðüð║ð╗ð░ð┤ðÁ, ð╗ð©ð▒ð¥ ð▓ð¢ÐâÐéÐÇð© ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)
    
    location = relationship("Location", back_populates="parts")
    engine = relationship("Engine", back_populates="parts")

class ActionLog(Base):
    __tablename__ = "action_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime(timezone=True), server_default=func.now())
    action_type = Column(String, nullable=False)
    
    # ðÜ ÐçðÁð╝Ðâ ð¥Ðéð¢ð¥Ðüð©ÐéÐüÐÅ ðÀð░ð┐ð©ÐüÐî
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)
    part_id = Column(Integer, ForeignKey("parts.id"), nullable=True)
    
    # ðöðÁÐéð░ð╗ð© ð┐ðÁÐÇðÁð╝ðÁÐëðÁð¢ð©ÐÅ/ð┤ðÁð╣ÐüÐéð▓ð©ÐÅ
    from_location = Column(String, nullable=True) # ðóðÁð║ÐüÐéð¥ð▓ð¥ðÁ ð¥ð┐ð©Ðüð░ð¢ð©ðÁ ð┤ð╗ÐÅ ð©ÐüÐéð¥ÐÇð©ð©
    to_location = Column(String, nullable=True)
    to_aircraft = Column(String, nullable=True)  # ðöð╗ÐÅ INSTALL: tail number Ðüð░ð╝ð¥ð╗ðÁÐéð░
    position = Column(Integer, nullable=True)     # ðöð╗ÐÅ INSTALL: ð┐ð¥ðÀð©Ðåð©ÐÅ ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ
    
    # ðíð¢ð░ð┐Ðêð¥Ðé ð¢ð░ÐÇð░ð▒ð¥Ðéð║ð© ð¢ð░ ð╝ð¥ð╝ðÁð¢Ðé ð┤ðÁð╣ÐüÐéð▓ð©ÐÅ (ðÆðÉðûðØð× ð┤ð╗ÐÅ ð©ÐüÐéð¥ÐÇð©ð©!)
    snapshot_tt = Column(Float, nullable=True)
    snapshot_tc = Column(Integer, nullable=True)
    
    # ðöð╗ÐÅ REMOVE: ÐéðÁÐàÐüð¥ÐüÐéð¥ÐÅð¢ð©ðÁ ð┐ÐÇð© Ðüð¢ÐÅÐéð©ð©
    condition_1_at_removal = Column(String, nullable=True)
    
    comments = Column(Text, nullable=True)
    file_url = Column(String, nullable=True) # ðíÐüÐïð╗ð║ð░ ð¢ð░ Google Drive / S3
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
    ttsn = Column(Float, nullable=True)  # TTSN (Engine) ð┐ÐÇð© Ðüð¢ÐÅÐéð©ð©
    tcsn = Column(Integer, nullable=True)  # TCSN (Engine) ð┐ÐÇð© Ðüð¢ÐÅÐéð©ð©
    ttsn_ac = Column(Float, nullable=True)  # TTSN (Aircraft) ð┐ÐÇð© Ðüð¢ÐÅÐéð©ð©
    tcsn_ac = Column(Integer, nullable=True)  # TCSN (Aircraft) ð┐ÐÇð© Ðüð¢ÐÅÐéð©ð©
    remarks_removal = Column(String, nullable=True)  # ðöð¥ð┐ð¥ð╗ð¢ð©ÐéðÁð╗Ðîð¢ÐïðÁ ðÀð░ð╝ðÁÐçð░ð¢ð©ÐÅ ð┐ÐÇð© Ðüð¢ÐÅÐéð©ð©
    supplier = Column(String, nullable=True)  # ðƒð¥ÐüÐéð░ð▓Ðëð©ð║ (ð┤ð╗ÐÅ Installation)
    is_active = Column(Boolean, default=True)  # ðöð╗ÐÅ INSTALL: ð░ð║Ðéð©ð▓ð¢ð░ ð╗ð© ÐâÐüÐéð░ð¢ð¥ð▓ð║ð░ (False ðÁÐüð╗ð© ð┤ð▓ð©ð│ð░ÐéðÁð╗Ðî Ðüð¢ÐÅÐé)
    engine = relationship("Engine", back_populates="logs")

class AircraftUtilizationHistory(Base):
    """ðÿÐüÐéð¥ÐÇð©ÐÅ ð¥ð▒ÐëðÁð│ð¥ ð¢ð░ð╗ðÁÐéð░ Ðüð░ð╝ð¥ð╗ÐæÐéð░ (TTSN/TCSN)"""
    __tablename__ = "aircraft_utilization_history"
    
    id = Column(Integer, primary_key=True, index=True)
    aircraft_id = Column(Integer, ForeignKey("aircrafts.id"), nullable=False)
    date = Column(DateTime(timezone=True), nullable=False)
    total_time = Column(Float, nullable=False)  # TTSN Ðüð░ð╝ð¥ð╗ÐæÐéð░
    total_cycles = Column(Integer, nullable=False)  # TCSN Ðüð░ð╝ð¥ð╗ÐæÐéð░
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    aircraft = relationship("Aircraft")

class EngineParameterHistory(Base):
    """ðÿÐüÐéð¥ÐÇð©ÐÅ ð▓ð▓ð¥ð┤ð░ ð┐ð░ÐÇð░ð╝ðÁÐéÐÇð¥ð▓ ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ (N1, N2, EGT)"""
    __tablename__ = "engine_parameter_history"
    
    id = Column(Integer, primary_key=True, index=True)
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=False)
    date = Column(DateTime(timezone=True), nullable=False)  # ðöð░Ðéð░ ðÀð░ð┐ð©Ðüð© ð┐ð░ÐÇð░ð╝ðÁÐéÐÇð¥ð▓
    created_at = Column(DateTime(timezone=True), server_default=func.now())  # ðÜð¥ð│ð┤ð░ ð▒Ðïð╗ð░ Ðüð¥ðÀð┤ð░ð¢ð░ ðÀð░ð┐ð©ÐüÐî
    
    # ðƒð░ÐÇð░ð╝ðÁÐéÐÇÐï ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ
    n1_takeoff = Column(Float, nullable=True)
    n2_takeoff = Column(Float, nullable=True)
    egt_takeoff = Column(Float, nullable=True)
    n1_cruise = Column(Float, nullable=True)
    n2_cruise = Column(Float, nullable=True)
    egt_cruise = Column(Float, nullable=True)
    
    # ðíð▓ÐÅðÀÐî Ðü ð┤ð▓ð©ð│ð░ÐéðÁð╗ðÁð╝
    engine = relationship("Engine")

class BoroscopeInspection(Base):
    """Borescope ð©ð¢Ðüð┐ðÁð║Ðåð©ð© ð┤ð▓ð©ð│ð░ÐéðÁð╗ðÁð╣"""
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

class BoroscopeSchedule(Base):
    """ðùð░ð┐ð╗ð░ð¢ð©ÐÇð¥ð▓ð░ð¢ð¢ÐïðÁ ð▒ð¥roÐüð║ð¥ð┐ð©ÐçðÁÐüð║ð©ðÁ ð©ð¢Ðüð┐ðÁð║Ðåð©ð©"""
    __tablename__ = "boroscope_schedule"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    aircraft_tail_number = Column(String, ForeignKey('aircrafts.tail_number'), nullable=False)
    position = Column(Integer, nullable=False)  # 1, 2, 3, 4
    inspector = Column(String, nullable=False)
    remarks = Column(String, nullable=True)
    location = Column(String, nullable=True)
    status = Column(String, default='Scheduled', nullable=False)  # Scheduled, Completed, Cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    aircraft = relationship("Aircraft", backref="boroscope_schedules")

class PurchaseOrder(Base):
    """Purchase Orders - ðÀð░ð║ð░ðÀÐï ð¢ð░ ðÀð░ð║Ðâð┐ð║Ðâ"""
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
    """ðùð░ð┐ð░ÐüÐï Ðüð║ð╗ð░ð┤ð░ (Store Balance)"""
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
    """Utilization Parameters - ð┐ð░ÐÇð░ð╝ðÁÐéÐÇÐï ð©Ðüð┐ð¥ð╗ÐîðÀð¥ð▓ð░ð¢ð©ÐÅ Ðüð░ð╝ð¥ð╗ðÁÐéð░"""
    __tablename__ = "utilization_parameters"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime(timezone=True), nullable=False)
    aircraft = Column(String, nullable=False)
    position = Column(Integer, nullable=True)  # ðƒð¥ðÀð©Ðåð©ÐÅ ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ (1-4) ð©ð╗ð© NULL ð┤ð╗ÐÅ ð¥ð▒ÐëðÁð╣ ðÀð░ð┐ð©Ðüð©
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)  # FK ð¢ð░ ð┤ð▓ð©ð│ð░ÐéðÁð╗Ðî
    ttsn = Column(Float, nullable=False)  # Total Time Since New
    tcsn = Column(Integer, nullable=False)  # Total Cycles Since New
    period = Column(Boolean, default=False)  # ðñð╗ð░ð│ ð┐ðÁÐÇð©ð¥ð┤ð░
    date_from = Column(DateTime(timezone=True), nullable=True)  # ðØð░Ðçð░ð╗ð¥ ð┐ðÁÐÇð©ð¥ð┤ð░
    date_to = Column(DateTime(timezone=True), nullable=True)  # ðÜð¥ð¢ðÁÐå ð┐ðÁÐÇð©ð¥ð┤ð░
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    """ðƒð¥ð╗ÐîðÀð¥ð▓ð░ÐéðÁð╗ð© Ðüð©ÐüÐéðÁð╝Ðï"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)  # ðÑÐìÐê ð┐ð░ÐÇð¥ð╗ÐÅ
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    position = Column(String, nullable=True)  # ðöð¥ð╗ðÂð¢ð¥ÐüÐéÐî ð▓ ð║ð¥ð╝ð┐ð░ð¢ð©ð©
    role = Column(String, nullable=False, default="viewer")  # admin, user, viewer
    photo_url = Column(String, nullable=True)  # ðíÐüÐïð╗ð║ð░ ð¢ð░ Ðäð¥Ðéð¥ ð┐ÐÇð¥Ðäð©ð╗ÐÅ
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)


class Notification(Base):
    """ðúð▓ðÁð┤ð¥ð╝ð╗ðÁð¢ð©ÐÅ ð┤ð╗ÐÅ ð┐ð¥ð╗ÐîðÀð¥ð▓ð░ÐéðÁð╗ðÁð╣"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)  # ðÜð¥ð╝Ðâ Ðâð▓ðÁð┤ð¥ð╝ð╗ðÁð¢ð©ðÁ (None = ð▓ÐüðÁð╝ ð░ð┤ð╝ð©ð¢ð░ð╝)
    action_type = Column(String, nullable=False)  # 'created', 'updated', 'deleted'
    entity_type = Column(String, nullable=False)  # 'engine', 'parameter', 'utilization', etc.
    entity_id = Column(Integer, nullable=True)
    message = Column(Text, nullable=False)
    performed_by = Column(String, nullable=False)  # ðÜÐéð¥ Ðüð¥ð▓ðÁÐÇÐêð©ð╗ ð┤ðÁð╣ÐüÐéð▓ð©ðÁ
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CustomColumn(Base):
    """ðƒð¥ð╗ÐîðÀð¥ð▓ð░ÐéðÁð╗ÐîÐüð║ð©ðÁ ð║ð¥ð╗ð¥ð¢ð║ð© ð┤ð╗ÐÅ Ðéð░ð▒ð╗ð©Ðå"""
    __tablename__ = "custom_columns"
    
    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String, nullable=False)  # 'purchase_orders', etc.
    column_key = Column(String, nullable=False)  # 'custom_1', 'custom_2', etc.
    column_label = Column(String, nullable=False)  # ðØð░ðÀð▓ð░ð¢ð©ðÁ, ð║ð¥Ðéð¥ÐÇð¥ðÁ ð▓ð©ð┤ð©Ðé ð┐ð¥ð╗ÐîðÀð¥ð▓ð░ÐéðÁð╗Ðî
    column_order = Column(Integer, default=0)  # ðƒð¥ÐÇÐÅð┤ð¥ð║ ð¥Ðéð¥ð▒ÐÇð░ðÂðÁð¢ð©ÐÅ
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PurchaseOrderCustomData(Base):
    """ðöð░ð¢ð¢ÐïðÁ ð┤ð╗ÐÅ ð┐ð¥ð╗ÐîðÀð¥ð▓ð░ÐéðÁð╗ÐîÐüð║ð©Ðà ð║ð¥ð╗ð¥ð¢ð¥ð║ Purchase Orders"""
    __tablename__ = "purchase_order_custom_data"
    
    id = Column(Integer, primary_key=True, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    column_key = Column(String, nullable=False)  # ðÜð╗ÐÄÐç ð║ð¥ð╗ð¥ð¢ð║ð© ð©ðÀ CustomColumn
    value = Column(Text, nullable=True)  # ðùð¢ð░ÐçðÁð¢ð©ðÁ
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FakeInstalled(Base):
    """ðóÐÇðÁð║ð©ð¢ð│ ÐäðÁð╣ð║ð¥ð▓ÐïÐà ÐâÐüÐéð░ð¢ð¥ð▓ð¥ð║ (ð┤ð¥ð║Ðâð╝ðÁð¢Ðéð░ð╗Ðîð¢ÐïðÁ ðÀð░ð╝ðÁð¢Ðï ð▒ðÁðÀ Ðäð░ð║Ðéð©ÐçðÁÐüð║ð©Ðà)"""
    __tablename__ = "fake_installed"
    
    id = Column(Integer, primary_key=True, index=True)
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)  # ðÜð░ð║ð¥ð╣ ð┤ð▓ð©ð│ð░ÐéðÁð╗Ðî
    engine_original_sn = Column(String, nullable=False)  # ð×ÐÇð©ð│ð©ð¢ð░ð╗Ðîð¢Ðïð╣ SN ð┤ð╗ÐÅ ð▒ÐïÐüÐéÐÇð¥ð│ð¥ ð┐ð¥ð©Ðüð║ð░
    engine_current_sn = Column(String, nullable=False)  # ðóðÁð║ÐâÐëð©ð╣ SN
    aircraft_id = Column(Integer, ForeignKey("aircrafts.id"), nullable=True)
    aircraft_tail = Column(String, nullable=True)  # ðöð╗ÐÅ ð▒ÐïÐüÐéÐÇð¥ð│ð¥ ð¥Ðéð¥ð▒ÐÇð░ðÂðÁð¢ð©ÐÅ
    position = Column(Integer, nullable=True)  # ðƒð¥ðÀð©Ðåð©ÐÅ ð¢ð░ Ðüð░ð╝ð¥ð╗ÐæÐéðÁ (1 ð©ð╗ð© 2)
    
    # ðöð¥ð║Ðâð╝ðÁð¢Ðéð░ð╗Ðîð¢ð░ÐÅ ð©ð¢Ðäð¥ÐÇð╝ð░Ðåð©ÐÅ
    documented_date = Column(String, nullable=False)  # ðöð░Ðéð░ ð║ð¥ð│ð┤ð░ ÐÅð║ð¥ð▒Ðï ðÀð░ð╝ðÁð¢ð©ð╗ð©
    documented_reason = Column(String, nullable=True)  # ðƒÐÇð©Ðçð©ð¢ð░ ð▓ ð┤ð¥ð║Ðâð╝ðÁð¢Ðéð░Ðà
    
    # ðºÐéð¥ ÐÅð║ð¥ð▒Ðï ð▒Ðïð╗ð¥
    old_engine_sn = Column(String, nullable=True)
    new_engine_sn = Column(String, nullable=True)
    
    # ðáðÁð░ð╗Ðîð¢ð¥ÐüÐéÐî
    is_fake = Column(Boolean, default=True)  # ðñð╗ð░ð│ ÐçÐéð¥ ÐìÐéð¥ ÐäðÁð╣ð║
    actual_notes = Column(Text, nullable=True)  # ðºÐéð¥ ð¢ð░ Ðüð░ð╝ð¥ð╝ ð┤ðÁð╗ðÁ ð▒Ðïð╗ð¥/ð¢ðÁ ð▒Ðïð╗ð¥
    
    # ð£ðÁÐéð░ð┤ð░ð¢ð¢ÐïðÁ
    created_by = Column(String, nullable=True)  # ðÜÐéð¥ ðÀð░ÐÇðÁð│ð©ÐüÐéÐÇð©ÐÇð¥ð▓ð░ð╗
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FakeInstalledSettings(Base):
    """Settings for Fake Installed module (e.g., header labels)."""
    __tablename__ = "fake_installed_settings"

    id = Column(Integer, primary_key=True, index=True)
    # JSON serialized mapping of header keys to labels
    headers_json = Column(Text, nullable=True)


class NameplateTracker(Base):
    """Tracking nameplate (Ðêð©ð╗Ðîð┤ð©ð║) history across engines and aircraft."""
    __tablename__ = "nameplate_tracker"
    
    id = Column(Integer, primary_key=True, index=True)
    nameplate_sn = Column(String, nullable=False, index=True)  # ðíðÁÐÇð©ð╣ð¢ð©ð║ ð¢ð░ Ðêð©ð╗Ðîð┤ð©ð║ðÁ
    engine_model = Column(String, nullable=True)  # CFM56-5B, PW, etc
    gss_id = Column(String, nullable=True, index=True)  # GSS ID Ðäð©ðÀð©ÐçðÁÐüð║ð¥ð│ð¥ ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ
    engine_orig_sn = Column(String, nullable=True, index=True)  # Original SN ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ
    aircraft_tail = Column(String, nullable=True)  # ðôð┤ðÁ ÐâÐüÐéð░ð¢ð¥ð▓ð╗ðÁð¢ (NULL = ð¢ð░ Ðüð║ð╗ð░ð┤ðÁ)
    position = Column(Integer, nullable=True)  # 1,2,3,4
    installed_date = Column(String, nullable=False)  # ðÜð¥ð│ð┤ð░ ð¢ð░ð┤ðÁð╗ð©/ÐâÐüÐéð░ð¢ð¥ð▓ð©ð╗ð©
    removed_date = Column(String, nullable=True)  # ðÜð¥ð│ð┤ð░ Ðüð¢ÐÅð╗ð© (NULL = ð░ð║Ðéð©ð▓ð¢ð¥)
    location_type = Column(String, nullable=True)  # on_aircraft, on_engine_storage, detached
    action_note = Column(String, nullable=True)  # installed, swapped_under, removed, etc
    performed_by = Column(String, nullable=True)  # ðÜÐéð¥ ð┤ðÁð╗ð░ð╗
    notes = Column(Text, nullable=True)  # ðöð¥ð┐ð¥ð╗ð¢ð©ÐéðÁð╗Ðîð¢ÐïðÁ ðÀð░ð╝ðÁÐéð║ð©
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ScheduledEvent(Base):
    """ðùð░ð┐ð╗ð░ð¢ð©ÐÇð¥ð▓ð░ð¢ð¢ÐïðÁ Ðüð¥ð▒ÐïÐéð©ÐÅ ð© ð▓ÐüÐéÐÇðÁÐçð© ð▓ ð║ð░ð╗ðÁð¢ð┤ð░ÐÇðÁ"""
    __tablename__ = "scheduled_events"
    
    id = Column(Integer, primary_key=True, index=True)
    event_date = Column(String, nullable=False, index=True)  # YYYY-MM-DD
    event_time = Column(String, nullable=True)  # HH:MM (ð¥ð┐Ðåð©ð¥ð¢ð░ð╗Ðîð¢ð¥)
    event_type = Column(String, nullable=False)  # SHIPMENT, MEETING, INSPECTION, MAINTENANCE, DEADLINE, OTHER
    title = Column(String, nullable=False)  # "Engine shipment to Baku"
    description = Column(Text, nullable=True)  # ðöðÁÐéð░ð╗ð© Ðüð¥ð▒ÐïÐéð©ÐÅ
    
    # ðíð▓ÐÅðÀÐî Ðü ð┤ð▓ð©ð│ð░ÐéðÁð╗ðÁð╝ (ð¥ð┐Ðåð©ð¥ð¢ð░ð╗Ðîð¢ð¥)
    engine_id = Column(Integer, ForeignKey('engines.id'), nullable=True)
    serial_number = Column(String, nullable=True)  # ðöð╗ÐÅ ð▒ÐïÐüÐéÐÇð¥ð│ð¥ ð┤ð¥ÐüÐéÐâð┐ð░
    
    # ðøð¥ð║ð░Ðåð©ÐÅ/ð╝ð░ÐÇÐêÐÇÐâÐé (ð¥ð┐Ðåð©ð¥ð¢ð░ð╗Ðîð¢ð¥)
    location = Column(String, nullable=True)  # "Baku", "Dubai", etc.
    from_location = Column(String, nullable=True)
    to_location = Column(String, nullable=True)
    
    # ðíÐéð░ÐéÐâÐü Ðüð¥ð▒ÐïÐéð©ÐÅ
    status = Column(String, default='PLANNED')  # PLANNED, IN_PROGRESS, COMPLETED, CANCELLED
    
    # ðƒÐÇð©ð¥ÐÇð©ÐéðÁÐé ð© ð▓ð©ðÀÐâð░ð╗Ðîð¢ð¥ðÁ ð¥Ðäð¥ÐÇð╝ð╗ðÁð¢ð©ðÁ
    priority = Column(String, default='MEDIUM')  # LOW, MEDIUM, HIGH, URGENT
    color = Column(String, default='#3788d8')  # ðªð▓ðÁÐé ð┐ð╗ð░Ðêð║ð© ð¢ð░ ð║ð░ð╗ðÁð¢ð┤ð░ÐÇðÁ
    
    # ð£ðÁÐéð░ð┤ð░ð¢ð¢ÐïðÁ
    created_by = Column(String, nullable=True)  # ðÜÐéð¥ Ðüð¥ðÀð┤ð░ð╗ Ðüð¥ð▒ÐïÐéð©ðÁ
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# SHIPMENT MODEL (Logistics & Schedules Tracking)
# ============================================================
class Shipment(Base):
    """
    ð£ð¥ð┤ðÁð╗Ðî ð┤ð╗ÐÅ ð¥ÐéÐüð╗ðÁðÂð©ð▓ð░ð¢ð©ÐÅ ð¥Ðéð┐ÐÇð░ð▓ð¥ð║ ð┤ð▓ð©ð│ð░ÐéðÁð╗ðÁð╣ ð© ðÀð░ð┐Ðçð░ÐüÐéðÁð╣ ð▓ ð┐ÐâÐéð©.
    ðƒð¥ð┤ð┤ðÁÐÇðÂð©ð▓ð░ðÁÐé:
    - ENGINE type: ð¥ÐéÐüð╗ðÁðÂð©ð▓ð░ð¢ð©ðÁ ð┤ð▓ð©ð│ð░ÐéðÁð╗ðÁð╣ ð▓ ÐéÐÇð░ð¢ðÀð©ÐéðÁ
    - PARTS type: ð¥ÐéÐüð╗ðÁðÂð©ð▓ð░ð¢ð©ðÁ ðÀð░ð┐Ðçð░ÐüÐéðÁð╣ (ð▓ð║ð╗ÐÄÐçð░ÐÅ pre-order - ðÁÐëðÁ ð¢ðÁ ð▓ ÐüÐéð¥ð║ðÁ)
    
    ðƒÐÇð© ÐüÐéð░ÐéÐâÐüðÁ DELIVERED:
    - ENGINE: ð¥ð▒ð¢ð¥ð▓ð╗ÐÅðÁÐé engines.location_id ð¢ð░ "On Stock"
    - PARTS: Ðüð¥ðÀð┤ð░ðÁÐé ð¢ð¥ð▓ÐâÐÄ ðÀð░ð┐ð©ÐüÐî ð▓ store_items (ð░ð▓Ðéð¥ð©ð¢ð▓ðÁð¢Ðéð░ÐÇð©ðÀð░Ðåð©ÐÅ)
    """
    __tablename__ = "shipments"
    
    # ð×Ðüð¢ð¥ð▓ð¢ÐïðÁ ð┐ð¥ð╗ÐÅ
    id = Column(Integer, primary_key=True, index=True)
    shipment_type = Column(String(50), nullable=False)  # ENGINE, PARTS
    status = Column(String(50), default='PLANNED')  # PLANNED, IN_TRANSIT, DELIVERED, DELAYED, CANCELLED
    
    # ðöðøð» ENGINE TYPE
    engine_id = Column(Integer, ForeignKey("engines.id"), nullable=True)
    engine_model = Column(String(100), nullable=True)  # ð£ð¥ð┤ðÁð╗Ðî ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ
    gss_id = Column(String(100), nullable=True)  # GSS ID ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅ
    destination_location = Column(String(255), nullable=True)  # ðÜÐâð┤ð░ ð┤ð¥ð╗ðÂðÁð¢ ð┐ÐÇð©ð▒ÐïÐéÐî ð┤ð▓ð©ð│ð░ÐéðÁð╗Ðî
    
    # ðöðøð» PARTS TYPE
    part_name = Column(String(255), nullable=True)  # ðÿð╝ÐÅ ðÀð░ð┐Ðçð░ÐüÐéð©
    part_category = Column(String(100), nullable=True)  # Overhaul, Consumable, High-Value
    part_quantity = Column(Integer, nullable=True)  # ðÜð¥ð╗ð©ÐçðÁÐüÐéð▓ð¥ ðÀð░ð┐Ðçð░ÐüÐéðÁð╣
    reserved_quantity = Column(Integer, default=0)  # ðöð╗ÐÅ pre-order (ðÁÐëðÁ ð¢ðÁ ð▓ inventory)
    
    # ð×Ðéð┐ÐÇð░ð▓ð║ð░ ð© ð┤ð¥ÐüÐéð░ð▓ð║ð░
    departure_date = Column(DateTime, nullable=True)
    expected_delivery_date = Column(DateTime, nullable=False)
    actual_delivery_date = Column(DateTime, nullable=True)
    
    # ð×ÐéÐüð╗ðÁðÂð©ð▓ð░ð¢ð©ðÁ
    supplier_name = Column(String(255), nullable=True)
    tracking_number = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    
    # ðƒð¥ð╗ÐîðÀð¥ð▓ð░ÐéðÁð╗Ðî ð© ð▓ÐÇðÁð╝ÐÅ
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # ðíð▓ÐÅðÀð©
    engine = relationship("Engine", foreign_keys=[engine_id])


class ConditionStatus(Base):
    """ðíð┐ÐÇð░ð▓ð¥Ðçð¢ð©ð║ ÐüÐéð░ÐéÐâÐüð¥ð▓ Condition ð┤ð╗ÐÅ Store Balance"""
    __tablename__ = "condition_statuses"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    color = Column(String(20), nullable=False, default="#6c757d")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class WorkType(Base):
    """ðíð┐ÐÇð░ð▓ð¥Ðçð¢ð©ð║ Ðéð©ð┐ð¥ð▓ ÐÇð░ð▒ð¥Ðé ð┤ð╗ÐÅ Borescope Inspection"""
    __tablename__ = "work_types"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GSSAssignment(Base):
    """
    ðóð░ð▒ð╗ð©Ðåð░ ð┤ð╗ÐÅ ð¥ÐéÐüð╗ðÁðÂð©ð▓ð░ð¢ð©ÐÅ ð┐ÐÇð©Ðüð▓ð¥ðÁð¢ð©ÐÅ GSS ID (ð▓ð¢ÐâÐéÐÇð©ð║ð¥ð╝ð┐ð░ð¢ðÁð╣Ðüð║ð©Ðà ð¢ð¥ð╝ðÁÐÇð¥ð▓) ð║ ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅð╝.
    ðƒð¥ðÀð▓ð¥ð╗ÐÅðÁÐé ð¥ÐéÐüð╗ðÁðÂð©ð▓ð░ÐéÐî Ðüð╝ðÁð¢Ðâ Ðêð©ð╗Ðîð┤ð©ð║ð¥ð▓ (nameplate) ð¢ð░ ð┤ð▓ð©ð│ð░ÐéðÁð╗ÐÅÐà.
    
    ðøð¥ð│ð©ð║ð░:
    - ðòÐüð╗ð© ðÀð░ð┐ð©ÐüÐî ÐüÐâÐëðÁÐüÐéð▓ÐâðÁÐé ÔåÆ GSS ID ðÀð░ð¢ÐÅÐé
    - ðòÐüð╗ð© ðÀð░ð┐ð©Ðüð© ð¢ðÁÐé ÔåÆ GSS ID Ðüð▓ð¥ð▒ð¥ð┤ðÁð¢
    - ðƒÐÇð© DELETE ÔåÆ GSS ID ð░ð▓Ðéð¥ð╝ð░Ðéð©ÐçðÁÐüð║ð© ð¥Ðüð▓ð¥ð▒ð¥ðÂð┤ð░ðÁÐéÐüÐÅ
    """
    __tablename__ = "gss_assignments"
    
    id = Column(Integer, primary_key=True, index=True)
    gss_id = Column(Integer, nullable=False, unique=True, index=True)  # ðúð¢ð©ð║ð░ð╗Ðîð¢Ðïð╣ GSS ID
    
    # ðíð▓ÐÅðÀÐî Ðü ð┤ð▓ð©ð│ð░ÐéðÁð╗ðÁð╝
    engine_id = Column(Integer, ForeignKey("engines.id", ondelete="CASCADE"), nullable=False)
    original_sn = Column(String, nullable=False)  # Snapshot Original SN ð¢ð░ ð╝ð¥ð╝ðÁð¢Ðé ð┐ÐÇð©Ðüð▓ð¥ðÁð¢ð©ÐÅ
    current_sn = Column(String, nullable=True)    # Snapshot Current SN (ðÁÐüð╗ð© ð¥Ðéð╗ð©Ðçð░ðÁÐéÐüÐÅ)
    
    # ð£ðÁð┤ð©ð░ ð© ð┐ÐÇð©ð╝ðÁÐçð░ð¢ð©ÐÅ
    photo_url = Column(String, nullable=True)      # URL Ðäð¥Ðéð¥ (ðÁÐüð╗ð© ð▓ÐüÐéð░ð▓ð╗ðÁð¢ð░ ÐüÐüÐïð╗ð║ð░)
    photo_filename = Column(String, nullable=True) # ðÿð╝ÐÅ Ðäð░ð╣ð╗ð░ (ðÁÐüð╗ð© ðÀð░ð│ÐÇÐâðÂðÁð¢ Ðäð░ð╣ð╗)
    remarks = Column(Text, nullable=True)          # ðƒÐÇð©ð╝ðÁÐçð░ð¢ð©ÐÅ
    
    # ð£ðÁÐéð░ð┤ð░ð¢ð¢ÐïðÁ
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_date = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    engine = relationship("Engine", backref="gss_assignment")
    user = relationship("User", backref="gss_assignments")

