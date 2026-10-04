"""
scheduler.py — APScheduler cron jobs for EchoAlert.

Runs a daily check for expiring/expired licenses and sends email notifications.
"""
import logging
import os
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app import models
from app.email_service import send_license_expiry_warning, SMTP_HOST, SMTP_USER

logger = logging.getLogger("sos_backend.scheduler")

WARNING_DAYS = int(os.getenv("LICENSE_WARNING_DAYS", "30"))


def check_license_expiry():
    """
    Query all companies and:
    - Auto-deactivate companies whose subscription_end has passed
    - Send notifications for expired or soon-to-expire companies
    """
    smtp_ok = bool(SMTP_HOST and SMTP_USER)
    logger.info(
        " Running license expiry check … (SMTP configured: %s, WARNING_DAYS: %d)",
        smtp_ok, WARNING_DAYS,
    )
    db = SessionLocal()
    try:
        today = date.today()
        cutoff = today + timedelta(days=WARNING_DAYS)

        # Get all active SUPER ADMIN notification recipients (platform level, company_id is NULL)
        super_admin_recipients = (
            db.query(models.NotificationRecipient)
            .filter(
                models.NotificationRecipient.is_active == True,
                models.NotificationRecipient.company_id == None
            )
            .all()
        )
        super_admin_emails = [r.email for r in super_admin_recipients]

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
            
            # Get this company's active notification recipients
            company_recipients = (
                db.query(models.NotificationRecipient)
                .filter(
                    models.NotificationRecipient.is_active == True,
                    models.NotificationRecipient.company_id == company.id
                )
                .all()
            )
            company_emails = [r.email for r in company_recipients]

            # Combine super admin emails, company recipient emails, and the company's main contact email
            extra = list(super_admin_emails) + list(company_emails)
            if company.contact_email:
                extra.append(company.contact_email)
            
            # Deduplicate emails
            extra = list(set(extra))

            if end < today:
                # License has expired — auto-deactivate if still active
                days_overdue = (today - end).days
                if company.is_active:
                    company.is_active = False
                    db.commit()
                    logger.warning(
                        "Company %s license EXPIRED %d day(s) ago — auto-deactivated",
                        company.company_code, days_overdue,
                    )
                else:
                    logger.warning(
                        "Company %s license EXPIRED %d day(s) ago (already deactivated)",
                        company.company_code, days_overdue,
                    )
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

        logger.info(" License check complete — %d notification(s) sent", notified)

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
