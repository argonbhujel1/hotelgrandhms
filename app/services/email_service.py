"""
Hotel Grand Garden — branded transactional emails.
If MAIL_SERVER is not configured, emails are logged (not raised) so the app keeps working.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from flask import current_app, render_template_string

logger = logging.getLogger(__name__)

# Shared branded shell
EMAIL_SHELL = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ subject }}</title>
</head>
<body style="margin:0;padding:0;background:#f4f1ea;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f1ea;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,.08);">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#111111 0%,#1c1c1c 60%,#2a2418 100%);padding:28px 28px 22px;text-align:center;">
              <div style="display:inline-block;background:#c9a227;color:#111;font-weight:800;font-size:18px;width:48px;height:48px;line-height:48px;border-radius:12px;margin-bottom:12px;">HG</div>
              <div style="color:#c9a227;font-size:11px;letter-spacing:.18em;text-transform:uppercase;margin-bottom:6px;">{{ hotel_name }}</div>
              <div style="color:#ffffff;font-size:20px;font-weight:700;">{{ title }}</div>
              <div style="color:#aaa;font-size:13px;margin-top:6px;">{{ business_name }}</div>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:28px 28px 8px;color:#222;font-size:15px;line-height:1.6;">
              <p style="margin:0 0 16px;">Dear <strong>{{ recipient_name }}</strong>,</p>
              {{ body_html|safe }}
            </td>
          </tr>
          {% if details %}
          <tr>
            <td style="padding:8px 28px 20px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f8f5ed;border-radius:12px;border:1px solid #e8e2d4;">
                {% for label, value in details %}
                <tr>
                  <td style="padding:12px 16px;border-bottom:1px solid #eee;color:#777;font-size:13px;width:40%;">{{ label }}</td>
                  <td style="padding:12px 16px;border-bottom:1px solid #eee;color:#111;font-size:14px;font-weight:600;text-align:right;">{{ value }}</td>
                </tr>
                {% endfor %}
              </table>
            </td>
          </tr>
          {% endif %}
          {% if highlight %}
          <tr>
            <td style="padding:0 28px 24px;">
              <div style="background:#111;color:#c9a227;text-align:center;padding:16px;border-radius:12px;font-size:18px;font-weight:700;">
                {{ highlight }}
              </div>
            </td>
          </tr>
          {% endif %}
          <tr>
            <td style="padding:8px 28px 28px;color:#555;font-size:14px;line-height:1.55;">
              <p style="margin:0 0 12px;">{{ closing }}</p>
              <p style="margin:0;color:#999;font-size:12px;">If you have questions, contact the hotel administration.</p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background:#1c1c1c;padding:18px 28px;text-align:center;">
              <div style="color:#c9a227;font-weight:700;font-size:13px;">{{ hotel_name }}</div>
              <div style="color:#888;font-size:12px;margin-top:4px;">{{ business_name }} · {{ address }}</div>
              <div style="color:#666;font-size:11px;margin-top:4px;">{{ phone }}{% if email %} · {{ email }}{% endif %}</div>
              <div style="color:#555;font-size:10px;margin-top:10px;">This is an automated message from Hotel Grand Garden HMS.</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _settings_ctx():
    try:
        from app.models.settings import BusinessSettings
        s = BusinessSettings.get_settings()
        return {
            "hotel_name": s.hotel_name or "HOTEL GRAND GARDEN",
            "business_name": s.business_name or "Family Restaurant & Bar",
            "address": s.address or "Urlabari-5, Morang",
            "phone": s.phone or "9816374804",
            "email": s.email or "",
        }
    except Exception:
        return {
            "hotel_name": "HOTEL GRAND GARDEN",
            "business_name": "Family Restaurant & Bar",
            "address": "Urlabari-5, Morang",
            "phone": "9816374804",
            "email": "",
        }


def build_html(
    *,
    subject: str,
    title: str,
    recipient_name: str,
    body_html: str,
    details: Optional[list] = None,
    highlight: Optional[str] = None,
    closing: str = "Thank you for being part of Hotel Grand Garden.",
) -> str:
    ctx = _settings_ctx()
    ctx.update(
        subject=subject,
        title=title,
        recipient_name=recipient_name or "Team Member",
        body_html=body_html,
        details=details or [],
        highlight=highlight,
        closing=closing,
    )
    return render_template_string(EMAIL_SHELL, **ctx)


def send_email(to_address: str, subject: str, html_body: str, text_fallback: str = "") -> bool:
    if not to_address or "@" not in to_address:
        logger.info("Email skipped (no valid address): %s", subject)
        return False

    server = current_app.config.get("MAIL_SERVER")
    if not server:
        logger.info(
            "[EMAIL-DRY-RUN] To=%s Subject=%s\n%s",
            to_address,
            subject,
            text_fallback or subject,
        )
        return False

    port = int(current_app.config.get("MAIL_PORT") or 587)
    use_tls = current_app.config.get("MAIL_USE_TLS", True)
    username = current_app.config.get("MAIL_USERNAME")
    password = current_app.config.get("MAIL_PASSWORD")
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or username or "noreply@hotelgrandgarden.com"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Hotel Grand Garden <{sender}>"
    msg["To"] = to_address
    if text_fallback:
        msg.attach(MIMEText(text_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(server, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.sendmail(sender, [to_address], msg.as_string())
        logger.info("Email sent to %s: %s", to_address, subject)
        return True
    except Exception as e:
        logger.exception("Email failed to %s: %s", to_address, e)
        return False


def notify(to_user, event: str, **kwargs) -> bool:
    """
    High-level notify by event key.
    to_user: User model or object with .email, .full_name
    """
    if not to_user:
        return False
    email = getattr(to_user, "email", None)
    name = getattr(to_user, "full_name", None) or getattr(to_user, "username", "Staff")

    builders = {
        "salary_increment": _salary_increment,
        "salary_payment": _salary_payment,
        "payroll_finalized": _payroll_finalized,
        "leave_submitted": _leave_submitted,
        "leave_approved": _leave_decision,
        "leave_rejected": _leave_decision,
        "attendance_approved": _attendance_decision,
        "attendance_rejected": _attendance_decision,
        "break_submitted": _break_submitted,
        "break_approved": _break_decision,
        "break_rejected": _break_decision,
        "overtime_submitted": _overtime_submitted,
        "overtime_approved": _overtime_decision,
        "overtime_rejected": _overtime_decision,
        "consumption_submitted": _consumption_submitted,
        "consumption_approved": _consumption_decision,
        "consumption_rejected": _consumption_decision,
        "password_reset": _password_reset,
        "welcome_staff": _welcome_staff,
    }
    fn = builders.get(event)
    if not fn:
        logger.warning("Unknown email event: %s", event)
        return False
    subject, html, text = fn(name=name, **kwargs)
    return send_email(email, subject, html, text)


# ---------- event builders ----------

def _salary_increment(name, **kw):
    prev_b = kw.get("previous_basic", "—")
    new_b = kw.get("new_basic", "—")
    prev_a = kw.get("previous_allowance", "—")
    new_a = kw.get("new_allowance", "—")
    amount = kw.get("increment_amount", "—")
    percent = kw.get("increment_percent", "—")
    effective = kw.get("effective_from", "—")
    reason = kw.get("reason") or "Performance & growth recognition"
    subject = "Salary Increment — Hotel Grand Garden"
    body = f"""
      <p>We are pleased to inform you that your salary has been <strong style="color:#c9a227;">incremented</strong>.</p>
      <p style="color:#555;">{reason}</p>
    """
    details = [
        ("Previous Basic", f"Rs. {prev_b}"),
        ("New Basic", f"Rs. {new_b}"),
        ("Previous Allowance", f"Rs. {prev_a}"),
        ("New Allowance", f"Rs. {new_a}"),
        ("Increment Amount", f"Rs. {amount}"),
        ("Increment %", f"{percent}%"),
        ("Effective From", str(effective)),
    ]
    highlight = f"New Basic: Rs. {new_b}"
    html = build_html(
        subject=subject,
        title="Salary Increment",
        recipient_name=name,
        body_html=body,
        details=details,
        highlight=highlight,
        closing="Congratulations! We value your contribution to Hotel Grand Garden.",
    )
    text = f"Salary increment for {name}. New basic Rs. {new_b} effective {effective}."
    return subject, html, text


def _salary_payment(name, **kw):
    amount = kw.get("amount", "—")
    month = kw.get("month", "—")
    method = kw.get("method", "—")
    remaining = kw.get("remaining", "—")
    subject = f"Salary Payment Received — {month}"
    body = "<p>A salary payment has been recorded for your account.</p>"
    details = [
        ("Salary Month", str(month)),
        ("Amount Paid", f"Rs. {amount}"),
        ("Payment Method", str(method)),
        ("Remaining", f"Rs. {remaining}"),
    ]
    html = build_html(
        subject=subject,
        title="Salary Payment",
        recipient_name=name,
        body_html=body,
        details=details,
        highlight=f"Paid: Rs. {amount}",
        closing="Thank you for your hard work.",
    )
    return subject, html, f"Salary payment Rs. {amount} for {month}."


def _payroll_finalized(name, **kw):
    """Payslip-style payroll notification email."""
    month = kw.get("month", "—")
    net = kw.get("net_payable", "—")
    basic = kw.get("basic", kw.get("basic_salary", "—"))
    allowance = kw.get("allowance", "—")
    ot_pay = kw.get("ot_pay", "—")
    gross = kw.get("gross_earnings", "—")
    total_deduction = kw.get("total_deduction", "—")
    unpaid = kw.get("unpaid_leave_deduction", "—")
    late = kw.get("late_deduction", "—")
    food = kw.get("food_deduction", "—")
    fine = kw.get("fine_deduction", "—")
    advance = kw.get("advance_deduction", "—")
    other = kw.get("other_deduction", "—")
    total_paid = kw.get("total_paid", "—")
    remaining = kw.get("remaining", "—")
    working_days = kw.get("working_days", "—")
    hotel = kw.get("hotel_name", "Hotel Grand Garden")

    subject = f"Payslip — {month} | {hotel}"
    body = f"""
      <p>Dear <strong>{name}</strong>,</p>
      <p>Your <strong>monthly payroll</strong> for <strong>{month}</strong> has been finalized.
      Below is a summary of your payslip.</p>
    """
    details = [
        ("Employee", str(name)),
        ("Salary Month", str(month)),
        ("Working Days", str(working_days)),
        ("Basic Salary", f"Rs. {basic}"),
        ("Allowance", f"Rs. {allowance}"),
        ("OT Pay", f"Rs. {ot_pay}"),
        ("Gross Earnings", f"Rs. {gross}"),
        ("Unpaid Leave Deduction", f"Rs. {unpaid}"),
        ("Late Deduction", f"Rs. {late}"),
        ("Food Deduction", f"Rs. {food}"),
        ("Fine Deduction", f"Rs. {fine}"),
        ("Advance Deduction", f"Rs. {advance}"),
        ("Other Deduction", f"Rs. {other}"),
        ("Total Deductions", f"Rs. {total_deduction}"),
        ("Net Payable", f"Rs. {net}"),
        ("Already Paid", f"Rs. {total_paid}"),
        ("Remaining", f"Rs. {remaining}"),
    ]
    html = build_html(
        subject=subject,
        title=f"Payslip — {month}",
        recipient_name=name,
        body_html=body,
        details=details,
        highlight=f"Net Payable: Rs. {net}",
        closing="This is a system-generated payslip notification from Hotel Grand Garden HR. Please contact accounts if you have questions.",
    )
    text = (
        f"Payslip {month} for {name}. Basic Rs. {basic}, Gross Rs. {gross}, "
        f"Deductions Rs. {total_deduction}, Net Payable Rs. {net}."
    )
    return subject, html, text


def _leave_submitted(name, **kw):
    subject = "Leave Request Submitted"
    body = "<p>Your leave request has been submitted and is awaiting approval.</p>"
    details = [
        ("Leave Date", str(kw.get("leave_date", "—"))),
        ("Type / Mode", str(kw.get("mode", "—"))),
        ("Reason", str(kw.get("reason", "—"))),
    ]
    html = build_html(subject=subject, title="Leave Submitted", recipient_name=name, body_html=body, details=details)
    return subject, html, "Leave request submitted."


def _leave_decision(name, **kw):
    status = kw.get("status", "updated")
    approved = status == "approved"
    subject = f"Leave Request {status.title()}"
    body = f"<p>Your leave request has been <strong>{status}</strong>.</p>"
    details = [
        ("Leave Date", str(kw.get("leave_date", "—"))),
        ("Status", status.title()),
        ("Note", str(kw.get("note", "—"))),
    ]
    html = build_html(
        subject=subject,
        title=f"Leave {status.title()}",
        recipient_name=name,
        body_html=body,
        details=details,
        highlight="Approved" if approved else "Rejected",
    )
    return subject, html, f"Leave {status}."


def _attendance_decision(name, **kw):
    status = kw.get("status", "updated")
    subject = f"Attendance {status.title()}"
    body = f"<p>Your attendance record has been <strong>{status}</strong>.</p>"
    details = [("Date", str(kw.get("date", "—"))), ("Status", status.title())]
    html = build_html(subject=subject, title=f"Attendance {status.title()}", recipient_name=name, body_html=body, details=details)
    return subject, html, f"Attendance {status}."


def _break_submitted(name, **kw):
    subject = "Break Request Submitted"
    body = "<p>Your break request has been submitted for approval.</p>"
    details = [("Date", str(kw.get("date", "—"))), ("Duration", str(kw.get("duration", "—")))]
    html = build_html(subject=subject, title="Break Submitted", recipient_name=name, body_html=body, details=details)
    return subject, html, "Break submitted."


def _break_decision(name, **kw):
    status = kw.get("status", "updated")
    subject = f"Break Request {status.title()}"
    body = f"<p>Your break request has been <strong>{status}</strong>.</p>"
    details = [("Date", str(kw.get("date", "—"))), ("Status", status.title())]
    html = build_html(subject=subject, title=f"Break {status.title()}", recipient_name=name, body_html=body, details=details)
    return subject, html, f"Break {status}."


def _overtime_submitted(name, **kw):
    subject = "Overtime Request Submitted"
    body = "<p>Your overtime request has been submitted for approval.</p>"
    details = [("Date", str(kw.get("date", "—"))), ("Hours", str(kw.get("hours", "—"))), ("Reason", str(kw.get("reason", "—")))]
    html = build_html(subject=subject, title="Overtime Submitted", recipient_name=name, body_html=body, details=details)
    return subject, html, "OT submitted."


def _overtime_decision(name, **kw):
    status = kw.get("status", "updated")
    subject = f"Overtime {status.title()}"
    body = f"<p>Your overtime request has been <strong>{status}</strong>.</p>"
    details = [("Date", str(kw.get("date", "—"))), ("Hours", str(kw.get("hours", "—"))), ("Status", status.title())]
    html = build_html(subject=subject, title=f"Overtime {status.title()}", recipient_name=name, body_html=body, details=details)
    return subject, html, f"OT {status}."


def _consumption_submitted(name, **kw):
    subject = "Hotel Consumption Submitted"
    body = "<p>Your hotel consumption request has been submitted for approval.</p>"
    details = [("Item", str(kw.get("item", "—"))), ("Amount", f"Rs. {kw.get('amount', '—')}")]
    html = build_html(subject=subject, title="Consumption Submitted", recipient_name=name, body_html=body, details=details)
    return subject, html, "Consumption submitted."


def _consumption_decision(name, **kw):
    status = kw.get("status", "updated")
    subject = f"Consumption {status.title()}"
    body = f"<p>Your consumption request has been <strong>{status}</strong>.</p>"
    details = [("Item", str(kw.get("item", "—"))), ("Amount", f"Rs. {kw.get('amount', '—')}"), ("Status", status.title())]
    html = build_html(subject=subject, title=f"Consumption {status.title()}", recipient_name=name, body_html=body, details=details)
    return subject, html, f"Consumption {status}."


def _password_reset(name, **kw):
    subject = "Password Reset — Hotel Grand Garden HMS"
    body = "<p>Your HMS password has been reset by an administrator. Please login with the new password and change it after signing in.</p>"
    html = build_html(subject=subject, title="Password Reset", recipient_name=name, body_html=body, closing="For security, do not share your password.")
    return subject, html, "Your password was reset."


def _welcome_staff(name, **kw):
    subject = "Welcome to Hotel Grand Garden"
    body = f"""
      <p>Welcome to the team! Your HMS account has been created.</p>
      <p>Username: <strong>{kw.get('username', '—')}</strong></p>
    """
    html = build_html(subject=subject, title="Welcome Aboard", recipient_name=name, body_html=body, highlight="We're glad to have you.")
    return subject, html, f"Welcome {name}."
