from datetime import datetime
from datetime import date
from app.utils.timeutil import npt_now_naive
from app import db


class StaffSalaryProfile(db.Model):
    __tablename__ = "staff_salary_profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    basic_salary = db.Column(db.Numeric(12, 2), default=0)
    allowance = db.Column(db.Numeric(12, 2), default=0)
    effective_from = db.Column(db.Date)
    status = db.Column(db.String(20), default="active")
    # Optional per-staff working hours (override global)
    work_start = db.Column(db.String(10))  # e.g. 10:00
    work_end = db.Column(db.String(10))
    required_daily_hours = db.Column(db.Numeric(4, 2))
    # Bank / wallet for salary payout
    bank_name = db.Column(db.String(100))
    bank_account_number = db.Column(db.String(50))
    wallet_provider = db.Column(db.String(50))  # eSewa, Khalti, Fonepay, Other
    wallet_account_number = db.Column(db.String(50))
    updated_at = db.Column(db.DateTime, default=npt_now_naive, onupdate=npt_now_naive)

    user = db.relationship("User", back_populates="salary_profile")

    @property
    def gross(self):
        return (self.basic_salary or 0) + (self.allowance or 0)


class SalaryIncrement(db.Model):
    __tablename__ = "salary_increments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    previous_basic = db.Column(db.Numeric(12, 2))
    new_basic = db.Column(db.Numeric(12, 2))
    previous_allowance = db.Column(db.Numeric(12, 2))
    new_allowance = db.Column(db.Numeric(12, 2))
    increment_amount = db.Column(db.Numeric(12, 2))
    increment_percent = db.Column(db.Numeric(6, 2))
    effective_from = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)


class SalaryRecord(db.Model):
    """Monthly payroll – RUNNING or FINAL."""
    __tablename__ = "salary_records"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="running")  # running, final
    basic = db.Column(db.Numeric(12, 2), default=0)
    allowance = db.Column(db.Numeric(12, 2), default=0)
    ot_hours = db.Column(db.Numeric(8, 2), default=0)
    ot_pay = db.Column(db.Numeric(12, 2), default=0)
    gross_earnings = db.Column(db.Numeric(12, 2), default=0)
    unpaid_leave_deduction = db.Column(db.Numeric(12, 2), default=0)
    late_deduction = db.Column(db.Numeric(12, 2), default=0)
    early_deduction = db.Column(db.Numeric(12, 2), default=0)
    food_deduction = db.Column(db.Numeric(12, 2), default=0)
    product_deduction = db.Column(db.Numeric(12, 2), default=0)
    fine_deduction = db.Column(db.Numeric(12, 2), default=0)
    advance_deduction = db.Column(db.Numeric(12, 2), default=0)
    other_deduction = db.Column(db.Numeric(12, 2), default=0)
    total_deduction = db.Column(db.Numeric(12, 2), default=0)
    net_payable = db.Column(db.Numeric(12, 2), default=0)
    total_paid = db.Column(db.Numeric(12, 2), default=0)
    remaining = db.Column(db.Numeric(12, 2), default=0)
    # Attendance snapshot
    working_days = db.Column(db.Integer, default=0)
    present_days = db.Column(db.Numeric(5, 1), default=0)
    paid_leave_days = db.Column(db.Numeric(5, 1), default=0)
    unpaid_leave_days = db.Column(db.Numeric(5, 1), default=0)
    half_days = db.Column(db.Numeric(5, 1), default=0)
    presence_hours = db.Column(db.Numeric(8, 2), default=0)
    break_hours = db.Column(db.Numeric(8, 2), default=0)
    worked_hours = db.Column(db.Numeric(8, 2), default=0)
    finalized_at = db.Column(db.DateTime)
    finalized_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)
    updated_at = db.Column(db.DateTime, default=npt_now_naive, onupdate=npt_now_naive)

    __table_args__ = (db.UniqueConstraint("user_id", "year", "month"),)


