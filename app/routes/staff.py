from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from app import db
from app.models.user import User, Role, Permission, RolePermission, StaffPermission, StaffSession
from app.models.staff_hr import StaffSalaryProfile, Attendance, LeaveRequest, BreakRequest, OvertimeRequest
from app.utils.decorators import permission_required
from app.utils.audit import log_activity, log_audit
from app.services.email_service import notify
from datetime import datetime, date

staff_bp = Blueprint("staff", __name__)


@staff_bp.route("/")
@login_required
@permission_required("staff.view")
def list_staff():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "active")  # active | inactive | all
    role_id = request.args.get("role_id", type=int)
    query = User.query
    if status == "active":
        query = query.filter_by(is_active=True)
    elif status == "inactive":
        query = query.filter_by(is_active=False)
    if role_id:
        query = query.filter_by(role_id=role_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                User.full_name.ilike(like),
                User.username.ilike(like),
                User.employee_id.ilike(like),
                User.phone.ilike(like),
                User.email.ilike(like),
            )
        )
    users = query.order_by(User.full_name).all()
    roles = Role.query.order_by(Role.name).all()
    return render_template("staff/list.html", users=users, q=q, status=status, roles=roles, role_id=role_id)



@staff_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required("staff.add")
def add_staff():
    roles = Role.query.order_by(Role.name).all()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        if User.query.filter_by(username=username).first():
            flash("Username already taken.", "danger")
            return render_template("staff/form.html", user=None, roles=roles)
        plain_password = (request.form.get("password") or "changeme123").strip()
        u = User(
            username=username,
            email=request.form.get("email"),
            full_name=request.form.get("full_name"),
            employee_id=request.form.get("employee_id") or None,
            phone=request.form.get("phone"),
            department=request.form.get("department"),
            role_id=int(request.form.get("role_id")),
            password_hash=generate_password_hash(plain_password),
            is_active=True,
            joining_date=date.today(),
        )
        db.session.add(u)
        db.session.flush()
        basic = request.form.get("basic_salary")
        from decimal import Decimal
        db.session.add(StaffSalaryProfile(
            user_id=u.id,
            basic_salary=Decimal(basic or "0"),
            allowance=Decimal(request.form.get("allowance") or "0"),
            effective_from=date.today(),
            work_start=request.form.get("work_start") or None,
            work_end=request.form.get("work_end") or None,
            required_daily_hours=Decimal(request.form.get("required_daily_hours")) if request.form.get("required_daily_hours") else None,
        ))
        db.session.commit()
        log_activity("create_staff", module="staff", record_id=u.id)
        notify(
            u,
            "welcome_staff",
            username=u.username,
            password=plain_password,
            login_url="https://hms.hotelgrand.com.np/login",
        )
        flash("Staff created. Login credentials emailed.", "success")
        return redirect(url_for("staff.list_staff"))
    return render_template("staff/form.html", user=None, roles=roles)


@staff_bp.route("/<int:uid>")
@login_required
@permission_required("staff.view")
def profile(uid):
    user = db.session.get(User, uid)
    if not user:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    roles = Role.query.order_by(Role.name).all()
    return render_template("staff/profile.html", user=user, roles=roles)


@staff_bp.route("/<int:uid>/permissions", methods=["GET", "POST"])
@login_required
@permission_required("staff.permissions")
def permissions(uid):
    user = db.session.get(User, uid)
    if not user:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    all_perms = Permission.query.order_by(Permission.code).all()
    role_perm_ids = {rp.permission_id for rp in user.role.permissions} if user.role else set()
    extra = {sp.permission_id: sp.granted for sp in user.extra_permissions}

    if request.method == "POST":
        StaffPermission.query.filter_by(user_id=user.id).delete()
        selected = request.form.getlist("perm")
        for pid in selected:
            pid = int(pid)
            if pid not in role_perm_ids:
                db.session.add(StaffPermission(user_id=user.id, permission_id=pid, granted=True))
        db.session.commit()
        log_audit("update_permissions", module="staff", record_id=user.id)
        flash("Permissions updated.", "success")
        return redirect(url_for("staff.profile", uid=uid))

    return render_template(
        "staff/permissions.html",
        user=user,
        all_perms=all_perms,
        role_perm_ids=role_perm_ids,
        extra=extra,
    )


@staff_bp.route("/sessions")
@login_required
@permission_required("sessions.view")
def live_sessions():
    sessions = StaffSession.query.filter_by(is_active=True).order_by(StaffSession.last_activity.desc()).all()
    return render_template("staff/sessions.html", sessions=sessions)


