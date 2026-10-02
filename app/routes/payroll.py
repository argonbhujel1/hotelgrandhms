from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.staff_hr import SalaryRecord, StaffSalaryProfile, SalaryPayment, SalaryIncrement
from app.services.email_service import notify
from app.models.user import User
from app.utils.decorators import permission_required
from app.utils.audit import log_activity
from datetime import date
from decimal import Decimal
from calendar import monthrange

payroll_bp = Blueprint("payroll", __name__)


def _ensure_running(user_id, year, month):
    rec = SalaryRecord.query.filter_by(user_id=user_id, year=year, month=month).first()
    if rec:
        return rec
    profile = StaffSalaryProfile.query.filter_by(user_id=user_id).first()
    basic = profile.basic_salary if profile else Decimal("0")
    allowance = profile.allowance if profile else Decimal("0")
    gross = (basic or 0) + (allowance or 0)
    rec = SalaryRecord(
        user_id=user_id,
        year=year,
        month=month,
        status="running",
        basic=basic or 0,
        allowance=allowance or 0,
        gross_earnings=gross,
        net_payable=gross,
        remaining=gross,
        working_days=26,
    )
    db.session.add(rec)
    db.session.commit()
    return rec


@payroll_bp.route("/")
@login_required
@permission_required("salary.view")
def index():
    today = date.today()
    year, month = today.year, today.month
    if current_user.has_permission("salary.reports") or current_user.role_code in ("super_admin", "admin"):
        users = User.query.filter_by(is_active=True).all()
        records = []
        user_map = {}
        for u in users:
            records.append(_ensure_running(u.id, year, month))
            user_map[u.id] = u
        return render_template("payroll/admin.html", records=records, year=year, month=month, user_map=user_map)
    # Staff self view
    rec = _ensure_running(current_user.id, year, month)
    history = SalaryRecord.query.filter_by(user_id=current_user.id).order_by(
        SalaryRecord.year.desc(), SalaryRecord.month.desc()
    ).all()
    return render_template("payroll/my.html", current=rec, history=history)


@payroll_bp.route("/<int:rid>")
@login_required
@permission_required("salary.view")
def view_record(rid):
    rec = db.session.get(SalaryRecord, rid)
    if not rec:
        flash("Not found.", "danger")
        return redirect(url_for("payroll.index"))
    if rec.user_id != current_user.id and not current_user.has_permission("salary.reports"):
        flash("Access denied.", "danger")
        return redirect(url_for("payroll.index"))
    user = db.session.get(User, rec.user_id)
    payments = SalaryPayment.query.filter_by(salary_record_id=rec.id).all()
    return render_template("payroll/payslip.html", rec=rec, user=user, payments=payments)


@payroll_bp.route("/<int:rid>/print")
@login_required
@permission_required("salary.view")
def print_payslip(rid):
    rec = db.session.get(SalaryRecord, rid)
    if not rec:
        flash("Not found.", "danger")
        return redirect(url_for("payroll.index"))
    if rec.user_id != current_user.id and not current_user.has_permission("salary.reports"):
        flash("Access denied.", "danger")
        return redirect(url_for("payroll.index"))
    user = db.session.get(User, rec.user_id)
    from app.models.settings import BusinessSettings
    settings = BusinessSettings.get_settings()
    return render_template("payroll/print.html", rec=rec, user=user, settings=settings)


@payroll_bp.route("/<int:rid>/finalize", methods=["POST"])
@login_required
@permission_required("salary.create")
def finalize(rid):
    rec = db.session.get(SalaryRecord, rid)
    if rec and rec.status == "running":
        rec.status = "final"
        from datetime import datetime
        rec.finalized_at = datetime.utcnow()
        rec.finalized_by_id = current_user.id
        db.session.commit()
        log_activity("finalize_payroll", module="payroll", record_id=rec.id)
        staff_user = db.session.get(User, rec.user_id)
        if staff_user:
            notify(
                staff_user,
                "payroll_finalized",
                month=f"{rec.month}/{rec.year}",
                net_payable=str(rec.net_payable or 0),
                basic=str(rec.basic or 0),
                allowance=str(rec.allowance or 0),
                ot_pay=str(rec.ot_pay or 0),
                gross_earnings=str(rec.gross_earnings or 0),
                total_deduction=str(rec.total_deduction or 0),
                unpaid_leave_deduction=str(rec.unpaid_leave_deduction or 0),
                late_deduction=str(rec.late_deduction or 0),
                food_deduction=str(rec.food_deduction or 0),
                fine_deduction=str(rec.fine_deduction or 0),
                advance_deduction=str(rec.advance_deduction or 0),
                other_deduction=str(rec.other_deduction or 0),
                total_paid=str(rec.total_paid or 0),
                remaining=str(rec.remaining or 0),
                working_days=str(rec.working_days or 26),
            )
        flash("Payroll finalized.", "success")
    return redirect(url_for("payroll.view_record", rid=rid))


@payroll_bp.route("/<int:rid>/pay", methods=["POST"])
@login_required
@permission_required("salary.payment")
def pay(rid):
    rec = db.session.get(SalaryRecord, rid)
    if not rec:
        flash("Not found.", "danger")
        return redirect(url_for("payroll.index"))
    amount = Decimal(request.form.get("amount") or "0")
    if amount <= 0:
        flash("Invalid amount.", "danger")
        return redirect(url_for("payroll.view_record", rid=rid))
    pay = SalaryPayment(
        salary_record_id=rec.id,
        user_id=rec.user_id,
        amount=amount,
        method=request.form.get("method") or "cash",
        reference=request.form.get("reference"),
        paid_by_id=current_user.id,
    )
    rec.total_paid = (rec.total_paid or 0) + amount
    rec.remaining = (rec.net_payable or 0) - rec.total_paid
    db.session.add(pay)
    db.session.commit()
    log_activity("salary_payment", module="payroll", record_id=rec.id, details=str(amount))
    flash("Payment recorded.", "success")
    return redirect(url_for("payroll.view_record", rid=rid))

