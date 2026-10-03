from datetime import datetime
from app import db


class BusinessSettings(db.Model):
    # maintenance_mode, logo_url, favicon_url added below as columns where possible

    __tablename__ = "business_settings"
    id = db.Column(db.Integer, primary_key=True)
    hotel_name = db.Column(db.String(150), default="HOTEL GRAND GARDEN")
    business_name = db.Column(db.String(150), default="Family Restaurant & Bar")
    address = db.Column(db.String(255), default="Urlabari-5, Morang")
    phone = db.Column(db.String(30), default="9816374804")
    email = db.Column(db.String(120))
    pan = db.Column(db.String(50), default="")
    vat_number = db.Column(db.String(50), default="")
    currency = db.Column(db.String(10), default="Rs.")
    check_in_time = db.Column(db.String(10), default="12:00")
    check_out_time = db.Column(db.String(10), default="11:00")
    logo_path = db.Column(db.String(255))
    favicon_path = db.Column(db.String(255))
    signature_path = db.Column(db.String(255))
    prepared_by_text = db.Column(db.Text, default="HOTEL GRAND GARDEN\nFamily Restaurant & Bar")
    # Geofence for staff attendance (Nepal)
    attendance_lat = db.Column(db.Float)  # hotel latitude
    attendance_lng = db.Column(db.Float)  # hotel longitude
    attendance_radius_m = db.Column(db.Integer, default=200)  # meters
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_settings(cls):
        s = cls.query.first()
        if not s:
            s = cls()
            db.session.add(s)
            db.session.commit()
        return s


class TaxSettings(db.Model):
    __tablename__ = "tax_settings"
    id = db.Column(db.Integer, primary_key=True)
    vat_rate = db.Column(db.Numeric(5, 2), default=13.0)
    vat_inclusive = db.Column(db.Boolean, default=True)
    vat_enabled = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_settings(cls):
        s = cls.query.first()
        if not s:
            s = cls()
            db.session.add(s)
            db.session.commit()
        return s


class POSSettings(db.Model):
    __tablename__ = "pos_settings"
    id = db.Column(db.Integer, primary_key=True)
    service_charge_percent = db.Column(db.Numeric(5, 2), default=0)
    default_payment_method = db.Column(db.String(30), default="cash")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_settings(cls):
        s = cls.query.first()
        if not s:
            s = cls()
            db.session.add(s)
            db.session.commit()
        return s


class WorkingHoursSettings(db.Model):
    __tablename__ = "working_hours_settings"
    id = db.Column(db.Integer, primary_key=True)
    work_start = db.Column(db.String(10), default="10:00")
    work_end = db.Column(db.String(10), default="18:00")
    required_daily_hours = db.Column(db.Numeric(4, 2), default=8.0)
    break_duration_minutes = db.Column(db.Integer, default=60)
    grace_period_minutes = db.Column(db.Integer, default=10)
    working_days_per_month = db.Column(db.Integer, default=26)
    late_fine_enabled = db.Column(db.Boolean, default=False)
    early_fine_enabled = db.Column(db.Boolean, default=False)
    late_fine_type = db.Column(db.String(30), default="per_minute")  # per_minute, per_hour, salary_based
    late_fine_amount = db.Column(db.Numeric(10, 2), default=2)
    overtime_enabled = db.Column(db.Boolean, default=True)
    overtime_salary_enabled = db.Column(db.Boolean, default=True)
    overtime_rate_type = db.Column(db.String(30), default="salary_based")
    overtime_fixed_rate = db.Column(db.Numeric(10, 2), default=0)
    overtime_multiplier = db.Column(db.Numeric(4, 2), default=1.5)
    overtime_unit = db.Column(db.String(20), default="exact")  # exact, 15min, 30min, 1hour
    break_excluded_from_hours = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_settings(cls):
        s = cls.query.first()
        if not s:
            s = cls()
            db.session.add(s)
            db.session.commit()
        return s



class SystemSetting(db.Model):
    """Key-value for maintenance mode, branding, etc."""
    __tablename__ = "system_settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=None):
        row = SystemSetting.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = SystemSetting.query.filter_by(key=key).first()
        if not row:
            row = SystemSetting(key=key)
            db.session.add(row)
        row.value = value if value is None else str(value)
        db.session.commit()
        return row
