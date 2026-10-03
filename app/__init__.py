import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()


def create_app(config_name=None):
    if config_name is None:
        env = (os.environ.get("FLASK_ENV") or os.environ.get("VERCEL_ENV") or "development").lower()
        if env in ("production", "prod") or os.environ.get("VERCEL"):
            config_name = "production"
        else:
            config_name = "development"

    from app.config import config_by_name

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        instance_relative_config=True,
    )
    app.config.from_object(config_by_name.get(config_name, config_by_name["default"]))

    # Ensure upload dirs (never crash on read-only FS like Vercel)
    try:
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        for sub in ("rooms", "menu", "qr", "logos", "signatures"):
            os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], sub), exist_ok=True)
    except OSError:
        # Vercel / serverless: use /tmp
        app.config["UPLOAD_FOLDER"] = "/tmp/hotel_hms_uploads"
        try:
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            for sub in ("rooms", "menu", "qr", "logos", "signatures"):
                os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], sub), exist_ok=True)
        except OSError:
            pass

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"
    login_manager.session_protection = "strong"

    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Blueprints
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.rooms import rooms_bp
    from app.routes.bookings import bookings_bp
    from app.routes.menu import menu_bp
    from app.routes.orders import orders_bp
    from app.routes.kitchen import kitchen_bp
    from app.routes.pos import pos_bp
    from app.routes.billing import billing_bp
    from app.routes.staff import staff_bp
    from app.routes.payroll import payroll_bp
    from app.routes.settings import settings_bp
    from app.routes.qr_public import qr_public_bp
    from app.routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(rooms_bp, url_prefix="/rooms")
    app.register_blueprint(bookings_bp, url_prefix="/bookings")
    app.register_blueprint(menu_bp, url_prefix="/menu")
    app.register_blueprint(orders_bp, url_prefix="/orders")
    app.register_blueprint(kitchen_bp, url_prefix="/kitchen")
    app.register_blueprint(pos_bp, url_prefix="/pos")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(staff_bp, url_prefix="/staff")
    app.register_blueprint(payroll_bp, url_prefix="/payroll")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(qr_public_bp)  # /order/<token>
    app.register_blueprint(api_bp, url_prefix="/api")

    # Exempt public QR order API from CSRF where needed (token-based)
    csrf.exempt(app.view_functions.get("qr_public.place_order"))
    csrf.exempt(app.view_functions.get("qr_public.place_order_qr_path"))
    csrf.exempt(app.view_functions.get("pos.checkout"))
    csrf.exempt(app.view_functions.get("pos.close_folio"))
    csrf.exempt(app.view_functions.get("pos.folio_info"))

    @app.before_request
    def maintenance_gate():
        from flask import request as req, render_template_string, session
        ep = (req.endpoint or "")
        if ep.startswith("static") or ep in ("auth.login", "auth.logout", "settings.maintenance"):
            return
        # Allow technical admin (argon) always
        from flask_login import current_user
        try:
            if current_user.is_authenticated and getattr(current_user, "username", "") == "argon":
                return
        except Exception:
            pass
        try:
            from app.models.settings import SystemSetting
            if SystemSetting.get("maintenance_mode") == "1":
                # other staff blocked except login
                if not current_user.is_authenticated:
                    return
                if getattr(current_user, "username", "") != "argon":
                    msg = SystemSetting.get("maintenance_message") or "Maintenance in progress."
                    logo = SystemSetting.get("logo_url") or ""
                    fav = SystemSetting.get("favicon_url") or ""
                    return render_template_string(
                        """<!DOCTYPE html><html><head><title>Maintenance</title>
                        {% if fav %}<link rel="icon" href="{{ fav }}">{% endif %}
                        <style>body{font-family:system-ui;display:flex;min-height:100vh;align-items:center;justify-content:center;background:#0f172a;color:#fff;text-align:center;margin:0;padding:24px}
                        img{max-height:72px;margin-bottom:16px}</style></head><body>
                        {% if logo %}<img src="{{ logo }}" alt="Logo">{% endif %}
                        <div><h1>Under Maintenance</h1><p>{{ msg }}</p>
                        <p style="opacity:.7;margin-top:24px"><a href="{{ url_for('auth.logout') }}" style="color:#93c5fd">Logout</a></p></div>
                        </body></html>""",
                        msg=msg, logo=logo, fav=fav,
                    ), 503
        except Exception:
            pass

    @app.before_request
    def validate_staff_session():
        """Force-logout works by deactivating StaffSession; reject if token inactive."""
        from flask import session, redirect, url_for, request as req, flash
        from flask_login import current_user, logout_user
        if not current_user.is_authenticated:
            return
        ep = req.endpoint or ""
        if ep.startswith("static") or ep in ("auth.login", "auth.logout"):
            return
        if not current_user.is_active:
            logout_user()
            flash("Your account is disabled.", "danger")
            return redirect(url_for("auth.login"))
        token = session.get("staff_session_token")
        from app.models.user import StaffSession
        import secrets
        from datetime import datetime
        if not token:
            # Recover: recreate session token instead of logging out (avoids CSRF loops)
            token = secrets.token_urlsafe(32)
            sess = StaffSession(
                user_id=current_user.id,
                session_token=token,
                ip_address=req.remote_addr,
                user_agent=(req.headers.get("User-Agent") or "")[:512],
                is_active=True,
                status="online",
            )
            db.session.add(sess)
            db.session.commit()
            session["staff_session_token"] = token
            return
        s = StaffSession.query.filter_by(
            session_token=token, user_id=current_user.id
        ).first()
        if s and not s.is_active:
            session.pop("staff_session_token", None)
            logout_user()
            flash("Your session was ended by an administrator. Please login again.", "warning")
            return redirect(url_for("auth.login"))
        if s:
            s.last_activity = datetime.utcnow()
            s.status = "online"
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

    @app.errorhandler(403)

    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    @app.context_processor
    def inject_globals():
        from app.models.settings import BusinessSettings
        from flask_login import current_user

        settings = None
        try:
            settings = BusinessSettings.get_settings()
        except Exception:
            pass
        from app.utils.timeutil import format_npt, now_npt
        app.jinja_env.filters['format_npt'] = format_npt
        return {
            "hotel_settings": settings,
            "current_user": current_user,
            "format_npt": format_npt,
            "now_npt": now_npt,
        }

    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            app.logger.warning("create_all skipped: %s", e)
        try:
            _ensure_hms_schema()
        except Exception:
            pass
        try:
            _ensure_schema_patches()
        except Exception:
            pass
        try:
            _seed_if_empty()
        except Exception as e:
            app.logger.warning("seed skipped: %s", e)
        try:
            _ensure_tech_admin()
        except Exception as e:
            app.logger.warning("tech admin: %s", e)
        try:
            db.session.remove()
            db.engine.dispose()
        except Exception:
            pass

    @app.teardown_appcontext
    def _shutdown_session(exception=None):
        try:
            db.session.remove()
        except Exception:
            pass

    return app