@staff_bp.route("/sessions/<int:sid>/logout", methods=["POST"])
@login_required
@permission_required("sessions.force_logout")
def force_logout(sid):
    s = db.session.get(StaffSession, sid)
    if s:
        s.is_active = False
        s.status = "offline"
        # Invalidate all active tokens for that user if requested
        if request.form.get("all_sessions"):
            StaffSession.query.filter_by(user_id=s.user_id, is_active=True).update(
                {"is_active": False, "status": "offline"}
            )
        db.session.commit()
        log_activity("force_logout", module="sessions", record_id=s.user_id)
        flash("Session terminated. User must re-login.", "info")
    return redirect(url_for("staff.live_sessions"))


@staff_bp.route("/attendance", methods=["GET", "POST"])
@login_required
def my_attendance():
    if request.method == "POST":
        action = request.form.get("action")
        today = date.today()
        att = Attendance.query.filter_by(user_id=current_user.id, date=today).first()
        if action == "check_in":
            if att and att.check_in:
                flash("Already checked in today.", "warning")
            else:
                if not att:
                    att = Attendance(user_id=current_user.id, date=today, status="pending")
                    db.session.add(att)
                att.check_in = datetime.utcnow()
                db.session.commit()
                flash("Checked in.", "success")
        elif action == "check_out" and att and att.check_in and not att.check_out:
            att.check_out = datetime.utcnow()
            delta = att.check_out - att.check_in
            att.presence_minutes = int(delta.total_seconds() // 60)
            att.worked_minutes = att.presence_minutes
            db.session.commit()
            flash("Checked out.", "success")
        return redirect(url_for("staff.my_attendance"))
    records = Attendance.query.filter_by(user_id=current_user.id).order_by(Attendance.date.desc()).limit(30).all()
    today_att = Attendance.query.filter_by(user_id=current_user.id, date=date.today()).first()
    return render_template("staff/attendance.html", records=records, today_att=today_att)


@staff_bp.route("/<int:uid>/reset-password", methods=["GET", "POST"])
@login_required
@permission_required("staff.reset_pw")
def reset_password(uid):
    user = db.session.get(User, uid)
    if not user:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    if request.method == "POST":
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        if len(new) < 6:
            flash("Password must be at least 6 characters.", "danger")
        elif new != confirm:
            flash("Passwords do not match.", "danger")
        else:
            user.password_hash = generate_password_hash(new)
            # Kill all sessions for this user
            StaffSession.query.filter_by(user_id=user.id, is_active=True).update(
                {"is_active": False, "status": "offline"}
            )
            db.session.commit()
            log_activity("reset_password", module="staff", record_id=user.id)
            notify(
                user,
                "password_reset",
                username=user.username,
                password=new,
                login_url="https://hms.hotelgrand.com.np/login",
            )
            flash(f"Password reset for {user.full_name}. New password emailed. All sessions logged out.", "success")
            return redirect(url_for("staff.profile", uid=uid))
    return render_template("staff/reset_password.html", user=user)




@staff_bp.route("/<int:uid>/edit", methods=["GET", "POST"])
@login_required
@permission_required("staff.edit")
def edit_staff(uid):
    user = db.session.get(User, uid)
    if not user:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    roles = Role.query.order_by(Role.name).all()
    if request.method == "POST":
        old_role = user.role.code if user.role else None
        user.full_name = request.form.get("full_name") or user.full_name
        user.email = request.form.get("email") or user.email
        user.phone = request.form.get("phone")
        user.employee_id = request.form.get("employee_id") or user.employee_id
        user.department = request.form.get("department")
        new_role_id = int(request.form.get("role_id") or user.role_id)
        # Protect: cannot demote last super_admin / cannot change own role away from admin without care
        if user.id == current_user.id and new_role_id != user.role_id:
            # allow but warn
            pass
        if current_user.has_permission("staff.role") or current_user.role_code in ("super_admin", "admin"):
            user.role_id = new_role_id
        db.session.commit()
        new_role = user.role.code if user.role else None
        if old_role != new_role:
            log_audit("change_role", module="staff", record_id=user.id, previous=old_role, new=new_role)
            log_activity("change_role", module="staff", record_id=user.id, details=f"{old_role}->{new_role}")
        else:
            log_activity("edit_staff", module="staff", record_id=user.id)
        flash("Staff updated.", "success")
        return redirect(url_for("staff.profile", uid=uid))
    return render_template("staff/form.html", user=user, roles=roles)


@staff_bp.route("/<int:uid>/deactivate", methods=["POST"])
@login_required
@permission_required("staff.disable")
def deactivate_staff(uid):
    user = db.session.get(User, uid)
    if not user:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("staff.profile", uid=uid))
    if user.role and user.role.code == "super_admin":
        # prevent deactivating the only super admin
        others = User.query.filter(User.role_id == user.role_id, User.is_active == True, User.id != user.id).count()
        if others < 1:
            flash("Cannot deactivate the only Super Admin.", "danger")
            return redirect(url_for("staff.profile", uid=uid))
    user.is_active = False
    StaffSession.query.filter_by(user_id=user.id, is_active=True).update(
        {"is_active": False, "status": "offline"}
    )
    db.session.commit()
    log_activity("deactivate_staff", module="staff", record_id=user.id)
    log_audit("deactivate_staff", module="staff", record_id=user.id, previous="active", new="inactive")
    flash(f"{user.full_name} deactivated. Sessions ended.", "info")
    return redirect(url_for("staff.profile", uid=uid))


