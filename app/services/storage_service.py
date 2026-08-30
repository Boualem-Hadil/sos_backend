import os
import uuid
import shutil
from fastapi import UploadFile
from mutagen.mp4 import MP4
from mutagen.mp3 import MP3
import mutagen

# Define the root uploads directory
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "voice_messages")
os.makedirs(UPLOAD_DIR, exist_ok=True)

class InvalidAudioError(Exception):
    pass

class AudioTooLongError(Exception):
    pass

def save_audio_file(file: UploadFile, max_duration_seconds: int = 60) -> tuple[str, int]:
    """
    Saves an uploaded audio file locally for V1.
    Validates that the file duration is within `max_duration_seconds`.
    Returns a tuple of (file_id, duration_seconds).
    """
    file_id = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, file_id)
    
    # Save the file first to read its metadata
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise e
        
    # Validate duration using mutagen
    try:
        audio = mutagen.File(file_path)
        if audio is None or not hasattr(audio, 'info'):
            raise InvalidAudioError("Could not read audio metadata")
            
        duration = int(audio.info.length)
        if duration > max_duration_seconds:
            os.remove(file_path)
            raise AudioTooLongError(f"Audio exceeds max duration of {max_duration_seconds}s (was {duration}s)")
            
        return file_id, duration
        
    except (InvalidAudioError, AudioTooLongError):
        raise
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise InvalidAudioError(f"Invalid audio file format: {str(e)}")

def get_audio_file_path(file_id: str) -> str:
    """
    Returns the absolute path to the saved audio file.
    """
    # Prevent directory traversal attacks
    clean_file_id = os.path.basename(file_id)
    return os.path.join(UPLOAD_DIR, clean_file_id)