def _ensure_schema_patches():
    """Add columns that models expect but older shared DBs may lack."""
    from sqlalchemy import text
    statements = [
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_email VARCHAR(200)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS booking_ref VARCHAR(32)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS guest_phone VARCHAR(30)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS guest_email VARCHAR(150)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS message TEXT",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS room_type_id INTEGER",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS room_number VARCHAR(20)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS base_price_snapshot NUMERIC(10,2)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS total_nights INTEGER",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS nightly_rates TEXT",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS source VARCHAR(30)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS advance_txn_number VARCHAR(100)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS advance_paid_claimed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_proof_url VARCHAR(500)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS client_ip VARCHAR(64)",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS ip_location VARCHAR(255)",
    ]
    try:
        for sql in statements:
            try:
                db.session.execute(text(sql))
                db.session.commit()
            except Exception:
                db.session.rollback()
                # SQLite fallback without IF NOT EXISTS
                try:
                    if "customer_email" in sql:
                        db.session.execute(text("ALTER TABLE orders ADD COLUMN customer_email VARCHAR(200)"))
                        db.session.commit()
                except Exception:
                    db.session.rollback()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _seed_if_empty():
    """Seed roles, permissions, admin user, defaults when DB is empty."""
    from app.models.user import User, Role, Permission, RolePermission
    from app.models.settings import BusinessSettings, TaxSettings, POSSettings, WorkingHoursSettings
    from app.models.menu import MenuCategory
    from werkzeug.security import generate_password_hash

    # Keep role labels up to date on existing DBs
    waiter = Role.query.filter_by(code="staff").first()
    if waiter and waiter.name != "Waiter":
        waiter.name = "Waiter"
        db.session.commit()

    if Role.query.first():
        return

    # Roles
    roles_data = [
        ("super_admin", "Super Admin"),
        ("admin", "Admin / Manager"),
        ("kitchen", "Kitchen Staff"),
        ("reception", "Reception Staff"),
        ("cashier", "Cashier"),
        ("staff", "Waiter"),
    ]
    roles = {}
    for code, name in roles_data:
        r = Role(code=code, name=name)
        db.session.add(r)
        roles[code] = r
    db.session.flush()

    # Permissions (module.action)
    perm_codes = [
        "dashboard.view",
        "rooms.view", "rooms.add", "rooms.edit", "rooms.delete", "rooms.status", "rooms.qr",
        "bookings.view", "bookings.create", "bookings.edit", "bookings.cancel", "bookings.checkin", "bookings.checkout", "bookings.payment",
        "menu.view", "menu.add", "menu.edit", "menu.delete", "menu.price", "menu.availability", "menu.categories", "menu.image", "menu.website", "menu.qr_vis",
        "orders.view", "orders.details", "orders.accept", "orders.status", "orders.cancel", "orders.qr_manage",
        "kitchen.view", "kitchen.accept", "kitchen.preparing", "kitchen.ready", "kitchen.delivered", "kitchen.completed",
        "pos.open", "pos.create", "pos.discount", "pos.service", "pos.hold", "pos.complete",
        "billing.view", "billing.create", "billing.complete", "billing.print", "billing.reprint", "billing.void", "billing.refund",
        "staff.view", "staff.add", "staff.edit", "staff.disable", "staff.reset_pw", "staff.role", "staff.permissions", "staff.salary",
        "salary.view", "salary.create", "salary.edit", "salary.increment", "salary.deduction", "salary.consumption", "salary.fine", "salary.advance", "salary.payment", "salary.reports",
        "attendance.view", "attendance.approve", "leave.view", "leave.approve", "break.view", "break.approve", "overtime.view", "overtime.approve",
        "settings.view", "settings.business", "settings.tax", "settings.payment", "settings.hotel", "settings.pos", "settings.system",
        "audit.view", "audit.export",
        "sessions.view", "sessions.force_logout",
        "reports.view", "reports.export",
    ]
    perms = {}
    for code in perm_codes:
        p = Permission(code=code, name=code.replace(".", " ").title())
        db.session.add(p)
        perms[code] = p
    db.session.flush()

    # Super admin & admin get all
    for role_code in ("super_admin", "admin"):
        for p in perms.values():
            db.session.add(RolePermission(role_id=roles[role_code].id, permission_id=p.id))

    # Kitchen
    for code in ["dashboard.view", "kitchen.view", "kitchen.accept", "kitchen.preparing", "kitchen.ready", "kitchen.delivered", "kitchen.completed", "orders.view", "orders.details"]:
        if code in perms:
            db.session.add(RolePermission(role_id=roles["kitchen"].id, permission_id=perms[code].id))

    # Reception
    for code in ["dashboard.view", "rooms.view", "rooms.status", "bookings.view", "bookings.create", "bookings.edit", "bookings.checkin", "bookings.checkout", "bookings.payment", "orders.view"]:
        if code in perms:
            db.session.add(RolePermission(role_id=roles["reception"].id, permission_id=perms[code].id))

    # Cashier
    for code in ["dashboard.view", "pos.open", "pos.create", "pos.discount", "pos.service", "pos.hold", "pos.complete", "billing.view", "billing.create", "billing.complete", "billing.print", "billing.reprint", "orders.view", "orders.status"]:
        if code in perms:
            db.session.add(RolePermission(role_id=roles["cashier"].id, permission_id=perms[code].id))

    # Waiter – self service
    for code in ["dashboard.view", "attendance.view", "leave.view", "break.view", "overtime.view", "salary.view"]:
        if code in perms:
            db.session.add(RolePermission(role_id=roles["staff"].id, permission_id=perms[code].id))

    # Default admin user
    admin = User(
        username="admin",
        email="info@hotelgrand.com.np",
        full_name="System Administrator",
        employee_id="HG-EMP-001",
        phone="9816374804",
        password_hash=generate_password_hash("admin123"),
        role_id=roles["super_admin"].id,
        is_active=True,
        department="Management",
    )
    db.session.add(admin)
    # Technical admin for maintenance
    if not User.query.filter_by(username="argon").first():
        tech = User(
            username="argon",
            email="argon@hotelgrand.com.np",
            full_name="Technical Admin",
            is_active=True,
            password_hash=generate_password_hash("argon123"),
            role_id=roles["super_admin"].id,
        )
        db.session.add(tech)

    # Business settings
    bs = BusinessSettings(
        hotel_name="HOTEL GRAND GARDEN",
        business_name="Family Restaurant & Bar",
        address="Urlabari-5, Morang",
        phone="9816374804",
        email="info@hotelgrand.com.np",
        pan="",  # must be set before billing
        vat_number="",
        currency="Rs.",
        check_in_time="12:00",
        check_out_time="11:00",
        prepared_by_text="HOTEL GRAND GARDEN\nFamily Restaurant & Bar",
    )
    db.session.add(bs)

    tax = TaxSettings(vat_rate=13.0, vat_inclusive=True, vat_enabled=True)
    db.session.add(tax)

    pos_s = POSSettings(service_charge_percent=0, default_payment_method="cash")
    db.session.add(pos_s)

    wh = WorkingHoursSettings(
        work_start="10:00",
        work_end="18:00",
        required_daily_hours=8.0,
        break_duration_minutes=60,
        grace_period_minutes=10,
        working_days_per_month=26,
        late_fine_enabled=False,
        early_fine_enabled=False,
        overtime_enabled=True,
        overtime_salary_enabled=True,
        overtime_rate_type="salary_based",
        overtime_multiplier=1.5,
    )
    db.session.add(wh)

    # Default menu categories
    for i, name in enumerate(["Drinks", "Food", "Breakfast", "Lunch", "Dinner"], 1):
        db.session.add(MenuCategory(name=name, sort_order=i, is_active=True))

    db.session.commit()


def _ensure_hms_schema():
    from sqlalchemy import text
    patches = [
        "ALTER TABLE rooms ADD COLUMN IF NOT EXISTS floor VARCHAR(20)",
        "ALTER TABLE rooms ADD COLUMN IF NOT EXISTS show_on_website BOOLEAN DEFAULT FALSE",
        # Do NOT bulk-update all rooms — public-admin rooms must stay True

        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_email VARCHAR(255)",
    ]
    for sql in patches:
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass


def _ensure_tech_admin():
    """Always ensure technical admin argon / argon123 exists."""
    from app.models.user import User, Role
    from werkzeug.security import generate_password_hash
    u = User.query.filter_by(username="argon").first()
    if u:
        return
    role = Role.query.filter_by(code="super_admin").first()
    if not role:
        return
    db.session.add(User(
        username="argon",
        email="argon@hotelgrand.com.np",
        full_name="Technical Admin",
        is_active=True,
        password_hash=generate_password_hash("argon123"),
        role_id=role.id,
    ))
    db.session.commit()
