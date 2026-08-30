import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, Integer, Float, Text,
    DateTime, Date, ForeignKey, Enum as SAEnum,
    UniqueConstraint, ARRAY
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database import Base


# ─── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    worker          = "worker"
    safety_officer  = "safety_officer"
    company_admin   = "company_admin"
    super_admin     = "super_admin"


class EmergencyStatus(str, enum.Enum):
    active             = "active"
    resolved           = "resolved"
    false_alarm        = "false_alarm"
    cancelled_by_worker = "cancelled_by_worker"   # worker-initiated end, not officer resolution


# NEW — responder type for officer resolution
class ResponderType(str, enum.Enum):
    police = "police"
    samu   = "samu"
    fire   = "fire"
    other  = "other"


class MessageType(str, enum.Enum):
    text = "text"
    voice = "voice"
    system = "system"


# ─── Company ──────────────────────────────────────────────────────────────────

class Company(Base):
    __tablename__ = "companies"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name               = Column(String(255), nullable=False)
    industry           = Column(String(100), nullable=False)          # factory, oil, construction, mining
    company_code       = Column(String(100), unique=True, nullable=False)  # e.g. SONATRACH-2024
    contact_email      = Column(String(255), nullable=True)           # for license expiry notifications
    max_users          = Column(Integer, nullable=False, default=50)
    current_users      = Column(Integer, nullable=False, default=0)
    sos_hotline_phone  = Column(String(30), nullable=True)
    subscription_start = Column(Date, nullable=True)
    subscription_end   = Column(Date, nullable=True)
    is_active          = Column(Boolean, nullable=False, default=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    users       = relationship("User",      back_populates="company", cascade="all, delete-orphan")
    emergencies = relationship("Emergency", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Company {self.name} ({self.company_code})>"


# ─── User ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id    = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    full_name     = Column(String(255), nullable=False)
    employee_id   = Column(String(100), nullable=False)   # company badge number
    phone         = Column(String(30), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role          = Column(SAEnum(UserRole), nullable=False, default=UserRole.worker)
    is_active     = Column(Boolean, nullable=False, default=True)
    is_on_duty    = Column(Boolean, nullable=False, default=False)
    assigned_officer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    last_seen     = Column(DateTime(timezone=True), nullable=True)
    # Live location — updated by worker app every ~15 s while foregrounded
    last_lat      = Column(Float, nullable=True)
    last_lng      = Column(Float, nullable=True)
    
    # Extra profile fields
    unit          = Column(String(100), nullable=True)
    department    = Column(String(100), nullable=True)
    position      = Column(String(100), nullable=True)

    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    latitude      = Column(Float, nullable=True)
    longitude     = Column(Float, nullable=True)
    location_updated_at = Column(DateTime(timezone=True), nullable=True)
    unit          = Column(String(100), nullable=True)

    # employee_id must be unique per company
    __table_args__ = (
        UniqueConstraint("employee_id", "company_id", name="uq_employee_company"),
    )

    # Relationships
    company         = relationship("Company",        back_populates="users")
    medical_profile = relationship("MedicalProfile", back_populates="user",
                                   uselist=False, cascade="all, delete-orphan")
    emergencies     = relationship("Emergency",      back_populates="user")

    def __repr__(self):
        return f"<User {self.full_name} [{self.employee_id}]>"


# ─── Medical Profile ──────────────────────────────────────────────────────────

class MedicalProfile(Base):
    __tablename__ = "medical_profiles"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id              = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                  unique=True, nullable=False)
    blood_type           = Column(String(10), nullable=True)
    is_universal_donor   = Column(Boolean, nullable=False, default=False)
    chronic_diseases     = Column(ARRAY(String), nullable=False, default=list)
    allergies            = Column(ARRAY(String), nullable=False, default=list)
    emergency_notes      = Column(Text, nullable=True)
    ice_contact_name     = Column(String(255), nullable=True)
    ice_contact_relation = Column(String(100), nullable=True)
    ice_contact_phone    = Column(String(30), nullable=True)
    updated_at           = Column(DateTime(timezone=True), server_default=func.now(),
                                  onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="medical_profile")

    def __repr__(self):
        return f"<MedicalProfile user_id={self.user_id}>"


# ─── Emergency ────────────────────────────────────────────────────────────────

class Emergency(Base):
    __tablename__ = "emergencies"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id              = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
                                  nullable=True)
    company_id           = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
                                  nullable=False)
    type                 = Column(String(50), nullable=False)   # Cardiac, Respiratory, Trauma …
    severity             = Column(String(20), nullable=False)   # Critical, Moderate, Low
    latitude             = Column(Float, nullable=True)
    longitude            = Column(Float, nullable=True)
    location_description = Column(String(500), nullable=True)
    status               = Column(SAEnum(EmergencyStatus), nullable=False,
                                  default=EmergencyStatus.active)
    started_at           = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at          = Column(DateTime(timezone=True), nullable=True)
    notes                = Column(Text, nullable=True)
    # ── Resolution fields (added for officer resolution flow) ──────────────
    responder_type       = Column(SAEnum(ResponderType), nullable=True)   # NEW
    eta_minutes          = Column(Integer, nullable=True)                  # NEW

    # ── Worker-activity & ping tracking (added for nearby-workers feature) ─
    last_seen_active     = Column(DateTime(timezone=True), nullable=True)  # NEW: updated on any worker action during emergency
    ping_sent_at         = Column(DateTime(timezone=True), nullable=True)  # NEW: when officer last sent "are you OK?" ping
    ping_acked_at        = Column(DateTime(timezone=True), nullable=True)  # NEW: when worker acknowledged the ping

    # ── Conditional GPS heartbeat (last reported position during emergency) ─
    # NOTE: latitude/longitude columns already exist (initial report position).
    # heartbeat_lat/lng track the *latest* live position while emergency is active.
    heartbeat_lat        = Column(Float, nullable=True)                    # NEW
    heartbeat_lng        = Column(Float, nullable=True)                    # NEW

    # Relationships
    user    = relationship("User",    back_populates="emergencies")
    company = relationship("Company", back_populates="emergencies")

    def __repr__(self):
        return f"<Emergency {self.type} [{self.status}]>"


# ─── Notification Recipients (configurable from admin panel) ──────────────────

class NotificationRecipient(Base):
    __tablename__ = "notification_recipients"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email      = Column(String(255), nullable=False, unique=True)
    name       = Column(String(255), nullable=False)
    is_active  = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<NotificationRecipient {self.email}>"


# ─── FCM Token ────────────────────────────────────────────────────────────────

class FCMToken(Base):
    __tablename__ = "fcm_tokens"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token        = Column(String(500), unique=True, nullable=False)
    device_info  = Column(String(255), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")


# ─── Message ──────────────────────────────────────────────────────────────────

class Message(Base):
    __tablename__ = "messages"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    emergency_id     = Column(UUID(as_uuid=True), ForeignKey("emergencies.id", ondelete="CASCADE"), nullable=False)
    sender_id        = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sender_role      = Column(String(50), nullable=False, default="worker")
    message_type     = Column(SAEnum(MessageType), nullable=False, default=MessageType.text)
    content          = Column(Text, nullable=True)
    file_url         = Column(String(500), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    emergency = relationship("Emergency")
    sender    = relationship("User")