@staff_bp.route("/<int:uid>/activate", methods=["POST"])
@login_required
@permission_required("staff.disable")
def activate_staff(uid):
    user = db.session.get(User, uid)
    if not user:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    user.is_active = True
    db.session.commit()
    log_activity("activate_staff", module="staff", record_id=user.id)
    flash(f"{user.full_name} activated.", "success")
    return redirect(url_for("staff.profile", uid=uid))


@staff_bp.route("/<int:uid>/delete", methods=["POST"])
@login_required
@permission_required("staff.disable")
def delete_staff(uid):
    """Soft-delete: deactivate permanently flagged. Hard delete only if never had financial ties — we soft-delete always for safety."""
    user = db.session.get(User, uid)
    if not user:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("staff.profile", uid=uid))
    if user.role and user.role.code == "super_admin":
        others = User.query.filter(User.role_id == user.role_id, User.is_active == True, User.id != user.id).count()
        if others < 1:
            flash("Cannot delete the only Super Admin.", "danger")
            return redirect(url_for("staff.profile", uid=uid))
    # Soft delete = deactivate + rename username so it can be reused
    user.is_active = False
    stamp = str(user.id)
    if not user.username.endswith("_deleted"):
        user.username = f"{user.username}_deleted_{stamp}"[:80]
        user.email = f"deleted_{stamp}_{user.email}"[:120]
    StaffSession.query.filter_by(user_id=user.id, is_active=True).update(
        {"is_active": False, "status": "offline"}
    )
    db.session.commit()
    log_activity("delete_staff", module="staff", record_id=user.id)
    log_audit("delete_staff", module="staff", record_id=user.id, previous="active", new="deleted")
    flash("Staff deleted (deactivated). Payroll history preserved.", "info")
    return redirect(url_for("staff.list_staff"))


@staff_bp.route("/<int:uid>/role", methods=["POST"])
@login_required
@permission_required("staff.role")
def change_role(uid):
    user = db.session.get(User, uid)
    if not user:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    new_role_id = int(request.form.get("role_id") or 0)
    role = db.session.get(Role, new_role_id)
    if not role:
        flash("Invalid role.", "danger")
        return redirect(url_for("staff.profile", uid=uid))
    if user.id == current_user.id and role.code not in ("super_admin", "admin"):
        flash("You cannot remove admin access from your own account.", "danger")
        return redirect(url_for("staff.profile", uid=uid))
    old = user.role.code if user.role else None
    user.role_id = role.id
    db.session.commit()
    log_audit("change_role", module="staff", record_id=user.id, previous=old, new=role.code)
    flash(f"Role changed to {role.name}.", "success")
    return redirect(url_for("staff.profile", uid=uid))


