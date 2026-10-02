from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.settings import BusinessSettings, TaxSettings, POSSettings, WorkingHoursSettings
from app.models.billing import PaymentMethod
from app.utils.decorators import permission_required
from app.utils.audit import log_audit
from app.utils.uploads import save_upload
from app.utils.cloudinary_upload import upload_media
from decimal import Decimal

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/")
@login_required
@permission_required("settings.view")
def index():
    return render_template("settings/index.html")


@settings_bp.route("/business", methods=["GET", "POST"])
@login_required
@permission_required("settings.business")
def business():
    s = BusinessSettings.get_settings()
    if request.method == "POST":
        old_pan = s.pan
        s.hotel_name = request.form.get("hotel_name") or s.hotel_name
        s.business_name = request.form.get("business_name") or s.business_name
        s.address = request.form.get("address") or s.address
        s.phone = request.form.get("phone") or s.phone
        s.email = request.form.get("email")
        s.pan = (request.form.get("pan") or "").strip()
        s.vat_number = (request.form.get("vat_number") or "").strip()
        s.currency = request.form.get("currency") or "Rs."
        s.check_in_time = request.form.get("check_in_time") or "12:00"
        s.check_out_time = request.form.get("check_out_time") or "11:00"
        s.prepared_by_text = request.form.get("prepared_by_text") or s.prepared_by_text

        for field, sub in (
            ("logo", "logos"),
            ("favicon", "logos"),
            ("signature", "signatures"),
        ):
            f = request.files.get(field)
            if f and f.filename:
                try:
                    media = upload_media(f, sub)
                    if media and media.get("url"):
                        # store absolute URL in path fields for simplicity on Vercel
                        path = media["url"]
                    elif media and media.get("local_path"):
                        path = media["local_path"]
                    else:
                        path = save_upload(f, sub)
                    if field == "logo":
                        s.logo_path = path
                    elif field == "favicon":
                        s.favicon_path = path
                    else:
                        s.signature_path = path
                except Exception as e:
                    flash(str(e), "danger")
                    return render_template("settings/business.html", s=s)

        db.session.commit()
        if old_pan != s.pan:
            log_audit("update_pan", module="settings", previous=old_pan, new=s.pan)
        flash("Business settings saved (including logo/favicon if uploaded).", "success")
        return redirect(url_for("settings.business"))
    return render_template("settings/business.html", s=s)


@settings_bp.route("/tax", methods=["GET", "POST"])
@login_required
@permission_required("settings.tax")
def tax():
    s = TaxSettings.get_settings()
    if request.method == "POST":
        s.vat_rate = Decimal(request.form.get("vat_rate") or "13")
        s.vat_inclusive = bool(request.form.get("vat_inclusive"))
        s.vat_enabled = True
        db.session.commit()
        flash("Tax settings saved. VAT remains compulsory.", "success")
        return redirect(url_for("settings.tax"))
    return render_template("settings/tax.html", s=s)


@settings_bp.route("/working-hours", methods=["GET", "POST"])
@login_required
@permission_required("settings.system")
def working_hours():
    s = WorkingHoursSettings.get_settings()
    if request.method == "POST":
        s.work_start = request.form.get("work_start") or s.work_start
        s.work_end = request.form.get("work_end") or s.work_end
        s.required_daily_hours = Decimal(request.form.get("required_daily_hours") or "8")
        s.grace_period_minutes = int(request.form.get("grace_period_minutes") or 10)
        s.working_days_per_month = int(request.form.get("working_days_per_month") or 26)
        s.late_fine_enabled = bool(request.form.get("late_fine_enabled"))
        s.early_fine_enabled = bool(request.form.get("early_fine_enabled"))
        s.overtime_enabled = bool(request.form.get("overtime_enabled"))
        s.overtime_salary_enabled = bool(request.form.get("overtime_salary_enabled"))
        s.overtime_multiplier = Decimal(request.form.get("overtime_multiplier") or "1.5")
        db.session.commit()
        flash("Working hours settings saved.", "success")
        return redirect(url_for("settings.working_hours"))
    return render_template("settings/working_hours.html", s=s)


