"""
email_service.py — Send transactional emails for EchoAlert via Resend HTTP API.

Configure via Railway Variables (or .env):
  RESEND_API_KEY   — from https://resend.com (free: 3000 emails/month)
  FROM_EMAIL       — verified sender address, e.g. noreply@yourdomain.com
  ADMIN_EMAIL      — comma-separated list: alice@x.com,bob@x.com
                     (also accepts JSON array format: ["alice@x.com","bob@x.com"])

Note: raw smtplib is blocked on Railway (Errno 101). Resend uses HTTPS (port 443)
which is always open.
"""
import json
import logging
import os
from datetime import date
from typing import List, Optional

import httpx

logger = logging.getLogger("sos_backend.email")

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL     = os.getenv("FROM_EMAIL", "EchoAlert <noreply@echoalert.dz>")

# Parse ADMIN_EMAIL — handles both:
#   plain CSV:  alice@x.com,bob@x.com
#   JSON array: ["alice@x.com","bob@x.com"]
_raw_admin_emails = os.getenv("ADMIN_EMAIL", "").strip()
try:
    if _raw_admin_emails.startswith("["):
        _parsed = json.loads(_raw_admin_emails)
        ADMIN_EMAILS: List[str] = [e.strip() for e in _parsed if isinstance(e, str) and e.strip()]
    else:
        ADMIN_EMAILS = [e.strip() for e in _raw_admin_emails.split(",") if e.strip()]
except Exception:
    ADMIN_EMAILS = [e.strip() for e in _raw_admin_emails.split(",") if e.strip()]

# Keep legacy SMTP_HOST / SMTP_USER exported so scheduler.py import doesn't break
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_USER = os.getenv("SMTP_USER", "")


def _resend_configured() -> bool:
    return bool(RESEND_API_KEY)


