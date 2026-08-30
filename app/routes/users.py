from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user, require_admin_or_officer, hash_password
from app.database import get_db
from app.sse_manager import sse_manager

router = APIRouter(prefix="/users", tags=["Users"])


# ─── List all workers in same company (officer/admin only) ────────────────────

@router.get("", response_model=schemas.APIResponse[list[schemas.UserOut]])
def list_users(
    current_user: models.User = Depends(require_admin_or_officer),
    db: Session = Depends(get_db),
):
    users = (
        db.query(models.User)
        .filter(models.User.company_id == current_user.company_id, models.User.is_active == True)
        .order_by(models.User.full_name)
        .all()
    )
    return schemas.APIResponse(data=[schemas.UserOut.model_validate(u) for u in users])


# ─── Add new worker ───────────────────────────────────────────────────────────

@router.post("", response_model=schemas.APIResponse[schemas.UserOut], status_code=status.HTTP_201_CREATED)
def create_user(
    body: schemas.WorkerCreate,
    current_user: models.User = Depends(require_admin_or_officer),
    db: Session = Depends(get_db),
):
    # Check limit
    company = current_user.company
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
        
    if company.current_users >= company.max_users:
        raise HTTPException(status_code=403, detail=f"Worker limit reached ({company.max_users})")

    existing = (
        db.query(models.User)
        .filter(models.User.employee_id == body.employee_id, models.User.company_id == company.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Employee ID already exists")

    user = models.User(
        company_id=company.id,
        full_name=body.full_name,
        employee_id=body.employee_id,
        phone=body.phone,
        unit=body.unit,
        department=body.department,
        position=body.position,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.flush()
    # Auto-create empty medical profile
    db.add(models.MedicalProfile(user_id=user.id))
    company.current_users += 1
    db.commit()
    db.refresh(user)

    return schemas.APIResponse(
        data=schemas.UserOut.model_validate(user),
        message="Worker created"
    )


# ─── Get single user profile + medical profile ───────────────────────────────

@router.get("/{user_id}", response_model=schemas.APIResponse[schemas.UserOut])
def get_user(
    user_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Workers can only see their own profile; officers/admins see their company
    if current_user.role == models.UserRole.worker:
        if str(user.id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.role != models.UserRole.super_admin:
        if str(user.company_id) != str(current_user.company_id):
            raise HTTPException(status_code=403, detail="Access denied")

    return schemas.APIResponse(data=schemas.UserOut.model_validate(user))


# ─── Update single user profile ───────────────────────────────────────────────

@router.put("/{user_id}", response_model=schemas.APIResponse[schemas.UserOut])
def update_user(
    user_id: str,
    body: schemas.WorkerUpdate,
    current_user: models.User = Depends(require_admin_or_officer),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if current_user.role != models.UserRole.super_admin:
        if str(user.company_id) != str(current_user.company_id):
            raise HTTPException(status_code=403, detail="Access denied")

    # Check for employee_id conflict if changed
    if body.employee_id and body.employee_id != user.employee_id:
        existing = (
            db.query(models.User)
            .filter(models.User.employee_id == body.employee_id, models.User.company_id == user.company_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Employee ID already exists")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return schemas.APIResponse(data=schemas.UserOut.model_validate(user), message="User updated")


# ─── Deactivate user ─────────────────────────────────────────────────────────

@router.delete("/{user_id}", response_model=schemas.APIResponse[None])
def deactivate_user(
    user_id: str,
    current_user: models.User = Depends(require_admin_or_officer),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if current_user.role != models.UserRole.super_admin:
        if str(user.company_id) != str(current_user.company_id):
            raise HTTPException(status_code=403, detail="Access denied")

    if str(user.id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    user.is_active = False
    
    # We could decrease company.current_users here if needed, but let's keep it simple
    company = user.company
    if company.current_users > 0:
        company.current_users -= 1
        
    db.commit()
    return schemas.APIResponse(data=None, message="User deactivated")


# ─── Upsert medical profile (Self) ────────────────────────────────────────────

@router.put("/medical-profile", response_model=schemas.APIResponse[schemas.MedicalProfileOut])
def upsert_medical_profile(
    body: schemas.MedicalProfileCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(models.MedicalProfile)
        .filter(models.MedicalProfile.user_id == current_user.id)
        .first()
    )

    if profile:
        # Update existing
        for field, value in body.model_dump(exclude_unset=False).items():
            setattr(profile, field, value)
        profile.updated_at = datetime.now(timezone.utc)
    else:
        # Create new
        profile = models.MedicalProfile(user_id=current_user.id, **body.model_dump())
        db.add(profile)

    db.commit()
    db.refresh(profile)
    return schemas.APIResponse(
        data=schemas.MedicalProfileOut.model_validate(profile),
        message="Medical profile updated",
    )


# ─── Upsert medical profile (Admin/Officer) ───────────────────────────────────

@router.put("/{user_id}/medical-profile", response_model=schemas.APIResponse[schemas.MedicalProfileOut])
def upsert_user_medical_profile(
    user_id: str,
    body: schemas.MedicalProfileCreate,
    current_user: models.User = Depends(require_admin_or_officer),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if current_user.role != models.UserRole.super_admin:
        if str(target.company_id) != str(current_user.company_id):
            raise HTTPException(status_code=403, detail="Access denied")

    profile = db.query(models.MedicalProfile).filter(models.MedicalProfile.user_id == target.id).first()

    if profile:
        for field, value in body.model_dump(exclude_unset=False).items():
            setattr(profile, field, value)
        profile.updated_at = datetime.now(timezone.utc)
    else:
        profile = models.MedicalProfile(user_id=target.id, **body.model_dump())
        db.add(profile)

    db.commit()
    db.refresh(profile)
    return schemas.APIResponse(
        data=schemas.MedicalProfileOut.model_validate(profile),
        message="Medical profile updated",
    )


# ─── Update last-seen heartbeat ───────────────────────────────────────────────

@router.put("/last-seen", response_model=schemas.APIResponse[schemas.UserLastSeen])
def update_last_seen(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    current_user.last_seen = now
    db.commit()
    return schemas.APIResponse(
        data=schemas.UserLastSeen(last_seen=now),
        message="Last seen updated",
    )


# ─── Update location heartbeat ────────────────────────────────────────────────

@router.put("/heartbeat", response_model=schemas.APIResponse)
def update_location_heartbeat(
    body: schemas.UserHeartbeat,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.latitude = body.latitude
    current_user.longitude = body.longitude
    current_user.location_updated_at = datetime.now(timezone.utc)
    db.commit()
    return schemas.APIResponse(
        success=True,
        message="Worker location heartbeat updated"
    )

# ─── Update live location ──────────────────────────────────────────────────────────

@router.put("/location", response_model=schemas.APIResponse[dict])
async def update_location(
    body: schemas.LocationUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Worker app calls this every ~15 s to report its live GPS position.
    Persists lat/lng on the User row and broadcasts a WORKER_LOCATION_UPDATED
    SSE event so the dashboard map updates in real-time.
    """
    # Persist coordinates
    current_user.last_lat = body.latitude
    current_user.last_lng = body.longitude
    db.commit()

    # Derive worker status: emergency if they have an active emergency, else active
    has_active_emergency = (
        db.query(models.Emergency)
        .filter(
            models.Emergency.user_id == current_user.id,
            models.Emergency.status == models.EmergencyStatus.active,
        )
        .first()
    ) is not None

    worker_status = "emergency" if has_active_emergency else "active"

    payload = {
        "user_id":     str(current_user.id),
        "lat":         body.latitude,
        "lng":         body.longitude,
        "status":      worker_status,
        "full_name":   current_user.full_name,
        "employee_id": current_user.employee_id,
    }

    await sse_manager.broadcast(
        company_id = str(current_user.company_id),
        event_type = "WORKER_LOCATION_UPDATED",
        data       = payload,
    )

    return schemas.APIResponse(data=payload, message="Location updated")


# ─── FCM & Duty ───────────────────────────────────────────────────────────────

@router.put("/duty", response_model=schemas.APIResponse[schemas.UserOut])
def update_duty(
    body: schemas.DutyUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.is_on_duty = body.is_on_duty
    db.commit()
    db.refresh(current_user)
    return schemas.APIResponse(
        data=schemas.UserOut.model_validate(current_user),
        message=f"Duty status updated to {body.is_on_duty}"
    )

@router.post("/fcm-tokens", response_model=schemas.APIResponse[None])
def register_fcm_token(
    body: schemas.FCMTokenRegister,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(models.FCMToken).filter(models.FCMToken.token == body.token).first()
    if existing:
        # If token belongs to someone else (e.g. user logged out and logged in), reassign
        existing.user_id = current_user.id
        existing.device_info = body.device_info
        existing.last_used_at = datetime.now(timezone.utc)
    else:
        new_token = models.FCMToken(
            user_id=current_user.id,
            token=body.token,
            device_info=body.device_info
        )
        db.add(new_token)
    db.commit()
    return schemas.APIResponse(data=None, message="Token registered")

@router.delete("/fcm-tokens/{token}", response_model=schemas.APIResponse[None])
def delete_fcm_token(
    token: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    token_record = db.query(models.FCMToken).filter(
        models.FCMToken.token == token,
        models.FCMToken.user_id == current_user.id
    ).first()
    if token_record:
        db.delete(token_record)
        db.commit()
    return schemas.APIResponse(data=None, message="Token deleted")
