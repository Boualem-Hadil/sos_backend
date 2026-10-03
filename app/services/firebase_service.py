import json
import logging
import os

import firebase_admin
from firebase_admin import credentials, messaging
from typing import List, Optional

logger = logging.getLogger("sos_backend.firebase")

# Track if firebase is initialized
_firebase_initialized = False


def _build_credential() -> credentials.Base | None:
    """
    Build a Firebase credential using the first available source, in order:

    1. FIREBASE_CREDENTIALS_JSON  — raw JSON string of the service-account key.
       Set this on Railway (no filesystem needed).

    2. FIREBASE_CREDENTIALS_PATH  — path to the service-account JSON file.
       Useful for local dev; ignored on Railway where no persistent FS exists.

    3. GOOGLE_APPLICATION_CREDENTIALS / Application Default Credentials (ADC).
       Handled implicitly by firebase_admin.initialize_app() with no args.

    Returns a credentials.Certificate if (1) or (2) succeeds, otherwise None
    (so the caller can fall through to ADC).
    """
    # -- 1. JSON string from environment (Railway-friendly) ----
    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        try:
            service_account_info = json.loads(cred_json)
            logger.info("Firebase: loading credentials from FIREBASE_CREDENTIALS_JSON")
            return credentials.Certificate(service_account_info)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "Firebase: FIREBASE_CREDENTIALS_JSON is set but could not be parsed as JSON: %s", exc
            )
            # Don't fall through to a broken credential — surface the mistake.
            raise

    # -- 2. File path (local dev fallback) ----
    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    if cred_path:
        if os.path.exists(cred_path):
            logger.info("Firebase: loading credentials from file %s", cred_path)
            return credentials.Certificate(cred_path)
        else:
            logger.warning(
                "Firebase: FIREBASE_CREDENTIALS_PATH is set to '%s' but the file does not exist. "
                "Falling back to Application Default Credentials.",
                cred_path,
            )

    # -- 3. ADC / GOOGLE_APPLICATION_CREDENTIALS ----
    # Return None to signal that initialize_app() should be called with no cred arg.
    return None


def init_firebase() -> None:
    """Initialise the Firebase Admin SDK (idempotent — safe to call multiple times)."""
    global _firebase_initialized
    if _firebase_initialized:
        return

    try:
        if not firebase_admin._apps:
            cred = _build_credential()
            if cred is not None:
                firebase_admin.initialize_app(cred)
            else:
                # Falls back to GOOGLE_APPLICATION_CREDENTIALS / ADC
                logger.info(
                    "Firebase: no explicit credentials found; "
                    "trying Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS / ADC)."
                )
                firebase_admin.initialize_app()

        _firebase_initialized = True
        logger.info("Firebase Admin SDK initialised successfully.")

    except Exception as exc:
        # Non-fatal: push notifications will silently no-op rather than crash the app.
        logger.warning("Firebase: initialisation failed — push notifications disabled. Error: %s", exc)


def send_push_notification(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> None:
    """Send an FCM push notification to one or more device tokens."""
    init_firebase()
    if not _firebase_initialized or not tokens:
        return

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
        tokens=tokens,
    )

    try:
        response = messaging.send_each_for_multicast(message)
        logger.info(
            "FCM multicast: %d success, %d failed (of %d tokens)",
            response.success_count,
            response.failure_count,
            len(tokens),
        )
    except Exception as exc:
        logger.error("FCM send error: %s", exc)

