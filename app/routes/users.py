from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user, require_admin_or_officer
from app.database import get_db

router = APIRouter(prefix="/users", tags=["Users"])


# ─── List all workers in same company (officer/admin only) ────────────────────

@router.get("", response_model=schemas.APIResponse[list[schemas.UserOut]])
def list_users(
    current_user: models.User = Depends(require_admin_or_officer),
    db: Session = Depends(get_db),
):
    users = (
        db.query(models.User)
        .filter(models.User.company_id == current_user.company_id)
        .order_by(models.User.full_name)
        .all()
    )
    return schemas.APIResponse(data=[schemas.UserOut.model_validate(u) for u in users])


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


# ─── Upsert medical profile ───────────────────────────────────────────────────

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
