"""
email_service.py — Send transactional emails for SOS Algérie.

Configure via .env:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ADMIN_EMAIL
"""
import logging
import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

logger = logging.getLogger("sos_backend.email")

SMTP_HOST    = os.getenv("SMTP_HOST", "")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER    = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ADMIN_EMAIL  = os.getenv("ADMIN_EMAIL", "")


def _smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def send_email(to_addresses: List[str], subject: str, html_body: str) -> bool:
    """
    Send an HTML email to one or more recipients.
    Returns True on success, False on failure (logs the error).
    Falls back to logging if SMTP is not configured.
    """
    if not _smtp_configured():
        logger.warning(
            "[EMAIL STUB] To: %s | Subject: %s\n--- BODY (first 300 chars) ---\n%s",
            ", ".join(to_addresses), subject, html_body[:300],
        )
        return False

    recipients = [a for a in to_addresses if a]  # filter empty strings
    if not recipients:
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"SOS Algérie Platform <{SMTP_USER}>"
        msg["To"]      = ", ".join(recipients)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipients, msg.as_string())

        logger.info("Email sent to %s: %s", recipients, subject)
        return True

    except Exception as exc:
        logger.error("Failed to send email to %s: %s", recipients, exc)
        return False


# ── License Expiry Templates ──────────────────────────────────────────────────

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
        action        = "Action urgente requise — contactez votre administrateur SOS Algérie pour renouveler."
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
                <h1 style="color:#fff;font-size:22px;margin:0;font-weight:800;letter-spacing:1px;">SOS Algérie Platform</h1>
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
                  Ce message est envoyé automatiquement par la plateforme SOS Algérie.<br>
                  © {date.today().year} SOS Algérie — Tous droits réservés.
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
      - Platform admin (ADMIN_EMAIL)
      - All active notification recipients (passed as extra_recipients)
    """
    subject = (
        f"[SOS Algérie] ⛔ Licence expirée — {company_name}"
        if expired
        else f"[SOS Algérie] ⚠️ Licence expire dans {days_left} jour(s) — {company_name}"
    )
    html  = _license_html(company_name, company_code, expiry_date, days_left, expired)
    
    recipients = list({ADMIN_EMAIL} | set(extra_recipients or []))
    send_email([r for r in recipients if r], subject, html)
