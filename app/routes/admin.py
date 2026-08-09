from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import hash_password, require_super_admin
from app.database import get_db

router = APIRouter(prefix="/admin", tags=["Admin"])


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

    today = date.today()
    cutoff_30 = today + timedelta(days=30)
    expiring_soon = (
        db.query(func.count(models.Company.id))
        .filter(
            models.Company.subscription_end != None,
            models.Company.subscription_end >= today,
            models.Company.subscription_end <= cutoff_30,
            models.Company.company_code != "SUPER-ADMIN",
        )
        .scalar()
    )
    expired = (
        db.query(func.count(models.Company.id))
        .filter(
            models.Company.subscription_end != None,
            models.Company.subscription_end < today,
            models.Company.company_code != "SUPER-ADMIN",
        )
        .scalar()
    )

    return schemas.APIResponse(
        data=schemas.AdminStats(
            total_companies         = total_companies,
            total_users             = total_users,
            total_emergencies_today = emergencies_today,
            active_emergencies      = active_emergencies,
            expiring_soon           = expiring_soon,
            expired                 = expired,
        )
    )


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
        contact_email      = body.contact_email,
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
    companies = (
        db.query(models.Company)
        .filter(models.Company.company_code != "SUPER-ADMIN")
        .order_by(models.Company.name)
        .all()
    )
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


# ─── Expiring Companies ───────────────────────────────────────────────────────

@router.get("/companies/expiring",
            response_model=schemas.APIResponse[list[schemas.CompanyStats]])
def expiring_companies(
    days: int = 30,
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Return companies whose license expires within `days` days (or is already expired)."""
    today  = date.today()
    cutoff = today + timedelta(days=days)

    companies = (
        db.query(models.Company)
        .filter(
            models.Company.subscription_end != None,
            models.Company.subscription_end <= cutoff,
            models.Company.company_code != "SUPER-ADMIN",
        )
        .order_by(models.Company.subscription_end)
        .all()
    )

    result = []
    for c in companies:
        stats = schemas.CompanyStats.model_validate(c)
        stats.active_emergencies = 0
        stats.total_emergencies  = 0
        result.append(stats)

    return schemas.APIResponse(data=result)


# ─── Create Safety Officer ────────────────────────────────────────────────────

@router.post("/officers",
             response_model=schemas.APIResponse[schemas.UserOut],
             status_code=status.HTTP_201_CREATED)
def create_officer(
    body: schemas.OfficerCreate,
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    # Validate company exists
    company = db.query(models.Company).filter(models.Company.id == body.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if not company.is_active:
        raise HTTPException(status_code=403, detail="Company is deactivated")

    if company.current_users >= company.max_users:
        raise HTTPException(
            status_code=403,
            detail=f"Worker limit reached for this company ({company.max_users})",
        )

    # Check duplicate employee_id in company
    existing = (
        db.query(models.User)
        .filter(
            models.User.employee_id == body.employee_id,
            models.User.company_id  == company.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Employee ID already in use for this company")

    officer = models.User(
        company_id    = company.id,
        full_name     = body.full_name,
        employee_id   = body.employee_id,
        phone         = body.phone,
        password_hash = hash_password(body.password),
        role          = models.UserRole.safety_officer,
    )
    db.add(officer)
    db.flush()
    db.add(models.MedicalProfile(user_id=officer.id, chronic_diseases=[], allergies=[]))
    company.current_users += 1
    db.commit()
    db.refresh(officer)

    return schemas.APIResponse(
        data    = schemas.UserOut.model_validate(officer),
        message = "Safety officer created",
    )


# ─── List Officers ────────────────────────────────────────────────────────────

@router.get("/officers",
            response_model=schemas.APIResponse[list[schemas.UserOut]])
def list_officers(
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    officers = (
        db.query(models.User)
        .filter(
            models.User.role.in_([
                models.UserRole.safety_officer,
                models.UserRole.company_admin,
            ])
        )
        .order_by(models.User.full_name)
        .all()
    )
    return schemas.APIResponse(
        data=[schemas.UserOut.model_validate(o) for o in officers]
    )


# ─── Deactivate Officer ───────────────────────────────────────────────────────

@router.delete("/officers/{user_id}",
               response_model=schemas.APIResponse[None])
def deactivate_officer(
    user_id: str,
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    officer = db.query(models.User).filter(models.User.id == user_id).first()
    if not officer:
        raise HTTPException(status_code=404, detail="User not found")
    if officer.role == models.UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Cannot deactivate super admin")

    officer.is_active = False
    db.commit()
    return schemas.APIResponse(data=None, message="Officer deactivated")


# ─── Notification Recipients ──────────────────────────────────────────────────

@router.get("/notification-recipients",
            response_model=schemas.APIResponse[list[schemas.NotificationRecipientOut]])
def list_notification_recipients(
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    recipients = (
        db.query(models.NotificationRecipient)
        .order_by(models.NotificationRecipient.name)
        .all()
    )
    return schemas.APIResponse(
        data=[schemas.NotificationRecipientOut.model_validate(r) for r in recipients]
    )


@router.post("/notification-recipients",
             response_model=schemas.APIResponse[schemas.NotificationRecipientOut],
             status_code=status.HTTP_201_CREATED)
def add_notification_recipient(
    body: schemas.NotificationRecipientCreate,
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(models.NotificationRecipient)
        .filter(models.NotificationRecipient.email == body.email)
        .first()
    )
    if existing:
        # Re-activate if previously removed
        existing.is_active = True
        existing.name = body.name
        db.commit()
        db.refresh(existing)
        return schemas.APIResponse(
            data=schemas.NotificationRecipientOut.model_validate(existing),
            message="Recipient re-activated",
        )

    recipient = models.NotificationRecipient(email=body.email, name=body.name)
    db.add(recipient)
    db.commit()
    db.refresh(recipient)
    return schemas.APIResponse(
        data=schemas.NotificationRecipientOut.model_validate(recipient),
        message="Recipient added",
    )


@router.delete("/notification-recipients/{recipient_id}",
               response_model=schemas.APIResponse[None])
def remove_notification_recipient(
    recipient_id: str,
    _: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    recipient = (
        db.query(models.NotificationRecipient)
        .filter(models.NotificationRecipient.id == recipient_id)
        .first()
    )
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    recipient.is_active = False
    db.commit()
    return schemas.APIResponse(data=None, message="Recipient removed")
