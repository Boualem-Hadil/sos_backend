import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user
from app.database import get_db
from app.sse_manager import sse_manager

router = APIRouter(prefix="/emergencies", tags=["Emergencies"])


# ─── Helper: build SSE payload ────────────────────────────────────────────────

def _emergency_payload(emergency: models.Emergency, db: Session) -> dict:
    user    = db.query(models.User).filter(models.User.id == emergency.user_id).first()
    company = db.query(models.Company).filter(models.Company.id == emergency.company_id).first()
    medical = None
    if user:
        medical = (
            db.query(models.MedicalProfile)
            .filter(models.MedicalProfile.user_id == user.id)
            .first()
        )

    return {
        "emergency":       schemas.EmergencyOut.model_validate(emergency).model_dump(mode="json"),
        "user":            schemas.UserOut.model_validate(user).model_dump(mode="json") if user else None,
        "medical_profile": schemas.MedicalProfileOut.model_validate(medical).model_dump(mode="json") if medical else None,
        "company":         schemas.CompanyOut.model_validate(company).model_dump(mode="json") if company else None,
    }


# ─── Report Emergency ─────────────────────────────────────────────────────────

@router.post("", response_model=schemas.APIResponse[schemas.EmergencyOut],
             status_code=status.HTTP_201_CREATED)
async def report_emergency(
    body: schemas.EmergencyCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emergency = models.Emergency(
        user_id              = current_user.id,
        company_id           = current_user.company_id,
        type                 = body.type,
        severity             = body.severity,
        latitude             = body.latitude,
        longitude            = body.longitude,
        location_description = body.location_description,
        status               = models.EmergencyStatus.active,
        started_at           = datetime.now(timezone.utc),
    )
    db.add(emergency)
    db.commit()
    db.refresh(emergency)

    # Broadcast SSE
    await sse_manager.broadcast(
        company_id = str(current_user.company_id),
        event_type = "EMERGENCY_STARTED",
        data       = _emergency_payload(emergency, db),
    )

    return schemas.APIResponse(
        data    = schemas.EmergencyOut.model_validate(emergency),
        message = "Emergency reported",
    )


# ─── Resolve Emergency ────────────────────────────────────────────────────────

@router.put("/{emergency_id}/resolve",
            response_model=schemas.APIResponse[schemas.EmergencyOut])
async def resolve_emergency(
    emergency_id: str,
    body: schemas.EmergencyResolve,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emergency = (
        db.query(models.Emergency)
        .filter(models.Emergency.id == emergency_id)
        .first()
    )
    if not emergency:
        raise HTTPException(status_code=404, detail="Emergency not found")

    # Only same-company workers/officers or super_admin can resolve
    if (str(emergency.company_id) != str(current_user.company_id)
            and current_user.role != models.UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    if emergency.status != models.EmergencyStatus.active:
        raise HTTPException(status_code=409, detail="Emergency is already resolved")

    emergency.status      = body.status
    emergency.resolved_at = datetime.now(timezone.utc)
    if body.notes:
        emergency.notes = body.notes

    db.commit()
    db.refresh(emergency)

    # Broadcast SSE
    await sse_manager.broadcast(
        company_id = str(emergency.company_id),
        event_type = "EMERGENCY_RESOLVED",
        data       = {
            "emergency_id": str(emergency.id),
            "status":       emergency.status.value,
        },
    )

    return schemas.APIResponse(
        data    = schemas.EmergencyOut.model_validate(emergency),
        message = "Emergency resolved",
    )


# ─── List Emergencies (paginated + filtered) ──────────────────────────────────

@router.get("", response_model=schemas.APIResponse[schemas.EmergencyPage])
def list_emergencies(
    page:   int          = Query(1, ge=1),
    limit:  int          = Query(20, ge=1, le=100),
    type:   str | None   = Query(None),
    status: str | None   = Query(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(models.Emergency).filter(
        models.Emergency.company_id == current_user.company_id
    )

    if type:
        query = query.filter(models.Emergency.type == type)
    if status:
        try:
            st = models.EmergencyStatus(status)
            query = query.filter(models.Emergency.status == st)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    total = query.count()
    items = (
        query
        .order_by(models.Emergency.started_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return schemas.APIResponse(
        data=schemas.EmergencyPage(
            items  = [schemas.EmergencyOut.model_validate(e) for e in items],
            total  = total,
            page   = page,
            limit  = limit,
            pages  = math.ceil(total / limit) if total else 1,
        )
    )


# ─── Get Single Emergency Detail ──────────────────────────────────────────────

@router.get("/{emergency_id}", response_model=schemas.APIResponse[schemas.EmergencyDetail])
def get_emergency(
    emergency_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emergency = (
        db.query(models.Emergency)
        .filter(models.Emergency.id == emergency_id)
        .first()
    )
    if not emergency:
        raise HTTPException(status_code=404, detail="Emergency not found")

    if (str(emergency.company_id) != str(current_user.company_id)
            and current_user.role != models.UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    user    = db.query(models.User).filter(models.User.id == emergency.user_id).first()
    medical = None
    if user:
        medical = (
            db.query(models.MedicalProfile)
            .filter(models.MedicalProfile.user_id == user.id)
            .first()
        )

    detail = schemas.EmergencyDetail.model_validate(emergency)
    if user:
        detail.user = schemas.UserOut.model_validate(user)
    if medical:
        detail.medical_profile = schemas.MedicalProfileOut.model_validate(medical)

    return schemas.APIResponse(data=detail)
