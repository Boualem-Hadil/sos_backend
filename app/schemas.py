from __future__ import annotations
from datetime import datetime, date
from typing import Any, Generic, List, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models import EmergencyStatus, UserRole

T = TypeVar("T")


# ─── Generic Response Wrapper ─────────────────────────────────────────────────

class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    message: str = "OK"


# ─── Token ────────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: UUID
    company_id: UUID
    role: UserRole


# ─── Company ──────────────────────────────────────────────────────────────────

class CompanyBase(BaseModel):
    name: str
    industry: str
    company_code: str
    max_users: int = 50
    subscription_start: Optional[date] = None
    subscription_end: Optional[date] = None

    @field_validator("company_code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.upper().strip()


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    max_users: Optional[int] = None
    is_active: Optional[bool] = None
    subscription_end: Optional[date] = None
    name: Optional[str] = None
    industry: Optional[str] = None


class CompanyOut(BaseModel):
    id: UUID
    name: str
    industry: str
    company_code: str
    max_users: int
    current_users: int
    subscription_start: Optional[date]
    subscription_end: Optional[date]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CompanyStats(CompanyOut):
    active_emergencies: int = 0
    total_emergencies: int = 0


# ─── Medical Profile ──────────────────────────────────────────────────────────

class MedicalProfileBase(BaseModel):
    blood_type: Optional[str] = None
    is_universal_donor: bool = False
    chronic_diseases: List[str] = []
    allergies: List[str] = []
    emergency_notes: Optional[str] = None
    ice_contact_name: Optional[str] = None
    ice_contact_relation: Optional[str] = None
    ice_contact_phone: Optional[str] = None


class MedicalProfileCreate(MedicalProfileBase):
    pass


class MedicalProfileOut(MedicalProfileBase):
    id: UUID
    user_id: UUID
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── User ─────────────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    full_name: str
    employee_id: str
    phone: Optional[str] = None


class UserRegister(UserBase):
    password: str = Field(min_length=6)
    company_code: str

    @field_validator("company_code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.upper().strip()


class UserLogin(BaseModel):
    employee_id: str
    password: str
    company_code: str

    @field_validator("company_code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.upper().strip()


class UserOut(UserBase):
    id: UUID
    company_id: UUID
    role: UserRole
    is_active: bool
    last_seen: Optional[datetime]
    created_at: datetime
    medical_profile: Optional[MedicalProfileOut] = None

    model_config = {"from_attributes": True}


class UserWithCompany(UserOut):
    company: Optional[CompanyOut] = None


class UserLastSeen(BaseModel):
    last_seen: datetime


# ─── Auth Responses ───────────────────────────────────────────────────────────

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserWithCompany


class RegisterResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── Emergency ────────────────────────────────────────────────────────────────

EMERGENCY_TYPES = [
    "Cardiac", "Respiratory", "Trauma", "Fire",
    "Neurological", "Poisoning", "Medical", "Police"
]
SEVERITY_LEVELS = ["Critical", "Moderate", "Low"]


class EmergencyCreate(BaseModel):
    type: str
    severity: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_description: Optional[str] = None

    @field_validator("type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in EMERGENCY_TYPES:
            raise ValueError(f"type must be one of {EMERGENCY_TYPES}")
        return v

    @field_validator("severity")
    @classmethod
    def valid_severity(cls, v: str) -> str:
        if v not in SEVERITY_LEVELS:
            raise ValueError(f"severity must be one of {SEVERITY_LEVELS}")
        return v


class EmergencyResolve(BaseModel):
    status: EmergencyStatus   # resolved | false_alarm
    notes: Optional[str] = None


class EmergencyOut(BaseModel):
    id: UUID
    user_id: Optional[UUID]
    company_id: UUID
    type: str
    severity: str
    latitude: Optional[float]
    longitude: Optional[float]
    location_description: Optional[str]
    status: EmergencyStatus
    started_at: datetime
    resolved_at: Optional[datetime]
    notes: Optional[str]

    model_config = {"from_attributes": True}


class EmergencyDetail(EmergencyOut):
    user: Optional[UserOut] = None
    medical_profile: Optional[MedicalProfileOut] = None


class EmergencyPage(BaseModel):
    items: List[EmergencyOut]
    total: int
    page: int
    limit: int
    pages: int


# ─── SSE Payloads ─────────────────────────────────────────────────────────────

class SSEEmergencyStarted(BaseModel):
    emergency: EmergencyOut
    user: Optional[UserOut]
    medical_profile: Optional[MedicalProfileOut]
    company: CompanyOut


class SSEEmergencyResolved(BaseModel):
    emergency_id: UUID
    status: EmergencyStatus


# ─── Admin Stats ──────────────────────────────────────────────────────────────

class AdminStats(BaseModel):
    total_companies: int
    total_users: int
    total_emergencies_today: int
    active_emergencies: int
