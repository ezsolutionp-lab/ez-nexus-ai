"""
EZ-NEXUS AI — SMS & Email Confirmation Service
Sends appointment confirmations via Twilio SMS and SMTP email.
Falls back gracefully if credentials are not yet configured.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)


# ── SMS via Twilio ────────────────────────────────────────────────────────────

def send_sms(to_phone: str, message: str) -> bool:
    if not all([settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_phone_number]):
        logger.info("Twilio not configured — SMS skipped")
        return False
    try:
        from twilio.rest import Client
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            body=message,
            from_=settings.twilio_phone_number,
            to=to_phone,
        )
        logger.info(f"SMS sent to {to_phone}")
        return True
    except Exception as e:
        logger.error(f"SMS failed: {e}")
        return False


def send_appointment_sms(client_phone: str, client_name: str, business_name: str,
                          service: str, scheduled_at: datetime) -> bool:
    if not client_phone:
        return False
    dt = scheduled_at.strftime("%A, %B %d at %I:%M %p")
    msg = (
        f"Hi {client_name}! Your appointment is confirmed.\n"
        f"📅 {dt}\n"
        f"🏢 {business_name}\n"
        f"💼 Service: {service}\n\n"
        f"Reply CANCEL to cancel. — EZ-NEXUS AI"
    )
    return send_sms(client_phone, msg)


def send_reminder_sms(client_phone: str, client_name: str, business_name: str,
                       service: str, scheduled_at: datetime) -> bool:
    if not client_phone:
        return False
    dt = scheduled_at.strftime("%A, %B %d at %I:%M %p")
    msg = (
        f"Reminder: {client_name}, your appointment is tomorrow!\n"
        f"📅 {dt} at {business_name}\n"
        f"💼 {service}\n"
        f"Reply CANCEL to cancel. — EZ-NEXUS AI"
    )
    return send_sms(client_phone, msg)


# ── Email via SMTP ────────────────────────────────────────────────────────────

def _send_email(to_email: str, subject: str, html_body: str) -> bool:
    if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password]):
        logger.info("SMTP not configured — email skipped")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"EZ-NEXUS AI <{settings.smtp_user}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, to_email, msg.as_string())
        logger.info(f"Email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False


def send_appointment_email(client_email: str, client_name: str, business_name: str,
                            service: str, scheduled_at: datetime, notes: str = "") -> bool:
    if not client_email:
        return False
    dt = scheduled_at.strftime("%A, %B %d, %Y at %I:%M %p")
    notes_row = f"<tr><td><b>Notes</b></td><td>{notes}</td></tr>" if notes else ""
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden">
      <div style="background:#0f172a;padding:24px 28px">
        <h2 style="color:#fff;margin:0;font-size:1.3rem">🤖 EZ-NEXUS AI</h2>
        <p style="color:#94a3b8;margin:4px 0 0;font-size:.85rem">Appointment Confirmed</p>
      </div>
      <div style="padding:28px">
        <p style="font-size:1rem;color:#1e293b">Hi <b>{client_name}</b>,<br>Your appointment has been confirmed!</p>
        <table style="width:100%;border-collapse:collapse;font-size:.9rem;margin:16px 0">
          <tr style="background:#f8fafc"><td style="padding:8px 12px;font-weight:700;color:#64748b;width:120px">Business</td><td style="padding:8px 12px">{business_name}</td></tr>
          <tr><td style="padding:8px 12px;font-weight:700;color:#64748b">Service</td><td style="padding:8px 12px">{service}</td></tr>
          <tr style="background:#f8fafc"><td style="padding:8px 12px;font-weight:700;color:#64748b">Date &amp; Time</td><td style="padding:8px 12px"><b>{dt}</b></td></tr>
          {notes_row}
        </table>
        <p style="font-size:.85rem;color:#64748b">Questions? Simply reply to this email or call the business directly.</p>
      </div>
      <div style="background:#f1f5f9;padding:14px 28px;font-size:.75rem;color:#94a3b8;text-align:center">
        Powered by EZ-NEXUS AI — Your AI Workforce for Business Growth™
      </div>
    </div>
    """
    return _send_email(client_email, f"✅ Appointment Confirmed — {business_name}", html)


def send_staff_notification_email(staff_email: str, business_name: str, client_name: str,
                                   client_phone: str, service: str, scheduled_at: datetime,
                                   approval_token: str, base_url: str) -> bool:
    if not staff_email:
        return False
    dt = scheduled_at.strftime("%A, %B %d, %Y at %I:%M %p")
    approve_url = f"{base_url}/appointments/approve/{approval_token}"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden">
      <div style="background:#0f766e;padding:24px 28px">
        <h2 style="color:#fff;margin:0;font-size:1.2rem">📅 New Appointment Needs Approval</h2>
        <p style="color:#99f6e4;margin:4px 0 0;font-size:.85rem">{business_name}</p>
      </div>
      <div style="padding:28px">
        <table style="width:100%;border-collapse:collapse;font-size:.9rem;margin-bottom:20px">
          <tr style="background:#f8fafc"><td style="padding:8px 12px;font-weight:700;color:#64748b;width:120px">Client</td><td style="padding:8px 12px"><b>{client_name}</b></td></tr>
          <tr><td style="padding:8px 12px;font-weight:700;color:#64748b">Phone</td><td style="padding:8px 12px">{client_phone or '—'}</td></tr>
          <tr style="background:#f8fafc"><td style="padding:8px 12px;font-weight:700;color:#64748b">Service</td><td style="padding:8px 12px">{service}</td></tr>
          <tr><td style="padding:8px 12px;font-weight:700;color:#64748b">Date &amp; Time</td><td style="padding:8px 12px"><b>{dt}</b></td></tr>
        </table>
        <div style="text-align:center">
          <a href="{approve_url}" style="background:#0f766e;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:700;display:inline-block">
            ✅ Approve &amp; Send Confirmation
          </a>
        </div>
        <p style="font-size:.8rem;color:#94a3b8;text-align:center;margin-top:14px">
          Or log in to your EZ-NEXUS dashboard to approve, reschedule, or cancel.
        </p>
      </div>
    </div>
    """
    return _send_email(staff_email, f"📅 New Booking: {client_name} — {service}", html)
