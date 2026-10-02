from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.order import Order
from app.services.order_service import change_order_status, create_order
from app.models.menu import MenuItem, MenuCategory
from app.models.room import Room, RestaurantTable
from decimal import Decimal
from app.utils.decorators import permission_required
from app.utils.audit import log_activity
from datetime import date
from sqlalchemy import func

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/")
@login_required
@permission_required("orders.view")
def list_orders():
    status = request.args.get("status", "")
    source = request.args.get("source", "")
    q = Order.query
    if status:
        q = q.filter_by(status=status)
    if source:
        q = q.filter_by(source=source)
    orders = q.order_by(Order.created_at.desc()).limit(150).all()

    today = date.today()
    cards = {
        "total": Order.query.filter(func.date(Order.created_at) == today).count(),
        "new": Order.query.filter_by(status="NEW").count(),
        "preparing": Order.query.filter(Order.status.in_(["ACCEPTED", "PREPARING"])).count(),
        "ready": Order.query.filter_by(status="READY").count(),
        "delivered": Order.query.filter_by(status="DELIVERED").count(),
        "completed": Order.query.filter_by(status="COMPLETED").count(),
        "cancelled": Order.query.filter_by(status="CANCELLED").count(),
    }
    return render_template("orders/list.html", orders=orders, cards=cards, status=status, source=source)


@orders_bp.route("/<int:oid>")
@login_required
@permission_required("orders.details")
def detail(oid):
    order = db.session.get(Order, oid)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("orders.list_orders"))
    return render_template("orders/detail.html", order=order)


@orders_bp.route("/<int:oid>/status", methods=["POST"])
@login_required
@permission_required("orders.status")
def set_status(oid):
    order = db.session.get(Order, oid)
    if not order:
        flash("Not found.", "danger")
        return redirect(url_for("orders.list_orders"))
    new_status = request.form.get("status")
    try:
        change_order_status(order, new_status, user_id=current_user.id)
        log_activity("order_status", module="orders", record_id=order.id, details=new_status)
        flash(f"Order {order.order_number} → {new_status}", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(request.referrer or url_for("orders.list_orders"))

@orders_bp.route("/manual", methods=["GET", "POST"])
@login_required
@permission_required("orders.accept")
def manual_add():
    """Admin/staff manual order entry (same as POS without immediate bill)."""
    categories = MenuCategory.query.filter_by(is_active=True).order_by(MenuCategory.sort_order).all()
    items = MenuItem.query.filter_by(is_active=True, is_available=True).all()
    rooms = Room.query.filter_by(is_active=True).order_by(Room.number).all()
    tables = RestaurantTable.query.filter_by(is_active=True).order_by(RestaurantTable.number).all()
    if request.method == "POST":
        source = (request.form.get("source") or "COUNTER").upper()
        room_id = request.form.get("room_id") or None
        table_id = request.form.get("table_id") or None
        if room_id:
            room_id = int(room_id)
            source = "ROOM"
        if table_id:
            table_id = int(table_id)
            source = "TABLE"
        item_ids = request.form.getlist("item_id")
        qtys = request.form.getlist("qty")
        items_data = []
        for iid, qty in zip(item_ids, qtys):
            if int(qty) > 0:
                items_data.append({"menu_item_id": int(iid), "quantity": int(qty)})
        if not items_data:
            flash("Select at least one item.", "danger")
            return render_template("orders/manual.html", categories=categories, items=items, rooms=rooms, tables=tables)
        try:
            order = create_order(
                source=source,
                items_data=items_data,
                room_id=room_id,
                table_id=table_id,
                customer_name=request.form.get("customer_name"),
                special_instructions=request.form.get("notes"),
                created_by_id=current_user.id,
            )
            log_activity("manual_order", module="orders", record_id=order.id)
            flash(f"Order {order.order_number} created.", "success")
            return redirect(url_for("orders.detail", oid=order.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("orders/manual.html", categories=categories, items=items, rooms=rooms, tables=tables)