def send_email(to_addresses: List[str], subject: str, html_body: str) -> bool:
    """
    Send an HTML email via Resend HTTP API (works on Railway — uses HTTPS port 443).
    Falls back to stub logging if RESEND_API_KEY is not set.
    """
    # Strip any malformed addresses and split by comma in case 
    # multiple emails were crammed into a single string
    raw_recipients = []
    for a in to_addresses:
        if not a:
            continue
        for part in a.split(","):
            raw_recipients.append(part)

    recipients = [
        r.strip().strip('"').strip("'").strip("[").strip("]")
        for r in raw_recipients
    ]
    recipients = list(set([r for r in recipients if r and "@" in r]))

    if not recipients:
        logger.warning("send_email called with no valid recipients — skipping")
        return False

    if not _resend_configured():
        logger.warning(
            "[EMAIL STUB — set RESEND_API_KEY in Railway] To: %s | Subject: %s",
            recipients, subject,
        )
        return False

    logger.info("Sending email via Resend → recipients=%s subject=%s", recipients, subject)
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": FROM_EMAIL,
                "to": recipients,
                "subject": subject,
                "html": html_body,
            },
            timeout=20,
        )
        if resp.status_code in (200, 201):
            logger.info("✅ Email sent to %s: %s", recipients, subject)
            return True
        else:
            logger.error("❌ Resend API error %d: %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.error("❌ Failed to send email to %s: %s — %s", recipients, type(exc).__name__, exc)
        return False


# -- License Expiry Templates ----

def _license_html(company_name: str, company_code: str, expiry_date: date, days_left: int, expired: bool) -> str:
    if expired:
        urgency_color = "#DC2626"
        status_text   = "⛔ EXPIRÉE"
        message       = f"La licence de <strong>{company_name}</strong> ({company_code}) a expiré le <strong>{expiry_date.strftime('%d/%m/%Y')}</strong>."
        action        = "Veuillez renouveler la licence immédiatement pour rétablir l'accès."
    elif days_left <= 7:
        urgency_color = "#DC2626"
        status_text   = f"🚨 EXPIRE DANS {days_left} JOUR(S)"
        message       = f"La licence de <strong>{company_name}</strong> ({company_code}) expire dans <strong>{days_left} jour(s)</strong>, le <strong>{expiry_date.strftime('%d/%m/%Y')}</strong>."
        action        = "Action urgente requise — contactez votre administrateur EchoAlert pour renouveler."
    else:
        urgency_color = "#F59E0B"
        status_text   = f"⚠️ EXPIRE DANS {days_left} JOURS"
        message       = f"La licence de <strong>{company_name}</strong> ({company_code}) expire dans <strong>{days_left} jours</strong>, le <strong>{expiry_date.strftime('%d/%m/%Y')}</strong>."
        action        = "Pensez à renouveler votre licence avant l'échéance pour maintenir la continuité du service."

    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background:#0F1623;font-family:Inter,Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0F1623;padding:40px 20px;">
        <tr><td align="center">
          <table width="600" cellpadding="0" cellspacing="0" style="background:#161E2E;border-radius:16px;border:1px solid #1E293B;overflow:hidden;">
            <!-- Header -->
            <tr>
              <td style="background:linear-gradient(135deg,#DC2626,#7F1D1D);padding:32px 40px;text-align:center;">
                <div style="font-size:36px;margin-bottom:8px;">🛡️</div>
                <h1 style="color:#fff;font-size:22px;margin:0;font-weight:800;letter-spacing:1px;">EchoAlert Platform</h1>
                <p style="color:rgba(255,255,255,0.7);margin:8px 0 0;font-size:13px;">Notification de Licence</p>
              </td>
            </tr>
            <!-- Status Badge -->
            <tr>
              <td style="padding:24px 40px 0;text-align:center;">
                <span style="display:inline-block;background:{urgency_color};color:#fff;font-weight:700;font-size:13px;padding:8px 20px;border-radius:100px;letter-spacing:1px;">
                  {status_text}
                </span>
              </td>
            </tr>
            <!-- Body -->
            <tr>
              <td style="padding:28px 40px;color:#CBD5E1;font-size:15px;line-height:1.7;">
                <p>{message}</p>
                <div style="background:#1A2535;border-left:4px solid {urgency_color};padding:16px 20px;border-radius:8px;margin:20px 0;">
                  <p style="margin:0;color:#F1F5F9;">{action}</p>
                </div>
                <table cellpadding="8" cellspacing="0" width="100%" style="margin-top:20px;border-collapse:collapse;">
                  <tr style="background:#1A2535;">
                    <td style="padding:10px 16px;border-radius:6px 6px 0 0;color:#94A3B8;font-size:12px;text-transform:uppercase;letter-spacing:1px;">Entreprise</td>
                    <td style="padding:10px 16px;color:#F1F5F9;font-weight:600;">{company_name}</td>
                  </tr>
                  <tr>
                    <td style="padding:10px 16px;color:#94A3B8;font-size:12px;text-transform:uppercase;letter-spacing:1px;">Code</td>
                    <td style="padding:10px 16px;color:#F1F5F9;font-family:monospace;">{company_code}</td>
                  </tr>
                  <tr style="background:#1A2535;">
                    <td style="padding:10px 16px;border-radius:0 0 6px 6px;color:#94A3B8;font-size:12px;text-transform:uppercase;letter-spacing:1px;">Date d'expiration</td>
                    <td style="padding:10px 16px;color:{urgency_color};font-weight:700;">{expiry_date.strftime('%d %B %Y')}</td>
                  </tr>
                </table>
              </td>
            </tr>
            <!-- Footer -->
            <tr>
              <td style="padding:24px 40px;border-top:1px solid #1E293B;text-align:center;">
                <p style="color:#475569;font-size:12px;margin:0;">
                  Ce message est envoyé automatiquement par la plateforme EchoAlert.<br>
                  © {date.today().year} EchoAlert — Tous droits réservés.
                </p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """


def send_license_expiry_warning(
    company_name: str,
    company_code: str,
    expiry_date: date,
    days_left: int,
    expired: bool,
    extra_recipients: Optional[List[str]] = None,
) -> None:
    """
    Send license expiry email to:
      - All platform super-admins (ADMIN_EMAIL — single address or comma-separated list)
      - All active notification recipients stored in the DB (passed as extra_recipients)
      - The company's own contact_email (also passed via extra_recipients by the scheduler)
    """
    subject = (
        f"[EchoAlert] ⛔ Licence expirée — {company_name}"
        if expired
        else f"[EchoAlert] ⚠️ Licence expire dans {days_left} jour(s) — {company_name}"
    )
    html = _license_html(company_name, company_code, expiry_date, days_left, expired)

    recipients = list(set(ADMIN_EMAILS) | set(extra_recipients or []))
    send_email([r for r in recipients if r], subject, html)
