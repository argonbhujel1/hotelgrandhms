from datetime import datetime
from app import db


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    username = db.Column(db.String(80))
    role = db.Column(db.String(50))
    action = db.Column(db.String(100), nullable=False)
    module = db.Column(db.String(50))
    record_type = db.Column(db.String(50))
    record_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    username = db.Column(db.String(80))
    role = db.Column(db.String(50))
    action = db.Column(db.String(100), nullable=False)
    module = db.Column(db.String(50))
    record_type = db.Column(db.String(50))
    record_id = db.Column(db.Integer)
    previous_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class SecurityEvent(db.Model):
    __tablename__ = "security_events"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    event_type = db.Column(db.String(50), nullable=False)  # failed_login, new_ip, unauthorized, etc.
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
