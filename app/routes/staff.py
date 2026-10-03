from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from app import db
from app.models.user import User, Role, Permission, RolePermission, StaffPermission, StaffSession
from app.models.staff_hr import StaffSalaryProfile, Attendance, AttendanceLog, LeaveRequest, BreakRequest, OvertimeRequest
from app.utils.decorators import permission_required
from app.utils.audit import log_activity, log_audit
from app.services.email_service import notify
from datetime import datetime, date
from app.utils.timeutil import npt_now_naive, now_npt

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
        bank_acc = (request.form.get("bank_account_number") or "").strip()
        wallet_acc = (request.form.get("wallet_account_number") or "").strip()
        if not bank_acc and not wallet_acc:
            flash("Bank account number वा Wallet account number मध्ये कम्तिमा एक अनिवार्य छ।", "danger")
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
            bank_name=(request.form.get("bank_name") or "").strip() or None,
            bank_account_number=bank_acc or None,
            wallet_provider=(request.form.get("wallet_provider") or "").strip() or None,
            wallet_account_number=wallet_acc or None,
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
    """Check-in / check-out with hotel geofence (default 200m). Nepal time."""
    import math
    from app.models.settings import BusinessSettings
    from app.services.email_service import send_email, get_admin_emails

    today = now_npt().date()
    bs = BusinessSettings.get_settings()
    hotel_lat = getattr(bs, "attendance_lat", None)
    hotel_lng = getattr(bs, "attendance_lng", None)
    radius = getattr(bs, "attendance_radius_m", None) or 200

    def haversine_m(lat1, lon1, lat2, lon2):
        R = 6371000.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * R * math.asin(math.sqrt(a))

    def log_attempt(action, success, lat, lng, dist, message):
        db.session.add(AttendanceLog(
            user_id=current_user.id,
            action=action,
            success=success,
            latitude=lat,
            longitude=lng,
            distance_m=dist,
            message=message,
            created_at=npt_now_naive(),
        ))

    def notify_outside(action, lat, lng, dist):
        try:
            name = current_user.full_name
            subj = f"[HMS] Outside geofence: {name} {action}"
            body = (
                f"<p><strong>{name}</strong> tried <strong>{action}</strong> outside the hotel radius.</p>"
                f"<p>Distance: <strong>{dist:.0f} m</strong> (allowed {radius} m)</p>"
                f"<p>Location: {lat:.6f}, {lng:.6f}</p>"
                f"<p>Time (NPT): {npt_now_naive().strftime('%d/%m/%Y %H:%M')}</p>"
            )
            for email in get_admin_emails() or []:
                send_email(email, subj, body, subj)
            if current_user.email:
                send_email(
                    current_user.email,
                    "Check-in/out blocked — outside hotel area",
                    f"<p>Your {action} was blocked because you are about {dist:.0f} m from the hotel "
                    f"(allowed {radius} m). Please try again at the hotel.</p>",
                    "Outside hotel geofence",
                )
        except Exception:
            pass

    if request.method == "POST":
        action = request.form.get("action")
        try:
            lat = float(request.form.get("latitude") or "")
            lng = float(request.form.get("longitude") or "")
        except (TypeError, ValueError):
            lat = lng = None

        geo_configured = hotel_lat is not None and hotel_lng is not None
        dist = None
        if geo_configured and lat is not None and lng is not None:
            dist = haversine_m(float(hotel_lat), float(hotel_lng), lat, lng)
        elif geo_configured and (lat is None or lng is None):
            flash("Location permission required for check-in/out. Allow GPS and try again.", "danger")
            log_attempt(
                "check_in_try" if action == "check_in" else "check_out_try",
                False, None, None, None, "Location not provided",
            )
            db.session.commit()
            return redirect(url_for("staff.my_attendance"))

        outside = geo_configured and dist is not None and dist > float(radius)

        att = Attendance.query.filter_by(user_id=current_user.id, date=today).first()
        if action == "check_in":
            if outside:
                log_attempt("check_in_try", False, lat, lng, dist, f"Outside radius ({dist:.0f}m)")
                db.session.commit()
                notify_outside("check-in", lat, lng, dist)
                flash(f"Check-in blocked: you are {dist:.0f} m away (max {radius} m). Admin notified.", "danger")
            elif att and att.check_in:
                flash("Already checked in today.", "warning")
            else:
                if not att:
                    att = Attendance(user_id=current_user.id, date=today)
                    db.session.add(att)
                att.check_in = npt_now_naive()
                att.status = "checked_in"
                att.check_in_lat = lat
                att.check_in_lng = lng
                log_attempt("check_in", True, lat, lng, dist, "OK")
                db.session.commit()
                flash(f"Checked in at {att.check_in.strftime('%H:%M')} NPT · Working", "success")
        elif action == "check_out" and att and att.check_in and not att.check_out:
            if outside:
                log_attempt("check_out_try", False, lat, lng, dist, f"Outside radius ({dist:.0f}m)")
                db.session.commit()
                notify_outside("check-out", lat, lng, dist)
                flash(f"Check-out blocked: you are {dist:.0f} m away (max {radius} m). Admin notified.", "danger")
            else:
                att.check_out = npt_now_naive()
                att.status = "checked_out"
                att.check_out_lat = lat
                att.check_out_lng = lng
                delta = att.check_out - att.check_in
                att.presence_minutes = int(delta.total_seconds() // 60)
                att.worked_minutes = att.presence_minutes
                log_attempt("check_out", True, lat, lng, dist, "OK")
                db.session.commit()
                flash(f"Checked out at {att.check_out.strftime('%H:%M')} NPT", "success")
        elif action == "check_out":
            flash("No active check-in to check out.", "warning")
        return redirect(url_for("staff.my_attendance"))

    records = Attendance.query.filter_by(user_id=current_user.id).order_by(Attendance.date.desc()).limit(30).all()
    today_att = Attendance.query.filter_by(user_id=current_user.id, date=today).first()
    # auto status label for display
    status_label = None
    if today_att and today_att.check_in and not today_att.check_out:
        status_label = "Working"
        if today_att.status not in ("checked_in", "working"):
            today_att.status = "working"
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    elif today_att and today_att.check_out:
        status_label = "Checked out"

    return render_template(
        "staff/attendance.html",
        records=records,
        today_att=today_att,
        npt_now=now_npt(),
        npt_today=today,
        status_label=status_label,
        geo_required=bool(hotel_lat is not None and hotel_lng is not None),
        radius_m=radius,
    )


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
        # Payment account (bank or wallet — at least one required)
        bank_acc = (request.form.get("bank_account_number") or "").strip()
        wallet_acc = (request.form.get("wallet_account_number") or "").strip()
        if not bank_acc and not wallet_acc:
            flash("Bank account number वा Wallet account number मध्ये कम्तिमा एक अनिवार्य छ।", "danger")
            return render_template("staff/form.html", user=user, roles=roles)
        sp = user.salary_profile
        if not sp:
            from app.models.staff_hr import StaffSalaryProfile
            from decimal import Decimal
            sp = StaffSalaryProfile(user_id=user.id, basic_salary=Decimal("0"), allowance=Decimal("0"))
            db.session.add(sp)
        sp.bank_name = (request.form.get("bank_name") or "").strip() or None
        sp.bank_account_number = bank_acc or None
        sp.wallet_provider = (request.form.get("wallet_provider") or "").strip() or None
        sp.wallet_account_number = wallet_acc or None
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
        lr.reviewed_at = npt_now_naive()
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




@staff_bp.route("/attendance/logs")
@login_required
@permission_required("staff.view")
def attendance_logs():
    """Admin: location attempts — check-in/out success & blocked tries."""
    staff_id = request.args.get("staff_id", type=int)
    users = User.query.order_by(User.full_name).all()
    q = AttendanceLog.query
    if staff_id:
        q = q.filter_by(user_id=staff_id)
    logs = q.order_by(AttendanceLog.created_at.desc()).limit(200).all()
    user_map = {u.id: u for u in users}
    from app.models.settings import BusinessSettings
    bs = BusinessSettings.get_settings()
    return render_template(
        "staff/attendance_logs.html",
        logs=logs,
        users=users,
        staff_id=staff_id,
        user_map=user_map,
        hotel_lat=getattr(bs, "attendance_lat", None),
        hotel_lng=getattr(bs, "attendance_lng", None),
        radius_m=getattr(bs, "attendance_radius_m", None) or 200,
        npt_now=now_npt(),
    )


@staff_bp.route("/attendance/report")
@login_required
@permission_required("staff.view")
def attendance_report():
    """Admin: Staff Attendance — filter by staff, month/year, or specific day (Nepal calendar)."""
    from calendar import monthrange
    from app.models.staff_hr import Attendance
    from app.utils.timeutil import now_npt

    users = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    # also include inactive if they have records
    all_users = User.query.order_by(User.full_name).all()

    npt = now_npt()
    staff_id = request.args.get("staff_id", type=int)
    year = request.args.get("year", type=int) or npt.year
    month = request.args.get("month", type=int) or npt.month
    day_s = (request.args.get("day") or "").strip()  # dd/mm/yyyy

    specific_day = None
    if day_s:
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                specific_day = datetime.strptime(day_s, fmt).date()
                break
            except ValueError:
                continue
        if not specific_day:
            flash("Invalid day format. Use dd/mm/yyyy (Nepal date).", "danger")

    if specific_day:
        start = specific_day
        end = specific_day
        mode = "day"
    else:
        last = monthrange(year, month)[1]
        start = date(year, month, 1)
        end = date(year, month, last)
        mode = "month"

    q = Attendance.query.filter(Attendance.date >= start, Attendance.date <= end)
    if staff_id:
        q = q.filter_by(user_id=staff_id)
    records = q.order_by(Attendance.date.asc(), Attendance.user_id).all()

    user_map = {u.id: u for u in all_users}
    # summary per staff
    summary = {}
    for r in records:
        s = summary.setdefault(r.user_id, {"days": 0, "minutes": 0, "name": (user_map.get(r.user_id).full_name if user_map.get(r.user_id) else f"#{r.user_id}")})
        if r.check_in:
            s["days"] += 1
            s["minutes"] += r.presence_minutes or 0

    years = list(range(npt.year - 2, npt.year + 2))
    months = list(range(1, 13))
    month_names = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]

    return render_template(
        "staff/attendance_report.html",
        users=users,
        all_users=all_users,
        records=records,
        summary=summary,
        staff_id=staff_id,
        year=year,
        month=month,
        months=months,
        month_names=month_names,
        years=years,
        day_s=day_s if specific_day else "",
        start=start,
        end=end,
        mode=mode,
        npt_now=npt,
    )


