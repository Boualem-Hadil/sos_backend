from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user
from app.database import get_db

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.get("/{company_id}", response_model=schemas.APIResponse[schemas.CompanyStats])
def get_company(
    company_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Access control: only members of the company or super_admin
    if (str(current_user.company_id) != company_id
            and current_user.role != models.UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    active_emergencies = (
        db.query(func.count(models.Emergency.id))
        .filter(
            models.Emergency.company_id == company.id,
            models.Emergency.status     == models.EmergencyStatus.active,
        )
        .scalar()
    )
    total_emergencies = (
        db.query(func.count(models.Emergency.id))
        .filter(models.Emergency.company_id == company.id)
        .scalar()
    )

    stats = schemas.CompanyStats.model_validate(company)
    stats.active_emergencies = active_emergencies
    stats.total_emergencies  = total_emergencies

    return schemas.APIResponse(data=stats)
