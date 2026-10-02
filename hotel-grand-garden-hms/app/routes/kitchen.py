from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.order import Order
from app.services.order_service import change_order_status
from app.utils.decorators import permission_required
from app.utils.audit import log_activity

kitchen_bp = Blueprint("kitchen", __name__)


@kitchen_bp.route("/")
@login_required
@permission_required("kitchen.view")
def index():
    active = Order.query.filter(
        Order.status.in_(["NEW", "ACCEPTED", "PREPARING", "READY"])
    ).order_by(Order.created_at.asc()).all()
    return render_template("kitchen/index.html", orders=active)


@kitchen_bp.route("/<int:oid>/action", methods=["POST"])
@login_required
@permission_required("kitchen.view")
def action(oid):
    order = db.session.get(Order, oid)
    if not order:
        flash("Not found.", "danger")
        return redirect(url_for("kitchen.index"))
    action = request.form.get("action")
    mapping = {
        "accept": ("ACCEPTED", "kitchen.accept"),
        "preparing": ("PREPARING", "kitchen.preparing"),
        "ready": ("READY", "kitchen.ready"),
        "delivered": ("DELIVERED", "kitchen.delivered"),
        "completed": ("COMPLETED", "kitchen.completed"),
    }
    if action not in mapping:
        flash("Invalid action.", "danger")
        return redirect(url_for("kitchen.index"))
    status, perm = mapping[action]
    if not current_user.has_permission(perm) and current_user.role_code not in ("super_admin", "admin", "kitchen"):
        flash("Not authorized for this action.", "danger")
        return redirect(url_for("kitchen.index"))
    try:
        change_order_status(order, status, user_id=current_user.id)
        log_activity(f"kitchen_{action}", module="kitchen", record_id=order.id)
        flash(f"{order.order_number} → {status}", "success")
    except ValueError as e:
        flash(str(e), "warning")
    return redirect(url_for("kitchen.index"))
