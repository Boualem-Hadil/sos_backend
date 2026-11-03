import json
import logging
import os
from dotenv import load_dotenv

load_dotenv()

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
) -> List[str]:
    """
    Send an FCM push notification to one or more device tokens.

    Returns a list of invalid/expired token strings so callers can clean them up
    from the database to avoid wasting future send attempts.
    """
    init_firebase()

    if not _firebase_initialized:
        logger.warning("FCM not initialized — skipping push notification (title=%r, tokens=%d)", title, len(tokens))
        return []

    if not tokens:
        logger.warning("FCM send_push_notification called with empty token list — skipping")
        return []

    # FCM data payload values must ALL be strings (Firebase requirement)
    str_data = {k: str(v) for k, v in (data or {}).items()}

    logger.info("FCM sending to %d token(s) — title=%r", len(tokens), title)

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        data=str_data,
        tokens=tokens,
        # Android: high priority ensures delivery even in Doze mode
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                sound="default",
                priority="high",
                channel_id="emergency_alerts",
            ),
        ),
        # iOS: sound + badge update via APNS
        apns=messaging.APNSConfig(
            headers={"apns-priority": "10"},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default", badge=1, content_available=True)
            ),
        ),
    )

    invalid_tokens: List[str] = []
    try:
        response = messaging.send_each_for_multicast(message)
        logger.info(
            "FCM multicast result: %d success, %d failed (of %d tokens)",
            response.success_count,
            response.failure_count,
            len(tokens),
        )

        # Log each individual failure so we can debug which token/device is broken
        for idx, result in enumerate(response.responses):
            if not result.success:
                token = tokens[idx]
                err_code = result.exception.code if result.exception else "unknown"
                err_msg = str(result.exception) if result.exception else "no details"
                logger.warning(
                    "FCM token[%d] FAILED — code=%s msg=%s token=%s…",
                    idx, err_code, err_msg, token[:25]
                )
                # Collect stale/unregistered tokens for the caller to delete from DB
                if err_code in (
                    "registration-token-not-registered",
                    "invalid-registration-token",
                    "messaging/registration-token-not-registered",
                ):
                    invalid_tokens.append(token)

    except Exception as exc:
        logger.error("FCM send_each_for_multicast raised exception: %s", exc, exc_info=True)

    return invalid_tokens
