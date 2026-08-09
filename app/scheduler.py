"""
scheduler.py — APScheduler cron jobs for SOS Algérie.

Runs a daily check for expiring/expired licenses and sends email notifications.
"""
import logging
import os
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app import models
from app.email_service import send_license_expiry_warning

logger = logging.getLogger("sos_backend.scheduler")

WARNING_DAYS = int(os.getenv("LICENSE_WARNING_DAYS", "30"))


def check_license_expiry():
    """
    Query all companies and send notifications for:
    - Companies that are already expired
    - Companies expiring within WARNING_DAYS days
    """
    logger.info("⏰ Running license expiry check …")
    db = SessionLocal()
    try:
        today = date.today()
        cutoff = today + timedelta(days=WARNING_DAYS)

        # Get all active notification recipients
        recipients = (
            db.query(models.NotificationRecipient)
            .filter(models.NotificationRecipient.is_active == True)
            .all()
        )
        recipient_emails = [r.email for r in recipients]

        # Find companies with a subscription_end set
        companies = (
            db.query(models.Company)
            .filter(
                models.Company.subscription_end != None,
                models.Company.company_code != "SUPER-ADMIN",  # skip platform company
            )
            .all()
        )

        notified = 0
        for company in companies:
            end = company.subscription_end
            if end is None:
                continue

            extra = list(recipient_emails)
            if company.contact_email:
                extra.append(company.contact_email)

            if end < today:
                # Already expired
                days_overdue = (today - end).days
                logger.warning("Company %s license EXPIRED %d day(s) ago", company.company_code, days_overdue)
                send_license_expiry_warning(
                    company_name=company.name,
                    company_code=company.company_code,
                    expiry_date=end,
                    days_left=0,
                    expired=True,
                    extra_recipients=extra,
                )
                notified += 1
            elif end <= cutoff:
                # Expiring soon
                days_left = (end - today).days
                logger.info("Company %s license expiring in %d day(s)", company.company_code, days_left)
                send_license_expiry_warning(
                    company_name=company.name,
                    company_code=company.company_code,
                    expiry_date=end,
                    days_left=days_left,
                    expired=False,
                    extra_recipients=extra,
                )
                notified += 1

        logger.info("⏰ License check complete — %d notification(s) sent", notified)

    except Exception as exc:
        logger.exception("License expiry check failed: %s", exc)
    finally:
        db.close()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Africa/Algiers")
    # Run daily at 08:00 local time
    scheduler.add_job(
        check_license_expiry,
        trigger=CronTrigger(hour=8, minute=0),
        id="license_expiry_check",
        name="Daily License Expiry Check",
        replace_existing=True,
    )
    return scheduler
