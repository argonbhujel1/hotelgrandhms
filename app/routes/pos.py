from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.menu import MenuCategory, MenuItem
from app.models.room import Room, RestaurantTable
from app.models.folio import Folio
from app.services.order_service import create_order
from app.services.folio_service import get_or_open_folio, close_folio_and_bill, ensure_room_nights
from app.utils.decorators import permission_required
from app.utils.audit import log_activity
from decimal import Decimal

pos_bp = Blueprint("pos", __name__)


@pos_bp.route("/")
@login_required
@permission_required("pos.open")
def index():
    categories = MenuCategory.query.filter_by(is_active=True).order_by(MenuCategory.sort_order).all()
    items = MenuItem.query.filter_by(is_active=True, is_available=True).order_by(MenuItem.sort_order, MenuItem.name).all()
    if not items:
        # Fallback: any active items (help when availability flag was left off)
        items = MenuItem.query.filter_by(is_active=True).order_by(MenuItem.sort_order, MenuItem.name).all()
    rooms = Room.query.filter_by(is_active=True).order_by(Room.number).all()
    tables = RestaurantTable.query.filter_by(is_active=True).order_by(RestaurantTable.number).all()
    open_folios = Folio.query.filter_by(status="open").all()
    folio_map = {}
    for f in open_folios:
        if f.room_id:
            folio_map[f"room-{f.room_id}"] = {
                "id": f.id,
                "number": f.folio_number,
                "total": str(f.grand_total()),
                "orders": len([o for o in f.orders if o.status != "CANCELLED"]),
            }
        if f.table_id:
            folio_map[f"table-{f.table_id}"] = {
                "id": f.id,
                "number": f.folio_number,
                "total": str(f.grand_total()),
                "orders": len([o for o in f.orders if o.status != "CANCELLED"]),
            }
    return render_template(
        "pos/index.html",
        categories=categories,
        items=items,
        rooms=rooms,
        tables=tables,
        folio_map=folio_map,
    )


@pos_bp.route("/folio-info")
@login_required
@permission_required("pos.open")
def folio_info():
    source = (request.args.get("source") or "").upper()
    room_id = request.args.get("room_id")
    table_id = request.args.get("table_id")
    folio = None
    if source == "ROOM" and room_id:
        folio = Folio.query.filter_by(status="open", source="ROOM", room_id=int(room_id)).first()
        if folio:
            ensure_room_nights(folio, current_user.id)
            folio = db.session.get(Folio, folio.id)
    elif source == "TABLE" and table_id:
        folio = Folio.query.filter_by(status="open", source="TABLE", table_id=int(table_id)).first()
    if not folio:
        return jsonify({"ok": True, "open": False})
    orders = [
        {
            "number": o.order_number,
            "status": o.status,
            "total": str(o.total),
            "items": [{"name": i.item_name, "qty": i.quantity} for i in o.items],
        }
        for o in folio.orders
        if o.status != "CANCELLED"
    ]
    charges = [
        {"desc": c.description, "amount": str(c.amount), "date": c.charge_date.isoformat() if c.charge_date else ""}
        for c in folio.charges
    ]
    return jsonify({
        "ok": True,
        "open": True,
        "folio_id": folio.id,
        "folio_number": folio.folio_number,
        "customer": folio.customer_name,
        "orders": orders,
        "charges": charges,
        "food_total": str(folio.food_total()),
        "charges_total": str(folio.charges_total()),
        "grand_total": str(folio.grand_total()),
    })


