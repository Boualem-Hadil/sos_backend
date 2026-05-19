from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)
from app.database import get_db
from app.sse_manager import sse_manager

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ─── Register ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=schemas.APIResponse[schemas.RegisterResponse],
             status_code=status.HTTP_201_CREATED)
def register(body: schemas.UserRegister, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # 1. Find company by code
    company = (
        db.query(models.Company)
        .filter(models.Company.company_code == body.company_code)
        .first()
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company code invalid")

    # 2. Check company is active
    if not company.is_active:
        raise HTTPException(status_code=403, detail="Company account is deactivated")

    # 3. Check user limit
    if company.current_users >= company.max_users:
        raise HTTPException(
            status_code=403,
            detail="User limit reached. Contact your administrator",
        )

    # 4. Check duplicate employee_id within the company
    existing = (
        db.query(models.User)
        .filter(
            models.User.employee_id == body.employee_id,
            models.User.company_id  == company.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Employee already registered")

    # 5. Create user
    user = models.User(
        company_id    = company.id,
        full_name     = body.full_name,
        employee_id   = body.employee_id,
        phone         = body.phone,
        password_hash = hash_password(body.password),
        role          = models.UserRole.worker,
    )
    db.add(user)
    db.flush()  # get user.id before commit

    # 6. Auto-create empty medical profile
    medical = models.MedicalProfile(
        user_id          = user.id,
        chronic_diseases = [],
        allergies        = [],
    )
    db.add(medical)

    # 7. Increment company.current_users
    company.current_users += 1
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, company.id, user.role.value)
    
    user_out = schemas.UserOut.model_validate(user)

    # Broadcast event to the real company channel
    background_tasks.add_task(
        sse_manager.broadcast,
        str(company.id),
        "worker_registered",
        user_out.model_dump(mode="json")
    )
    # Also broadcast to 'COMP-123' for local testing (dashboard fallback)
    background_tasks.add_task(
        sse_manager.broadcast,
        "COMP-123",
        "worker_registered",
        user_out.model_dump(mode="json")
    )

    return schemas.APIResponse(
        data=schemas.RegisterResponse(
            access_token=token,
            user=user_out,
        ),
        message="Registration successful",
    )


# ─── Login ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=schemas.APIResponse[schemas.LoginResponse])
def login(body: schemas.UserLogin, db: Session = Depends(get_db)):
    # Find company → then user
    company = (
        db.query(models.Company)
        .filter(models.Company.company_code == body.company_code)
        .first()
    )
    if not company:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = (
        db.query(models.User)
        .filter(
            models.User.employee_id == body.employee_id,
            models.User.company_id  == company.id,
        )
        .first()
    )

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")

    # Update last_seen
    user.last_seen = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, company.id, user.role.value)

    user_out = schemas.UserWithCompany.model_validate(user)
    user_out.company = schemas.CompanyOut.model_validate(company)

    return schemas.APIResponse(
        data=schemas.LoginResponse(access_token=token, user=user_out),
        message="Login successful",
    )


# ─── Me ───────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=schemas.APIResponse[schemas.UserWithCompany])
def me(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.refresh(current_user)
    company = db.query(models.Company).filter(models.Company.id == current_user.company_id).first()

    user_out = schemas.UserWithCompany.model_validate(current_user)
    if company:
        user_out.company = schemas.CompanyOut.model_validate(company)

    return schemas.APIResponse(data=user_out)
