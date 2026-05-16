from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import require_super_admin
from app.database import get_db

router = APIRouter(prefix="/admin", tags=["Admin"])


# ─── Create Company ───────────────────────────────────────────────────────────

@router.post("/companies",
             response_model=schemas.APIResponse[schemas.CompanyOut],
             status_code=status.HTTP_201_CREATED)
def create_company(
    body: schemas.CompanyCreate,
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(models.Company)
        .filter(models.Company.company_code == body.company_code)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Company code already in use")

    company = models.Company(
        name               = body.name,
        industry           = body.industry,
        company_code       = body.company_code.upper(),
        max_users          = body.max_users,
        subscription_start = body.subscription_start or date.today(),
        subscription_end   = body.subscription_end,
        is_active          = True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    return schemas.APIResponse(
        data    = schemas.CompanyOut.model_validate(company),
        message = "Company created",
    )


# ─── List All Companies ───────────────────────────────────────────────────────

@router.get("/companies",
            response_model=schemas.APIResponse[list[schemas.CompanyStats]])
def list_companies(
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    companies = db.query(models.Company).order_by(models.Company.name).all()
    result = []
    for c in companies:
        active_em = (
            db.query(func.count(models.Emergency.id))
            .filter(
                models.Emergency.company_id == c.id,
                models.Emergency.status     == models.EmergencyStatus.active,
            )
            .scalar()
        )
        total_em = (
            db.query(func.count(models.Emergency.id))
            .filter(models.Emergency.company_id == c.id)
            .scalar()
        )
        stats = schemas.CompanyStats.model_validate(c)
        stats.active_emergencies = active_em
        stats.total_emergencies  = total_em
        result.append(stats)

    return schemas.APIResponse(data=result)


# ─── Update Company ───────────────────────────────────────────────────────────

@router.put("/companies/{company_id}",
            response_model=schemas.APIResponse[schemas.CompanyOut])
def update_company(
    company_id: str,
    body: schemas.CompanyUpdate,
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(company, field, value)

    db.commit()
    db.refresh(company)
    return schemas.APIResponse(
        data    = schemas.CompanyOut.model_validate(company),
        message = "Company updated",
    )


# ─── Platform Stats ───────────────────────────────────────────────────────────

@router.get("/stats", response_model=schemas.APIResponse[schemas.AdminStats])
def admin_stats(
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    total_companies = db.query(func.count(models.Company.id)).scalar()
    total_users     = db.query(func.count(models.User.id)).scalar()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    emergencies_today = (
        db.query(func.count(models.Emergency.id))
        .filter(models.Emergency.started_at >= today_start)
        .scalar()
    )
    active_emergencies = (
        db.query(func.count(models.Emergency.id))
        .filter(models.Emergency.status == models.EmergencyStatus.active)
        .scalar()
    )

    return schemas.APIResponse(
        data=schemas.AdminStats(
            total_companies         = total_companies,
            total_users             = total_users,
            total_emergencies_today = emergencies_today,
            active_emergencies      = active_emergencies,
        )
    )
