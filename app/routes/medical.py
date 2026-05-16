from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user
from app.database import get_db

router = APIRouter(prefix="/medical", tags=["Medical Profiles"])


@router.get("/me", response_model=schemas.APIResponse[schemas.MedicalProfileOut])
def get_my_medical_profile(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch the current user's own medical profile."""
    profile = (
        db.query(models.MedicalProfile)
        .filter(models.MedicalProfile.user_id == current_user.id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Medical profile not found")
    return schemas.APIResponse(data=schemas.MedicalProfileOut.model_validate(profile))


@router.get("/{user_id}", response_model=schemas.APIResponse[schemas.MedicalProfileOut])
def get_user_medical_profile(
    user_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fetch another user's medical profile.
    Workers can only access their own; officers/admins see their company.
    """
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if current_user.role == models.UserRole.worker:
        if str(target.id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.role != models.UserRole.super_admin:
        if str(target.company_id) != str(current_user.company_id):
            raise HTTPException(status_code=403, detail="Access denied")

    profile = (
        db.query(models.MedicalProfile)
        .filter(models.MedicalProfile.user_id == user_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Medical profile not found")

    return schemas.APIResponse(data=schemas.MedicalProfileOut.model_validate(profile))