@staff_bp.route("/attendance/report/mail", methods=["POST"])
@login_required
@permission_required("staff.view")
def attendance_report_mail():
    from app.models.staff_hr import Attendance
    from app.services.email_service import send_email, get_admin_emails

    staff_id = request.form.get("staff_id", type=int)
    year = request.form.get("year", type=int)
    month = request.form.get("month", type=int)
    day_s = (request.form.get("day") or "").strip()

    specific_day = None
    if day_s:
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                specific_day = datetime.strptime(day_s, fmt).date()
                break
            except ValueError:
                continue

    if specific_day:
        start = end = specific_day
    else:
        from calendar import monthrange
        from app.utils.timeutil import now_npt
        npt = now_npt()
        year = year or npt.year
        month = month or npt.month
        last = monthrange(year, month)[1]
        start = date(year, month, 1)
        end = date(year, month, last)

    q = Attendance.query.filter(Attendance.date >= start, Attendance.date <= end)
    if staff_id:
        q = q.filter_by(user_id=staff_id)
    records = q.order_by(Attendance.date, Attendance.user_id).all()
    users = {u.id: u for u in User.query.all()}
    rows = []
    for r in records:
        u = users.get(r.user_id)
        name = u.full_name if u else f"#{r.user_id}"
        d = r.date.strftime("%d/%m/%Y") if r.date else "—"
        cin = r.check_in.strftime("%H:%M") if r.check_in else "—"
        cout = r.check_out.strftime("%H:%M") if r.check_out else "—"
        rows.append(f"<tr><td>{d}</td><td>{name}</td><td>{cin}</td><td>{cout}</td><td>{r.presence_minutes or 0}</td><td>{r.status}</td></tr>")
    html = (
        f"<h2>Staff Attendance {start.strftime('%d/%m/%Y')} → {end.strftime('%d/%m/%Y')} (Nepal)</h2>"
        f"<table border='1' cellpadding='6' cellspacing='0'>"
        f"<thead><tr><th>Date (dd/mm/yyyy)</th><th>Staff</th><th>In</th><th>Out</th><th>Minutes</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(rows) or '<tr><td colspan=6>No records</td></tr>'}</tbody></table>"
    )
    try:
        subject = f"Attendance report {start.strftime('%d/%m/%Y')} to {end.strftime('%d/%m/%Y')}"
        ok = False
        for email in get_admin_emails() or []:
            if send_email(email, subject, html, subject):
                ok = True
        if ok:
            flash("Attendance report emailed to admin.", "success")
        else:
            flash("No admin email configured or mail failed.", "warning")
    except Exception as e:
        flash(f"Could not email report: {e}", "danger")
    return redirect(url_for(
        "staff.attendance_report",
        staff_id=staff_id or "",
        year=year or "",
        month=month or "",
        day=day_s or "",
    ))