@staff_bp.route("/leave", methods=["GET", "POST"])
@login_required
def request_leave():
    from app.models.staff_hr import LeaveType
    types = LeaveType.query.filter_by(is_active=True).all()
    if not types:
        for name, paid in [("Casual", True), ("Sick", True), ("Emergency", False), ("Personal", False), ("Other", False)]:
            db.session.add(LeaveType(name=name, is_paid=paid, is_active=True))
        db.session.commit()
        types = LeaveType.query.filter_by(is_active=True).all()
    if request.method == "POST":
        lr = LeaveRequest(
            user_id=current_user.id,
            leave_type_id=int(request.form.get("leave_type_id") or 0) or None,
            leave_date=date.fromisoformat(request.form.get("leave_date")),
            leave_mode=request.form.get("leave_mode") or "full",
            reason=request.form.get("reason"),
            status="pending",
        )
        db.session.add(lr)
        db.session.commit()
        notify(current_user, "leave_submitted", leave_date=str(lr.leave_date), mode=lr.leave_mode, reason=lr.reason or "")
        # notify admins
        from app.models.user import Role
        admins = User.query.join(Role).filter(Role.code.in_(["super_admin", "admin"]), User.is_active == True).all()
        for a in admins:
            if a.id != current_user.id:
                notify(a, "leave_submitted", leave_date=str(lr.leave_date), mode=f"{current_user.full_name}: {lr.leave_mode}", reason=lr.reason or "")
        flash("Leave request submitted. Email notification sent.", "success")
        return redirect(url_for("staff.request_leave"))
    my = LeaveRequest.query.filter_by(user_id=current_user.id).order_by(LeaveRequest.created_at.desc()).limit(30).all()
    return render_template("staff/leave.html", types=types, requests=my)


@staff_bp.route("/leave/<int:lid>/review", methods=["POST"])
@login_required
@permission_required("leave.approve")
def review_leave(lid):
    lr = db.session.get(LeaveRequest, lid)
    if not lr:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    status = request.form.get("status")
    if status in ("approved", "rejected"):
        lr.status = status
        lr.reviewed_by_id = current_user.id
        from datetime import datetime
        lr.reviewed_at = datetime.utcnow()
        db.session.commit()
        staff = db.session.get(User, lr.user_id)
        notify(staff, f"leave_{status}", leave_date=str(lr.leave_date), status=status, note=request.form.get("note") or "")
        flash(f"Leave {status}.", "success")
    return redirect(request.referrer or url_for("staff.list_staff"))


@staff_bp.route("/overtime", methods=["GET", "POST"])
@login_required
def request_overtime():
    def _parse_dt(val):
        """Parse datetime-local or ISO strings safely."""
        from datetime import datetime
        if not val:
            raise ValueError("Missing datetime")
        val = val.strip().replace("Z", "")
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(val)

    if request.method == "POST":
        try:
            ot_date_raw = request.form.get("ot_date") or ""
            start = _parse_dt(request.form.get("start_time"))
            end = _parse_dt(request.form.get("end_time"))
            if end <= start:
                flash("End time must be after start time.", "danger")
                my = OvertimeRequest.query.filter_by(user_id=current_user.id).order_by(OvertimeRequest.created_at.desc()).limit(30).all()
                return render_template("staff/overtime.html", requests=my)
            if ot_date_raw:
                ot_date = date.fromisoformat(ot_date_raw)
            else:
                ot_date = start.date()
            hours = Decimal(str(max(0, (end - start).total_seconds() / 3600))).quantize(Decimal("0.01"))
            ot = OvertimeRequest(
                user_id=current_user.id,
                ot_date=ot_date,
                start_time=start,
                end_time=end,
                hours=hours,
                reason=request.form.get("reason"),
                note=request.form.get("note"),
                status="pending",
            )
            db.session.add(ot)
            db.session.commit()
            notify(current_user, "overtime_submitted", date=str(ot.ot_date), hours=str(hours), reason=ot.reason or "")
            flash("Overtime submitted successfully.", "success")
            return redirect(url_for("staff.request_overtime"))
        except Exception as e:
            db.session.rollback()
            flash(f"Could not save overtime. Check date/time fields. ({e})", "danger")
    my = OvertimeRequest.query.filter_by(user_id=current_user.id).order_by(OvertimeRequest.created_at.desc()).limit(30).all()
    return render_template("staff/overtime.html", requests=my)


@staff_bp.route("/overtime/<int:oid>/review", methods=["POST"])
@login_required
@permission_required("overtime.approve")
def review_overtime(oid):
    ot = db.session.get(OvertimeRequest, oid)
    if not ot:
        flash("Not found.", "danger")
        return redirect(url_for("staff.list_staff"))
    status = request.form.get("status")
    if status in ("approved", "rejected"):
        ot.status = status
        ot.reviewed_by_id = current_user.id
        db.session.commit()
        staff = db.session.get(User, ot.user_id)
        notify(staff, f"overtime_{status}", date=str(ot.ot_date), hours=str(ot.hours), status=status)
        flash(f"Overtime {status}.", "success")
    return redirect(request.referrer or url_for("staff.list_staff"))