@pos_bp.route("/checkout", methods=["POST"])
@login_required
@permission_required("pos.complete")
def checkout():
    data = request.get_json(silent=True) or {}
    source = (data.get("source") or "COUNTER").upper()
    room_id = data.get("room_id") or None
    table_id = data.get("table_id") or None
    if room_id:
        room_id = int(room_id)
        source = "ROOM"
    if table_id:
        table_id = int(table_id)
        source = "TABLE"

    items_raw = data.get("items") or []
    if not items_raw:
        return jsonify({"ok": False, "error": "Cart is empty"}), 400

    items_data = [{"menu_item_id": int(row["id"]), "quantity": int(row.get("qty", 1)), "notes": row.get("notes")} for row in items_raw]
    close_bill = bool(data.get("close_bill"))
    payment_method = data.get("payment_method") or "cash"
    amount_received = data.get("amount_received")
    customer_email = (data.get("customer_email") or data.get("email") or "").strip()
    # Counter: email required from staff. Room/Table: use QR guest email if not provided.
    if source == "COUNTER" and not customer_email:
        return jsonify({"ok": False, "error": "Customer email is required for counter sales."}), 400
    if source in ("ROOM", "TABLE") and not customer_email:
        from app.models.order import Order
        q = Order.query.filter(Order.status != "CANCELLED")
        if room_id:
            q = q.filter_by(room_id=room_id)
        if table_id:
            q = q.filter_by(table_id=table_id)
        prev = q.order_by(Order.id.desc()).first()
        if prev and prev.customer_email:
            customer_email = prev.customer_email

    try:
        folio = get_or_open_folio(
            source=source,
            room_id=room_id,
            table_id=table_id,
            customer_name=data.get("customer_name"),
            user_id=current_user.id,
        )
        order = create_order(
            source=source,
            items_data=items_data,
            room_id=room_id,
            table_id=table_id,
            customer_name=data.get("customer_name"),
            customer_email=customer_email or None,
            special_instructions=data.get("notes"),
            discount=Decimal(str(data.get("discount") or 0)),
            created_by_id=current_user.id,
            folio_id=folio.id,
        )
        # Mark room/table occupied
        if room_id:
            room = db.session.get(Room, room_id)
            if room:
                room.status = "occupied"
                db.session.commit()
        if table_id:
            table = db.session.get(RestaurantTable, table_id)
            if table:
                table.status = "occupied"
                db.session.commit()

        bill_id = None
        bill_number = None
        if close_bill or source == "COUNTER":
            bill = close_folio_and_bill(
                folio,
                payment_method=payment_method,
                amount_received=Decimal(str(amount_received)) if amount_received else None,
                user=current_user,
                discount=Decimal(str(data.get("discount") or 0)),
            )
            bill_id = bill.id
            bill_number = bill.bill_number

        if customer_email:
            try:
                from app.services.email_service import notify
                class _G:
                    email = customer_email
                    full_name = (data.get("customer_name") or "Guest")
                notify(
                    _G(),
                    "order_received",
                    order_number=order.order_number,
                    total=str(order.total),
                    source=source,
                    items_html="",
                )
            except Exception:
                pass
        log_activity("pos_checkout", module="pos", record_id=order.id)
        return jsonify({
            "ok": True,
            "order_number": order.order_number,
            "folio_number": folio.folio_number,
            "folio_id": folio.id,
            "bill_number": bill_number,
            "bill_id": bill_id,
            "total": str(order.total),
            "folio_total": str(folio.grand_total()),
            "billed": bool(bill_id),
        })
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"ok": False, "error": "Something went wrong. Please try again."}), 500


@pos_bp.route("/close-folio", methods=["POST"])
@login_required
@permission_required("pos.complete")
def close_folio():
    data = request.get_json(silent=True) or {}
    folio_id = data.get("folio_id")
    folio = db.session.get(Folio, int(folio_id)) if folio_id else None
    if not folio or folio.status != "open":
        return jsonify({"ok": False, "error": "Open folio not found"}), 404
    try:
        email = (data.get("customer_email") or data.get("email") or "").strip()
        if not email:
            for o in reversed(list(folio.orders or [])):
                if getattr(o, "customer_email", None):
                    email = o.customer_email
                    break
        # Room/Table may still miss email if QR order had none — still allow close but skip mail
        bill = close_folio_and_bill(
            folio,
            payment_method=data.get("payment_method") or "cash",
            amount_received=Decimal(str(data["amount_received"])) if data.get("amount_received") else None,
            user=current_user,
            discount=Decimal(str(data.get("discount") or 0)),
        )
        log_activity("close_folio", module="pos", record_id=folio.id)
        return jsonify({"ok": True, "bill_id": bill.id, "bill_number": bill.bill_number, "total": str(bill.total)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