@settings_bp.route("/payment-methods", methods=["GET", "POST"])
@login_required
@permission_required("settings.payment")
def payment_methods():
    methods = PaymentMethod.query.order_by(PaymentMethod.sort_order).all()
    if request.method == "POST" and request.form.get("name"):
        db.session.add(PaymentMethod(
            name=request.form.get("name"),
            code=(request.form.get("code") or request.form.get("name")).lower().replace(" ", "_"),
            description=request.form.get("description"),
            is_active=True,
        ))
        db.session.commit()
        flash("Payment method added.", "success")
        return redirect(url_for("settings.payment_methods"))
    if not methods:
        for name, code in [("Cash", "cash"), ("QR Payment", "qr"), ("Card", "card"), ("Other", "other")]:
            db.session.add(PaymentMethod(name=name, code=code, is_active=True))
        db.session.commit()
        methods = PaymentMethod.query.order_by(PaymentMethod.sort_order).all()
    return render_template("settings/payment_methods.html", methods=methods)


@settings_bp.route("/payment-methods/<int:mid>/toggle", methods=["POST"])
@login_required
@permission_required("settings.payment")
def toggle_payment_method(mid):
    m = db.session.get(PaymentMethod, mid)
    if m:
        m.is_active = not m.is_active
        db.session.commit()
        flash(f"{m.name} {'enabled' if m.is_active else 'disabled'}.", "success")
    return redirect(url_for("settings.payment_methods"))


@settings_bp.route("/payment-methods/<int:mid>/edit", methods=["POST"])
@login_required
@permission_required("settings.payment")
def edit_payment_method(mid):
    m = db.session.get(PaymentMethod, mid)
    if m:
        m.name = request.form.get("name") or m.name
        m.description = request.form.get("description")
        db.session.commit()
        flash("Payment method updated.", "success")
    return redirect(url_for("settings.payment_methods"))



@settings_bp.route("/clear-data", methods=["GET", "POST"])
@login_required
@permission_required("settings.business")
def clear_data():
    """Danger zone: wipe orders, bills, folios, bookings (not staff/menu/rooms)."""
    if getattr(current_user, "role_code", None) not in ("super_admin", "admin") and not getattr(current_user, "is_admin", False):
        flash("Only admin can clear operational data.", "danger")
        return redirect(url_for("settings.index"))
    if request.method == "POST":
        confirm = (request.form.get("confirm") or "").strip().upper()
        if confirm != "CLEAR":
            flash('Type CLEAR to confirm.', "danger")
            return render_template("settings/clear_data.html")
        from sqlalchemy import text
        try:
            # Order matters for FKs
            tables = [
                "order_status_history",
                "order_items",
                "orders",
                "folio_charges",
                "bills",
                "folios",
                "bookings",
            ]
            for tbl in tables:
                try:
                    db.session.execute(text(f"DELETE FROM {tbl}"))
                except Exception:
                    db.session.rollback()
                    try:
                        db.session.execute(text(f"TRUNCATE TABLE {tbl} CASCADE"))
                    except Exception:
                        db.session.rollback()
            db.session.commit()
            log_audit("clear_operational_data", module="settings")
            flash("All orders, bills, folios and bookings cleared.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Clear failed: {e}", "danger")
        return redirect(url_for("settings.clear_data"))
    return render_template("settings/clear_data.html")



@settings_bp.route("/maintenance", methods=["GET", "POST"])
@login_required
@permission_required("settings.system")
def maintenance():
    from app.models.settings import SystemSetting
    if request.method == "POST":
        enabled = request.form.get("maintenance_mode") in ("1", "on", "true", "True")
        SystemSetting.set("maintenance_mode", "1" if enabled else "0")
        SystemSetting.set("maintenance_message", (request.form.get("maintenance_message") or "").strip())
        # logo / favicon upload via local or URL
        logo = request.form.get("logo_url", "").strip()
        fav = request.form.get("favicon_url", "").strip()
        f = request.files.get("logo_file")
        if f and f.filename:
            try:
                from app.utils.uploads import save_upload
                logo = save_upload(f, "logos")
            except Exception:
                pass
        f2 = request.files.get("favicon_file")
        if f2 and f2.filename:
            try:
                from app.utils.uploads import save_upload
                fav = save_upload(f2, "logos")
            except Exception:
                pass
        if logo:
            SystemSetting.set("logo_url", logo)
        if fav:
            SystemSetting.set("favicon_url", fav)
        flash("Maintenance settings saved.", "success")
        return redirect(url_for("settings.maintenance"))
    return render_template(
        "settings/maintenance.html",
        maintenance_mode=SystemSetting.get("maintenance_mode") == "1",
        maintenance_message=SystemSetting.get("maintenance_message") or "We are under maintenance. Please check back soon.",
        logo_url=SystemSetting.get("logo_url") or "",
        favicon_url=SystemSetting.get("favicon_url") or "",
    )