@payroll_bp.route("/<int:rid>/edit", methods=["GET", "POST"])
@login_required
@permission_required("salary.edit")
def edit_record(rid):
    rec = db.session.get(SalaryRecord, rid)
    if not rec:
        flash("Not found.", "danger")
        return redirect(url_for("payroll.index"))
    if rec.status == "final" and current_user.role_code not in ("super_admin", "admin"):
        flash("Finalized payroll is locked.", "warning")
        return redirect(url_for("payroll.view_record", rid=rid))
    user = db.session.get(User, rec.user_id)
    if request.method == "POST":
        if rec.status == "final" and current_user.role_code not in ("super_admin", "admin"):
            flash("Cannot edit finalized payroll.", "danger")
            return redirect(url_for("payroll.view_record", rid=rid))
        rec.basic = Decimal(request.form.get("basic") or rec.basic or 0)
        rec.allowance = Decimal(request.form.get("allowance") or rec.allowance or 0)
        rec.ot_hours = Decimal(request.form.get("ot_hours") or rec.ot_hours or 0)
        rec.ot_pay = Decimal(request.form.get("ot_pay") or rec.ot_pay or 0)
        rec.unpaid_leave_deduction = Decimal(request.form.get("unpaid_leave_deduction") or 0)
        rec.late_deduction = Decimal(request.form.get("late_deduction") or 0)
        rec.early_deduction = Decimal(request.form.get("early_deduction") or 0)
        rec.food_deduction = Decimal(request.form.get("food_deduction") or 0)
        rec.fine_deduction = Decimal(request.form.get("fine_deduction") or 0)
        rec.advance_deduction = Decimal(request.form.get("advance_deduction") or 0)
        rec.other_deduction = Decimal(request.form.get("other_deduction") or 0)
        rec.gross_earnings = (rec.basic or 0) + (rec.allowance or 0) + (rec.ot_pay or 0)
        rec.total_deduction = (
            (rec.unpaid_leave_deduction or 0) + (rec.late_deduction or 0) + (rec.early_deduction or 0)
            + (rec.food_deduction or 0) + (rec.fine_deduction or 0) + (rec.advance_deduction or 0)
            + (rec.other_deduction or 0)
        )
        rec.net_payable = rec.gross_earnings - rec.total_deduction
        rec.remaining = rec.net_payable - (rec.total_paid or 0)
        # Super admin can unlock final back to running
        if request.form.get("status") in ("running", "final") and current_user.role_code in ("super_admin", "admin"):
            rec.status = request.form.get("status")
        db.session.commit()
        log_activity("edit_payroll", module="payroll", record_id=rec.id)
        flash("Payroll updated.", "success")
        return redirect(url_for("payroll.view_record", rid=rid))
    return render_template("payroll/edit.html", rec=rec, user=user)


@payroll_bp.route("/increment/<int:uid>", methods=["GET", "POST"])
@login_required
@permission_required("salary.increment")
def salary_increment(uid):
    user = db.session.get(User, uid)
    if not user:
        flash("Staff not found.", "danger")
        return redirect(url_for("payroll.index"))
    profile = StaffSalaryProfile.query.filter_by(user_id=user.id).first()
    if not profile:
        profile = StaffSalaryProfile(user_id=user.id, basic_salary=Decimal("0"), allowance=Decimal("0"), effective_from=date.today())
        db.session.add(profile)
        db.session.commit()

    if request.method == "POST":
        prev_basic = profile.basic_salary or Decimal("0")
        prev_allow = profile.allowance or Decimal("0")
        new_basic = Decimal(request.form.get("new_basic") or prev_basic)
        new_allow = Decimal(request.form.get("new_allowance") or prev_allow)
        effective = request.form.get("effective_from") or date.today().isoformat()
        try:
            effective_date = date.fromisoformat(effective)
        except ValueError:
            effective_date = date.today()
        inc_amt = (new_basic - prev_basic) + (new_allow - prev_allow)
        inc_pct = Decimal("0")
        if prev_basic and prev_basic > 0:
            inc_pct = ((new_basic - prev_basic) / prev_basic * 100).quantize(Decimal("0.01"))
        reason = request.form.get("reason") or ""

        row = SalaryIncrement(
            user_id=user.id,
            previous_basic=prev_basic,
            new_basic=new_basic,
            previous_allowance=prev_allow,
            new_allowance=new_allow,
            increment_amount=inc_amt,
            increment_percent=inc_pct,
            effective_from=effective_date,
            reason=reason,
            updated_by_id=current_user.id,
        )
        db.session.add(row)
        profile.basic_salary = new_basic
        profile.allowance = new_allow
        profile.effective_from = effective_date
        db.session.commit()

        log_activity("salary_increment", module="payroll", record_id=user.id, details=str(inc_amt))
        notify(
            user,
            "salary_increment",
            previous_basic=str(prev_basic),
            new_basic=str(new_basic),
            previous_allowance=str(prev_allow),
            new_allowance=str(new_allow),
            increment_amount=str(inc_amt),
            increment_percent=str(inc_pct),
            effective_from=str(effective_date),
            reason=reason,
        )
        flash(f"Salary incremented for {user.full_name}. Email notification sent.", "success")
        return redirect(url_for("staff.profile", uid=user.id))

    history = SalaryIncrement.query.filter_by(user_id=user.id).order_by(SalaryIncrement.created_at.desc()).all()
    return render_template("payroll/increment.html", user=user, profile=profile, history=history)
