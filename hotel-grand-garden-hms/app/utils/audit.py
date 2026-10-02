from flask import request
from flask_login import current_user
from app import db
from app.models.activity import ActivityLog, AuditLog, SecurityEvent


def log_activity(action, module=None, record_type=None, record_id=None, details=None):
    try:
        entry = ActivityLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            username=current_user.username if current_user.is_authenticated else None,
            role=current_user.role_code if current_user.is_authenticated else None,
            action=action,
            module=module,
            record_type=record_type,
            record_id=record_id,
            details=details,
            ip_address=request.remote_addr if request else None,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()


def log_audit(action, module=None, record_type=None, record_id=None, previous=None, new=None):
    try:
        entry = AuditLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            username=current_user.username if current_user.is_authenticated else None,
            role=current_user.role_code if current_user.is_authenticated else None,
            action=action,
            module=module,
            record_type=record_type,
            record_id=record_id,
            previous_value=str(previous) if previous is not None else None,
            new_value=str(new) if new is not None else None,
            ip_address=request.remote_addr if request else None,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()


def log_security(event_type, details=None, user_id=None):
    try:
        entry = SecurityEvent(
            user_id=user_id,
            event_type=event_type,
            details=details,
            ip_address=request.remote_addr if request else None,
            user_agent=request.headers.get("User-Agent", "")[:512] if request else None,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
