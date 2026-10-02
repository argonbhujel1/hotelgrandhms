from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db
from app.models.user import User, StaffSession, StaffLoginHistory
from app.utils.audit import log_activity, log_security
import secrets

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()

        ip = request.remote_addr
        ua = request.headers.get("User-Agent", "")[:512]

        if not user or not check_password_hash(user.password_hash, password):
            log_security("failed_login", details=f"username={username}", user_id=user.id if user else None)
            if user:
                db.session.add(StaffLoginHistory(user_id=user.id, ip_address=ip, user_agent=ua, success=False))
                db.session.commit()
            flash("Invalid username or password.", "danger")
            return render_template("auth/login.html")

        if not user.is_active:
            log_security("disabled_account_login", user_id=user.id)
            flash("Your account is disabled. Contact administrator.", "danger")
            return render_template("auth/login.html")

        login_user(user, remember=bool(request.form.get("remember")))
        user.last_login_at = datetime.utcnow()

        token = secrets.token_urlsafe(32)
        sess = StaffSession(
            user_id=user.id,
            session_token=token,
            ip_address=ip,
            user_agent=ua,
            device_label=user.device_label,
            is_active=True,
            status="online",
        )
        db.session.add(sess)
        db.session.add(StaffLoginHistory(user_id=user.id, ip_address=ip, user_agent=ua, success=True))
        db.session.commit()
        session["staff_session_token"] = token

        log_activity("login", module="auth")
        next_url = request.args.get("next") or url_for("dashboard.index")
        return redirect(next_url)

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    token = session.pop("staff_session_token", None)
    if token:
        s = StaffSession.query.filter_by(session_token=token, user_id=current_user.id).first()
        if s:
            s.is_active = False
            s.status = "offline"
            db.session.commit()
    log_activity("logout", module="auth")
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        if not check_password_hash(current_user.password_hash, current):
            flash("Current password is incorrect.", "danger")
        elif len(new) < 6:
            flash("New password must be at least 6 characters.", "danger")
        elif new != confirm:
            flash("Passwords do not match.", "danger")
        else:
            current_user.password_hash = generate_password_hash(new)
            db.session.commit()
            log_activity("password_change", module="auth")
            flash("Password updated.", "success")
            return redirect(url_for("dashboard.index"))
    return render_template("auth/change_password.html")
