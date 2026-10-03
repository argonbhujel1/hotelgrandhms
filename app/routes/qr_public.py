from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from app import db
from app.models.room import QRCode
from app.models.menu import MenuCategory, MenuItem
from app.models.settings import BusinessSettings
from app.services.order_service import create_order
from app.services.folio_service import get_or_open_folio
from app import csrf

qr_public_bp = Blueprint("qr_public", __name__)


def _order_page(token):
    qr = QRCode.query.filter_by(token=token, is_active=True).first()
    if not qr:
        return render_template("qr/invalid.html"), 404

    label = qr.label
    categories = (
        MenuCategory.query.filter_by(is_active=True)
        .order_by(MenuCategory.sort_order)
        .all()
    )
    items = (
        MenuItem.query.filter_by(is_active=True, is_available=True, show_on_qr=True)
        .order_by(MenuItem.sort_order, MenuItem.name)
        .all()
    )
    if not items:
        items = (
            MenuItem.query.filter_by(is_active=True, is_available=True)
            .order_by(MenuItem.sort_order, MenuItem.name)
            .all()
        )
    settings = BusinessSettings.get_settings()
    return render_template(
        "qr/menu.html",
        qr=qr,
        label=label,
        categories=categories,
        items=items,
        settings=settings,
        token=token,
    )


@qr_public_bp.route("/order/<token>")
def order_page(token):
    return _order_page(token)


@qr_public_bp.route("/qr/order/<token>")
def order_page_qr_path(token):
    """Alias so QR scans open https://hms.hotelgrand.com.np/qr/order/<token>."""
    return _order_page(token)


@qr_public_bp.route("/qr/order")
def order_page_qr_root():
    """
    Landing if someone scans a generic /qr/order URL without token —
    show guidance (token is required).
    """
    return render_template("qr/invalid.html"), 404


def _place_order(token):
    qr = QRCode.query.filter_by(token=token, is_active=True).first()
    if not qr:
        return jsonify({"ok": False, "error": "Invalid or disabled QR code."}), 404

    data = request.get_json(silent=True) or {}
    items_raw = data.get("items") or []
    if not items_raw:
        return jsonify({"ok": False, "error": "Cart is empty."}), 400

    email = (data.get("customer_email") or data.get("email") or "").strip()
    # Email compulsory for room + table QR orders
    if not email:
        return jsonify({"ok": False, "error": "Please enter your email address."}), 400

    items_data = []
    for row in items_raw:
        items_data.append({
            "menu_item_id": int(row["id"]),
            "quantity": int(row.get("qty", 1)),
            "notes": row.get("notes"),
        })

    source = "ROOM" if qr.source_type == "room" else "TABLE"
    try:
        folio = get_or_open_folio(
            source=source,
            room_id=qr.room_id,
            table_id=qr.table_id,
            customer_name=data.get("customer_name"),
        )
        order = create_order(
            source=source,
            items_data=items_data,
            room_id=qr.room_id,
            table_id=qr.table_id,
            customer_name=data.get("customer_name"),
            customer_email=email or None,
            special_instructions=data.get("special_instructions"),
            folio_id=folio.id,
        )
        # Order received email to guest
        try:
            from app.services.email_service import notify
            class _G:
                email = email
                full_name = (data.get("customer_name") or "Guest")
            items_html = "<ul>" + "".join(
                f"<li>Item #{row.get('id')} x{row.get('qty',1)}</li>" for row in items_raw
            ) + "</ul>"
            notify(
                _G(),
                "order_received",
                order_number=order.order_number,
                total=str(order.total),
                source=source,
                items_html=items_html,
            )
            from app.services.email_service import notify_admin
            try:
                from app.services.push_service import notify_roles
                roles = ["kitchen", "admin", "super_admin", "staff"]
                if source == "ROOM":
                    roles.append("reception")
                notify_roles(
                    roles,
                    "🔔 New Room Order" if source == "ROOM" else "🔔 New Order",
                    f"{order.order_number} · Rs. {order.total}",
                    url=f"/orders/{order.id}",
                    tag=f"order-{order.id}",
                )
            except Exception:
                pass
            notify_admin(
                "admin_new_order",
                order_number=order.order_number,
                total=str(order.total),
                source=source,
                guest=email or data.get("customer_name") or "Guest",
            )
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "order_number": order.order_number,
            "total": str(order.total),
            "folio_id": folio.id,
            "message": f"Order {order.order_number} placed successfully!",
        })
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"ok": False, "error": "Something went wrong. Please try again or contact Hotel Grand Garden."}), 500


@qr_public_bp.route("/order/<token>/place", methods=["POST"])
def place_order(token):
    return _place_order(token)


@qr_public_bp.route("/qr/order/<token>/place", methods=["POST"])
def place_order_qr_path(token):
    return _place_order(token)
