import os
import firebase_admin
from firebase_admin import credentials, messaging
from typing import List, Optional

# Track if firebase is initialized
_firebase_initialized = False

def init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return
    
    # In V1, this could be from an env var pointing to the service account JSON
    # e.g., GOOGLE_APPLICATION_CREDENTIALS
    # If not provided, firebase_admin will try to find it in the environment
    try:
        if not firebase_admin._apps:
            # If the user has set up a service account path
            cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            else:
                # Try default app (works if GOOGLE_APPLICATION_CREDENTIALS is set)
                firebase_admin.initialize_app()
            _firebase_initialized = True
            print("Firebase initialized successfully.")
    except Exception as e:
        print(f"Warning: Failed to initialize Firebase: {e}")

def send_push_notification(tokens: List[str], title: str, body: str, data: Optional[dict] = None) -> None:
    """
    Sends a push notification to multiple device tokens.
    """
    init_firebase()
    if not _firebase_initialized or not tokens:
        return

    # Create the MulticastMessage
    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=data or {},
        tokens=tokens,
    )
    
    try:
        response = messaging.send_each_for_multicast(message)
        print(f"Successfully sent FCM message: {response.success_count} success, {response.failure_count} failed")
    except Exception as e:
        print(f"Error sending FCM message: {e}")