class SalaryDeduction(db.Model):
    __tablename__ = "salary_deductions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    deduction_type = db.Column(db.String(50))  # other, damage, loan...
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reason = db.Column(db.Text)
    deduction_month = db.Column(db.Date)  # first of month
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)


class StaffConsumption(db.Model):
    __tablename__ = "staff_consumptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    item_name = db.Column(db.String(150), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"))
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)  # snapshot
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reason = db.Column(db.Text)
    note = db.Column(db.Text)
    consumption_date = db.Column(db.Date, default=date.today)
    deduction_month = db.Column(db.Date)
    status = db.Column(db.String(20), default="pending")  # pending, approved, rejected
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=npt_now_naive)


class Fine(db.Model):
    __tablename__ = "fines"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    fine_date = db.Column(db.Date, default=date.today)
    deduction_month = db.Column(db.Date)
    calculation_details = db.Column(db.Text)
    status = db.Column(db.String(20), default="active")  # active, waived, adjusted
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)


class SalaryAdvance(db.Model):
    __tablename__ = "salary_advances"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reason = db.Column(db.Text)
    advance_date = db.Column(db.Date, default=date.today)
    deduction_month = db.Column(db.Date)
    recovered = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(20), default="pending")  # pending, recovered, partial
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)


class SalaryPayment(db.Model):
    __tablename__ = "salary_payments"
    id = db.Column(db.Integer, primary_key=True)
    salary_record_id = db.Column(db.Integer, db.ForeignKey("salary_records.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(50), default="cash")  # cash, bank, qr, other
    reference = db.Column(db.String(100))
    notes = db.Column(db.String(255))
    paid_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    paid_at = db.Column(db.DateTime, default=npt_now_naive)


class Attendance(db.Model):
    __tablename__ = "attendances"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    check_in = db.Column(db.DateTime)
    check_out = db.Column(db.DateTime)
    presence_minutes = db.Column(db.Integer, default=0)
    break_minutes = db.Column(db.Integer, default=0)
    worked_minutes = db.Column(db.Integer, default=0)
    overtime_minutes = db.Column(db.Integer, default=0)
    late_minutes = db.Column(db.Integer, default=0)
    early_minutes = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="pending")  # pending, checked_in, working, checked_out, approved, rejected
    notes = db.Column(db.Text)
    check_in_lat = db.Column(db.Float)
    check_in_lng = db.Column(db.Float)
    check_out_lat = db.Column(db.Float)
    check_out_lng = db.Column(db.Float)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)

    __table_args__ = (db.UniqueConstraint("user_id", "date"),)


class LeaveType(db.Model):
    __tablename__ = "leave_types"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    is_paid = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)


class LeaveRequest(db.Model):
    __tablename__ = "leave_requests"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    leave_type_id = db.Column(db.Integer, db.ForeignKey("leave_types.id"))
    leave_date = db.Column(db.Date, nullable=False)
    leave_mode = db.Column(db.String(20), default="full")  # full, first_half, second_half
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending")
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=npt_now_naive)


class BreakRequest(db.Model):
    __tablename__ = "break_requests"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    break_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer)
    reason = db.Column(db.Text)
    note = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending")
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)


class OvertimeRequest(db.Model):
    __tablename__ = "overtime_requests"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ot_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    hours = db.Column(db.Numeric(6, 2))
    reason = db.Column(db.Text)
    note = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending")
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)



class AttendanceLog(db.Model):
    """Every check-in / check-out attempt (success or outside radius)."""
    __tablename__ = "attendance_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action = db.Column(db.String(30), nullable=False, index=True)
    # check_in, check_in_try, check_out, check_out_try
    success = db.Column(db.Boolean, default=False)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    distance_m = db.Column(db.Float)  # distance from hotel geofence center
    message = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=npt_now_naive, index=True)

    user = db.relationship("User", backref=db.backref("attendance_logs", lazy="dynamic"))
