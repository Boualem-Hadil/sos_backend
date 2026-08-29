import math
from datetime import datetime, timezone, timedelta

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

    # ── Duplicate proximity check ─────────────────────────────────────────────
    # Look for other active emergencies in the same company started within the
    # last 2 minutes and within ~100 m of the new one.
    possible_duplicate_ids: list[str] = []
    if body.latitude is not None and body.longitude is not None:
        two_min_ago = datetime.now(timezone.utc) - timedelta(minutes=2)
        other_active = (
            db.query(models.Emergency)
            .filter(
                models.Emergency.company_id == current_user.company_id,
                models.Emergency.status     == models.EmergencyStatus.active,
                models.Emergency.id         != emergency.id,
                models.Emergency.started_at >= two_min_ago,
            )
            .all()
        )
        for other in other_active:
            if other.latitude is not None and other.longitude is not None:
                dist_km = _haversine_km(
                    body.latitude, body.longitude,
                    other.latitude, other.longitude,
                )
                if dist_km <= 0.05:   # 50 m
                    possible_duplicate_ids.append(str(other.id))

    # Broadcast SSE (possible_duplicate_of is additive — empty list if none)
    sse_payload = _emergency_payload(emergency, db)
    sse_payload["possible_duplicate_of"] = possible_duplicate_ids
    await sse_manager.broadcast(
        company_id = str(current_user.company_id),
        event_type = "EMERGENCY_STARTED",
        data       = sse_payload,
    )

    return schemas.APIResponse(
        data    = schemas.EmergencyOut.model_validate(emergency),
        message = "Emergency reported",
    )


# ─── Resolve Emergency ───────────────────────────────────────────────────────────────

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

    # ── Persist status + existing fields (UNCHANGED) ─────────────────────────
    emergency.status      = body.status
    emergency.resolved_at = datetime.now(timezone.utc)

    # ── NEW: persist resolution detail fields ──────────────────────────────
    if body.responder_type is not None:
        emergency.responder_type = body.responder_type       # NEW
    if body.eta_minutes is not None:
        emergency.eta_minutes = body.eta_minutes             # NEW
    if body.resolution_notes:
        emergency.notes = body.resolution_notes              # maps to existing 'notes' column

    db.commit()
    db.refresh(emergency)

    # ── Broadcast SSE with FULL enriched payload (CHANGED: was thin {id, status}) ──
    await sse_manager.broadcast(
        company_id = str(emergency.company_id),
        event_type = "EMERGENCY_RESOLVED",
        data       = _emergency_payload(emergency, db),    # CHANGED
    )

    return schemas.APIResponse(
        data    = schemas.EmergencyOut.model_validate(emergency),
        message = "Emergency resolved",
    )


# ─── List Emergencies (paginated + filtered) ──────────────────────────────────

