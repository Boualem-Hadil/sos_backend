"""
Company Admin routes — /company-admin/*

All endpoints here are exclusively for company_admin (and super_admin who
inherits the role-guard). The company_id is ALWAYS derived from the
authenticated user's JWT — it is never accepted from the request body.

Audit logging is performed inline for: officer_created, officer_deactivated,
officer_reactivated, password_reset.
"""
import json
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import hash_password, require_company_admin
from app.database import get_db

router = APIRouter(prefix="/company-admin", tags=["Company Admin"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _write_audit(
    db: Session,
    company_id,
    actor_id,
    action: str,
    target_id=None,
    target_name: Optional[str] = None,
    meta: Optional[dict] = None,
):
    log = models.AuditLog(
        company_id  = company_id,
        actor_id    = actor_id,
        action      = action,
        target_id   = target_id,
        target_name = target_name,
        meta        = json.dumps(meta) if meta else None,
    )
    db.add(log)


def _get_officer_in_company(user_id: str, company_id, db: Session) -> models.User:
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.company_id == company_id,
        models.User.role == models.UserRole.safety_officer,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Officer not found in this company")
    return user


# ─── Overview Stats ───────────────────────────────────────────────────────────

@router.get("/overview", response_model=schemas.APIResponse[schemas.CompanyAdminStats])
def company_admin_overview(
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id

    total_officers = (
        db.query(func.count(models.User.id))
        .filter(
            models.User.company_id == cid,
            models.User.role == models.UserRole.safety_officer,
            models.User.is_active == True,
        )
        .scalar()
    )
    total_workers = (
        db.query(func.count(models.User.id))
        .filter(
            models.User.company_id == cid,
            models.User.role == models.UserRole.worker,
            models.User.is_active == True,
        )
        .scalar()
    )
    total_departments = (
        db.query(func.count(models.Department.id))
        .filter(
            models.Department.company_id == cid,
            models.Department.is_active == True,
        )
        .scalar()
    )

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    month_open = (
        db.query(func.count(models.Emergency.id))
        .filter(
            models.Emergency.company_id == cid,
            models.Emergency.started_at >= month_start,
            models.Emergency.status == models.EmergencyStatus.active,
        )
        .scalar()
    )
    month_resolved_q = (
        db.query(models.Emergency)
        .filter(
            models.Emergency.company_id == cid,
            models.Emergency.started_at >= month_start,
            models.Emergency.status == models.EmergencyStatus.resolved,
            models.Emergency.resolved_at != None,
        )
        .all()
    )
    month_resolved = len(month_resolved_q)

    durations = [
        (e.resolved_at - e.started_at).total_seconds() / 60
        for e in month_resolved_q
        if e.resolved_at and e.started_at
    ]
    avg_minutes = round(sum(durations) / len(durations), 1) if durations else None

    return schemas.APIResponse(
        data=schemas.CompanyAdminStats(
            total_officers             = total_officers or 0,
            total_workers              = total_workers or 0,
            total_departments          = total_departments or 0,
            month_emergencies_open     = month_open or 0,
            month_emergencies_resolved = month_resolved,
            avg_response_minutes       = avg_minutes,
        )
    )


# ─── Officers ─────────────────────────────────────────────────────────────────

@router.get("/officers", response_model=schemas.APIResponse[list[schemas.UserOut]])
def list_officers(
    include_inactive: bool = Query(False),
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    q = db.query(models.User).filter(
        models.User.company_id == current_user.company_id,
        models.User.role == models.UserRole.safety_officer,
    )
    if not include_inactive:
        q = q.filter(models.User.is_active == True)
    officers = q.order_by(models.User.full_name).all()
    return schemas.APIResponse(data=[schemas.UserOut.model_validate(o) for o in officers])


@router.put("/officers/{officer_id}", response_model=schemas.APIResponse[schemas.UserOut])
def update_officer_contact(
    officer_id: str,
    body: schemas.OfficerContactUpdate,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    officer = _get_officer_in_company(officer_id, current_user.company_id, db)

    if body.employee_id and body.employee_id != officer.employee_id:
        conflict = db.query(models.User).filter(
            models.User.employee_id == body.employee_id,
            models.User.company_id == current_user.company_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Employee ID already in use")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(officer, field, value)

    db.commit()
    db.refresh(officer)
    return schemas.APIResponse(data=schemas.UserOut.model_validate(officer), message="Officer updated")


@router.patch("/officers/{officer_id}/deactivate", response_model=schemas.APIResponse[None])
def deactivate_officer(
    officer_id: str,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    officer = _get_officer_in_company(officer_id, current_user.company_id, db)
    if not officer.is_active:
        raise HTTPException(status_code=400, detail="Officer already inactive")

    officer.is_active = False
    company = officer.company
    if company and company.current_users > 0:
        company.current_users -= 1

    _write_audit(db, current_user.company_id, current_user.id,
                 "officer_deactivated", officer.id, officer.full_name)
    db.commit()
    return schemas.APIResponse(data=None, message="Officer deactivated")


@router.patch("/officers/{officer_id}/reactivate", response_model=schemas.APIResponse[None])
def reactivate_officer(
    officer_id: str,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    officer = _get_officer_in_company(officer_id, current_user.company_id, db)
    if officer.is_active:
        raise HTTPException(status_code=400, detail="Officer is already active")

    company = officer.company
    if company and company.current_users >= company.max_users:
        raise HTTPException(status_code=403, detail="User limit reached. Cannot reactivate.")

    officer.is_active = True
    if company:
        company.current_users += 1

    _write_audit(db, current_user.company_id, current_user.id,
                 "officer_reactivated", officer.id, officer.full_name)
    db.commit()
    return schemas.APIResponse(data=None, message="Officer reactivated")


@router.patch("/officers/{officer_id}/reset-password",
              response_model=schemas.APIResponse[schemas.PasswordResetOut])
def reset_officer_password(
    officer_id: str,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    officer = _get_officer_in_company(officer_id, current_user.company_id, db)

    temp_pw = _generate_temp_password()
    officer.password_hash = hash_password(temp_pw)
    officer.must_change_password = True

    _write_audit(db, current_user.company_id, current_user.id,
                 "password_reset", officer.id, officer.full_name)
    db.commit()

    return schemas.APIResponse(
        data=schemas.PasswordResetOut(temp_password=temp_pw),
        message="Password reset successfully",
    )


# ─── Workers (read-only) ──────────────────────────────────────────────────────

@router.get("/workers", response_model=schemas.APIResponse[list[schemas.UserOut]])
def list_workers(
    department: Optional[str] = Query(None),
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    q = db.query(models.User).filter(
        models.User.company_id == current_user.company_id,
        models.User.role == models.UserRole.worker,
        models.User.is_active == True,
    )
    if department:
        q = q.filter(models.User.department == department)
    workers = q.order_by(models.User.full_name).all()
    return schemas.APIResponse(data=[schemas.UserOut.model_validate(w) for w in workers])


# ─── Departments ──────────────────────────────────────────────────────────────

@router.get("/departments", response_model=schemas.APIResponse[list[schemas.DepartmentOut]])
def list_departments(
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    depts = (
        db.query(models.Department)
        .filter(models.Department.company_id == current_user.company_id)
        .order_by(models.Department.name)
        .all()
    )
    return schemas.APIResponse(data=[schemas.DepartmentOut.model_validate(d) for d in depts])


@router.post("/departments",
             response_model=schemas.APIResponse[schemas.DepartmentOut],
             status_code=status.HTTP_201_CREATED)
def create_department(
    body: schemas.DepartmentCreate,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    dept = models.Department(company_id=current_user.company_id, name=body.name.strip())
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return schemas.APIResponse(data=schemas.DepartmentOut.model_validate(dept), message="Department created")


@router.put("/departments/{dept_id}", response_model=schemas.APIResponse[schemas.DepartmentOut])
def update_department(
    dept_id: str,
    body: schemas.DepartmentUpdate,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    dept = db.query(models.Department).filter(
        models.Department.id == dept_id,
        models.Department.company_id == current_user.company_id,
    ).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(dept, field, value)
    db.commit()
    db.refresh(dept)
    return schemas.APIResponse(data=schemas.DepartmentOut.model_validate(dept), message="Department updated")


# ─── Units ────────────────────────────────────────────────────────────────────

@router.get("/departments/{dept_id}/units", response_model=schemas.APIResponse[list[schemas.UnitOut]])
def list_units(
    dept_id: str,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    dept = db.query(models.Department).filter(
        models.Department.id == dept_id,
        models.Department.company_id == current_user.company_id,
    ).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    units = (
        db.query(models.Unit)
        .filter(models.Unit.department_id == dept.id)
        .order_by(models.Unit.name)
        .all()
    )
    return schemas.APIResponse(data=[schemas.UnitOut.model_validate(u) for u in units])


@router.post("/departments/{dept_id}/units",
             response_model=schemas.APIResponse[schemas.UnitOut],
             status_code=status.HTTP_201_CREATED)
def create_unit(
    dept_id: str,
    body: schemas.UnitCreate,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    dept = db.query(models.Department).filter(
        models.Department.id == dept_id,
        models.Department.company_id == current_user.company_id,
    ).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    unit = models.Unit(department_id=dept.id, name=body.name.strip())
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return schemas.APIResponse(data=schemas.UnitOut.model_validate(unit), message="Unit created")


@router.put("/departments/{dept_id}/units/{unit_id}", response_model=schemas.APIResponse[schemas.UnitOut])
def update_unit(
    dept_id: str,
    unit_id: str,
    body: schemas.UnitUpdate,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    dept = db.query(models.Department).filter(
        models.Department.id == dept_id,
        models.Department.company_id == current_user.company_id,
    ).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    unit = db.query(models.Unit).filter(
        models.Unit.id == unit_id,
        models.Unit.department_id == dept.id,
    ).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(unit, field, value)
    db.commit()
    db.refresh(unit)
    return schemas.APIResponse(data=schemas.UnitOut.model_validate(unit), message="Unit updated")


# ─── Notification Recipients ──────────────────────────────────────────────────

@router.get("/notifications", response_model=schemas.APIResponse[list[schemas.NotificationRecipientOut]])
def list_notification_recipients(
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    recipients = (
        db.query(models.NotificationRecipient)
        .filter(
            models.NotificationRecipient.company_id == current_user.company_id,
            models.NotificationRecipient.is_active == True,
        )
        .order_by(models.NotificationRecipient.name)
        .all()
    )
    return schemas.APIResponse(data=[schemas.NotificationRecipientOut.model_validate(r) for r in recipients])


@router.post("/notifications",
             response_model=schemas.APIResponse[schemas.NotificationRecipientOut],
             status_code=status.HTTP_201_CREATED)
def add_notification_recipient(
    body: schemas.NotificationRecipientCompanyCreate,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(models.NotificationRecipient).filter(
        models.NotificationRecipient.email == body.email,
        models.NotificationRecipient.company_id == current_user.company_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Recipient with this email already exists")

    rec = models.NotificationRecipient(
        email=body.email,
        name=body.name,
        company_id=current_user.company_id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return schemas.APIResponse(data=schemas.NotificationRecipientOut.model_validate(rec), message="Recipient added")


@router.delete("/notifications/{recipient_id}", response_model=schemas.APIResponse[None])
def remove_notification_recipient(
    recipient_id: str,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    rec = db.query(models.NotificationRecipient).filter(
        models.NotificationRecipient.id == recipient_id,
        models.NotificationRecipient.company_id == current_user.company_id,
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recipient not found")
    rec.is_active = False
    db.commit()
    return schemas.APIResponse(data=None, message="Recipient removed")


# ─── Emergency History ────────────────────────────────────────────────────────

@router.get("/history", response_model=schemas.APIResponse[list[schemas.EmergencyOut]])
def emergency_history(
    type: Optional[str]      = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str]   = Query(None),
    page: int                = Query(1, ge=1),
    limit: int               = Query(50, ge=1, le=200),
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    q = db.query(models.Emergency).filter(
        models.Emergency.company_id == current_user.company_id,
    )
    if type:
        q = q.filter(models.Emergency.type == type)
    if status_filter:
        try:
            q = q.filter(models.Emergency.status == models.EmergencyStatus(status_filter))
        except ValueError:
            pass
    if date_from:
        try:
            q = q.filter(models.Emergency.started_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(models.Emergency.started_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass

    total = q.count()
    items = (
        q.order_by(models.Emergency.started_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return schemas.APIResponse(
        data=[schemas.EmergencyOut.model_validate(e) for e in items],
        message=f"{total} total records",
    )


# ─── Company Settings ─────────────────────────────────────────────────────────

@router.get("/settings", response_model=schemas.APIResponse[schemas.CompanyOut])
def get_company_settings(
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    company = db.query(models.Company).filter(models.Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return schemas.APIResponse(data=schemas.CompanyOut.model_validate(company))


@router.put("/settings", response_model=schemas.APIResponse[schemas.CompanyOut])
def update_company_settings(
    body: schemas.CompanyUpdate,
    current_user: models.User = Depends(require_company_admin),
    db: Session = Depends(get_db),
):
    company = db.query(models.Company).filter(models.Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # company_admin can only edit these fields — max_users / subscription are super_admin only
    allowed_fields = {"name", "industry", "contact_email", "sos_hotline_phone"}
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in allowed_fields:
            setattr(company, field, value)

    db.commit()
    db.refresh(company)
    return schemas.APIResponse(data=schemas.CompanyOut.model_validate(company), message="Settings updated")
