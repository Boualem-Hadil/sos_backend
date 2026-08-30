from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from fastapi.responses import FileResponse
import os
import uuid

from app import models, schemas
from app.auth import get_current_user
from app.database import get_db
from app.sse_manager import sse_manager
from app.services.storage_service import save_audio_file, get_audio_file_path, UPLOAD_DIR

router = APIRouter(prefix="/emergencies", tags=["Emergency Chat"])

def get_authorized_emergency(emergency_id: str, current_user: models.User, db: Session) -> models.Emergency:
    emergency = db.query(models.Emergency).filter(models.Emergency.id == emergency_id).first()
    if not emergency:
        raise HTTPException(status_code=404, detail="Emergency not found")
        
    # Super admins can see anything
    if current_user.role == models.UserRole.super_admin:
        return emergency
        
    # Must be in the same company
    if str(emergency.company_id) != str(current_user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
        
    # If user is a worker, they must own the emergency
    if current_user.role == models.UserRole.worker and str(emergency.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
        
    return emergency

@router.get("/{emergency_id}/messages", response_model=schemas.APIResponse[list[schemas.MessageOut]])
def get_messages(
    emergency_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emergency = get_authorized_emergency(emergency_id, current_user, db)
    
    messages = db.query(models.Message).filter(
        models.Message.emergency_id == emergency.id
    ).order_by(models.Message.created_at.asc()).all()
    
    return schemas.APIResponse(
        data=[schemas.MessageOut.model_validate(m) for m in messages]
    )

@router.post("/{emergency_id}/messages/text", response_model=schemas.APIResponse[schemas.MessageOut])
async def post_text_message(
    emergency_id: str,
    body: schemas.MessageCreateText,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emergency = get_authorized_emergency(emergency_id, current_user, db)
    
    if emergency.status != models.EmergencyStatus.active:
        raise HTTPException(status_code=400, detail="Cannot send messages to an inactive emergency")
        
    # Determine sender_role: explicit in body (e.g. ai_assistant/system) or derived from current_user role
    effective_role = body.sender_role or ("safety_officer" if current_user.role in [models.UserRole.safety_officer, models.UserRole.company_admin, models.UserRole.super_admin] else "worker")
    if body.sender_role in ["ai_assistant", "system"]:
        effective_role = body.sender_role

    message = models.Message(
        emergency_id=emergency.id,
        sender_id=current_user.id,
        sender_role=effective_role,
        message_type=models.MessageType.text,
        content=body.content
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    
    # Broadcast new message via SSE
    message_data = schemas.MessageOut.model_validate(message).model_dump(mode="json")
    await sse_manager.broadcast(
        company_id=str(emergency.company_id),
        event_type="NEW_MESSAGE",
        data={"emergency_id": str(emergency.id), "message": message_data}
    )
    
    return schemas.APIResponse(data=schemas.MessageOut.model_validate(message))

@router.post("/{emergency_id}/messages/voice", response_model=schemas.APIResponse[schemas.MessageOut])
async def post_voice_message(
    emergency_id: str,
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emergency = get_authorized_emergency(emergency_id, current_user, db)
    
    if emergency.status != models.EmergencyStatus.active:
        raise HTTPException(status_code=400, detail="Cannot send messages to an inactive emergency")
        
    try:
        file_id, duration = save_audio_file(file, max_duration_seconds=60)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    effective_role = "safety_officer" if current_user.role in [models.UserRole.safety_officer, models.UserRole.company_admin, models.UserRole.super_admin] else "worker"
    message = models.Message(
        emergency_id=emergency.id,
        sender_id=current_user.id,
        sender_role=effective_role,
        message_type=models.MessageType.voice,
        file_url=f"/emergencies/{emergency_id}/messages/voice/{file_id}",
        duration_seconds=duration
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    
    # Broadcast new message via SSE
    message_data = schemas.MessageOut.model_validate(message).model_dump(mode="json")
    await sse_manager.broadcast(
        company_id=str(emergency.company_id),
        event_type="NEW_MESSAGE",
        data={"emergency_id": str(emergency.id), "message": message_data}
    )
    
    return schemas.APIResponse(data=schemas.MessageOut.model_validate(message))

@router.get("/{emergency_id}/messages/voice/{file_id}")
def get_voice_message(
    emergency_id: str,
    file_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Ensure user has access to this emergency
    emergency = get_authorized_emergency(emergency_id, current_user, db)
    
    file_path = get_audio_file_path(file_id)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    return FileResponse(file_path, media_type="audio/mp4")