@router.get("", response_model=schemas.APIResponse[schemas.EmergencyPage])
def list_emergencies(
    page:   int          = Query(1, ge=1),
    limit:  int          = Query(20, ge=1, le=500),
    type:   str | None   = Query(None),
    status: str | None   = Query(None),
    user_id: str | None  = Query(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(models.Emergency).filter(
        models.Emergency.company_id == current_user.company_id
    )

    if user_id:
        if user_id == "me":
            query = query.filter(models.Emergency.user_id == current_user.id)
        else:
            query = query.filter(models.Emergency.user_id == user_id)

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


# ─── Haversine helper ─────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Returns great-circle distance in kilometres between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ─── GPS Heartbeat (worker → backend) ────────────────────────────────────────

@router.post("/{emergency_id}/heartbeat",
             response_model=schemas.APIResponse[schemas.EmergencyOut])
async def gps_heartbeat(
    emergency_id: str,
    body: schemas.GpsHeartbeatIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Worker app sends GPS coordinates every ~30 s while the emergency is active.
    Also updates last_seen_active as an interaction signal.
    Only sent while the emergency is active — stops on resolve/cancel.
    PRIVACY NOTE: location is shared only during an active emergency; no
    background tracking. Full consent UI is a separate task.
    """
    emergency = (
        db.query(models.Emergency)
        .filter(models.Emergency.id == emergency_id)
        .first()
    )
    if not emergency:
        raise HTTPException(status_code=404, detail="Emergency not found")

    # Only the reporting worker (or super_admin) may send heartbeats for this emergency
    if (str(emergency.user_id) != str(current_user.id)
            and current_user.role != models.UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    if emergency.status != models.EmergencyStatus.active:
        raise HTTPException(status_code=409, detail="Emergency is not active")

    now = datetime.now(timezone.utc)
    emergency.heartbeat_lat    = body.latitude
    emergency.heartbeat_lng    = body.longitude
    emergency.last_seen_active = now   # interaction signal
    db.commit()
    db.refresh(emergency)

    # Broadcast a lightweight SSE so the dashboard can update the marker in real time
    await sse_manager.broadcast(
        company_id = str(emergency.company_id),
        event_type = "HEARTBEAT_UPDATED",
        data       = {
            "emergency_id":  str(emergency.id),
            "latitude":      body.latitude,
            "longitude":     body.longitude,
            "last_seen_active": now.isoformat(),
            "not_responding": schemas.EmergencyOut.model_validate(emergency).not_responding,
        },
    )

    return schemas.APIResponse(
        data    = schemas.EmergencyOut.model_validate(emergency),
        message = "Heartbeat recorded",
    )


# ─── "Are You OK?" Ping (officer → worker via backend/SSE) ───────────────────

@router.post("/{emergency_id}/ping",
             response_model=schemas.APIResponse[schemas.EmergencyOut])
async def send_ping(
    emergency_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Officer triggers an 'are you OK?' ping.  The worker app receives a PING_SENT
    SSE event and must respond within PING_RESPONSE_WINDOW_SECONDS (60 s).
    After the window, if ping_acked_at is still null, the emergency is flagged
    not_responding (derived field — no separate DB column needed).
    """
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

    if emergency.status != models.EmergencyStatus.active:
        raise HTTPException(status_code=409, detail="Emergency is not active")

    # Reset previous ack so the new window starts fresh
    emergency.ping_sent_at  = datetime.now(timezone.utc)
    emergency.ping_acked_at = None
    db.commit()
    db.refresh(emergency)

    # Broadcast to the company channel — the worker app listens on the same SSE stream
    await sse_manager.broadcast(
        company_id = str(emergency.company_id),
        event_type = "PING_SENT",
        data       = {
            "emergency_id": str(emergency.id),
            "ping_sent_at": emergency.ping_sent_at.isoformat(),
            "window_seconds": schemas.PING_RESPONSE_WINDOW_SECONDS,
        },
    )

    return schemas.APIResponse(
        data    = schemas.EmergencyOut.model_validate(emergency),
        message = "Ping sent",
    )


# ─── Ping Acknowledgment (worker → backend) ───────────────────────────────────

@router.post("/{emergency_id}/ping-ack",
             response_model=schemas.APIResponse[schemas.EmergencyOut])
async def ack_ping(
    emergency_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Worker taps 'I am OK' within the response window.
    Sets ping_acked_at, clears not_responding flag (derived), and notifies dashboard.
    """
    emergency = (
        db.query(models.Emergency)
        .filter(models.Emergency.id == emergency_id)
        .first()
    )
    if not emergency:
        raise HTTPException(status_code=404, detail="Emergency not found")

    if (str(emergency.user_id) != str(current_user.id)
            and current_user.role != models.UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    if emergency.ping_sent_at is None:
        raise HTTPException(status_code=409, detail="No pending ping to acknowledge")

    now = datetime.now(timezone.utc)
    sent = emergency.ping_sent_at
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    if (now - sent).total_seconds() > schemas.PING_RESPONSE_WINDOW_SECONDS:
        raise HTTPException(status_code=410, detail="Ping window has expired")

    emergency.ping_acked_at    = now
    emergency.last_seen_active = now  # also counts as interaction
    db.commit()
    db.refresh(emergency)

    await sse_manager.broadcast(
        company_id = str(emergency.company_id),
        event_type = "PING_ACKED",
        data       = {
            "emergency_id":  str(emergency.id),
            "ping_acked_at": now.isoformat(),
            "not_responding": False,
        },
    )

    return schemas.APIResponse(
        data    = schemas.EmergencyOut.model_validate(emergency),
        message = "Ping acknowledged",
    )


# ─── Nearby Workers (officer → dashboard) ────────────────────────────────────

@router.get("/{emergency_id}/nearby-workers",
            response_model=schemas.APIResponse[list[schemas.NearbyWorkerOut]])
def get_nearby_workers(
    emergency_id: str,
    radius_km: float = Query(0.5, ge=0.1, le=50.0,
                             description="Search radius in kilometres"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns same-company workers matched by operational unit and/or GPS proximity.
    Unit matches bypass distance checks. GPS matches require a heartbeat within the last 10 minutes.
    """
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

    # Use the latest heartbeat position; fall back to initial report position
    origin_lat = emergency.heartbeat_lat or emergency.latitude
    origin_lng = emergency.heartbeat_lng or emergency.longitude

    # GPS calculation will just be skipped if origin is None.
    victim = None
    if emergency.user_id:
        victim = db.query(models.User).filter(models.User.id == emergency.user_id).first()
    victim_unit = victim.unit if victim else None

    # Get all other workers in the company
    other_workers = (
        db.query(models.User)
        .filter(
            models.User.company_id == emergency.company_id,
            models.User.id != emergency.user_id
        )
        .all()
    )

    now = datetime.now(timezone.utc)
    freshness_threshold = now - timedelta(minutes=10)
    results: list[schemas.NearbyWorkerOut] = []

    for worker in other_workers:
        is_unit_match = bool(victim_unit and worker.unit and worker.unit == victim_unit)
        is_gps_match = False
        distance = None

        if worker.location_updated_at and worker.location_updated_at >= freshness_threshold:
            if worker.latitude is not None and worker.longitude is not None and origin_lat is not None and origin_lng is not None:
                dist = _haversine_km(
                    origin_lat, origin_lng,
                    worker.latitude, worker.longitude,
                )
                if dist <= radius_km:
                    is_gps_match = True
                    distance = dist
        
        if is_unit_match and is_gps_match:
            match_type = "both"
        elif is_gps_match:
            match_type = "gps"
        elif is_unit_match:
            match_type = "unit"
        else:
            continue

        results.append(schemas.NearbyWorkerOut(
            id           = worker.id,
            full_name    = worker.full_name,
            phone        = worker.phone,
            match_type   = match_type,
            distance_km  = round(distance, 3) if distance is not None else None,
            latitude     = worker.latitude if is_gps_match else None,
            longitude    = worker.longitude if is_gps_match else None,
        ))

    # Sort: GPS-matched workers first (ordered by distance), then unit-only matches.
    results.sort(key=lambda w: (
        0 if w.match_type in ("gps", "both") else 1,
        w.distance_km if w.distance_km is not None else float('inf')
    ))

    # Fallback: if no workers found via GPS or Unit, return up to 5 random/available workers
    if not results and other_workers:
        for worker in other_workers[:5]:
            results.append(schemas.NearbyWorkerOut(
                id           = worker.id,
                full_name    = worker.full_name,
                phone        = worker.phone,
                match_type   = "company",
                distance_km  = None,
                latitude     = None,
                longitude    = None,
            ))

    return schemas.APIResponse(
        data    = results,
        message = f"{len(results)} worker(s) found",
    )
