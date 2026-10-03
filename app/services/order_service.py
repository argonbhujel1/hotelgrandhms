from decimal import Decimal
from datetime import datetime
from app.utils.timeutil import npt_now_naive
from app import db
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.menu import MenuItem
from app.models.settings import TaxSettings, POSSettings
from app.utils.vat import money, calc_vat_inclusive, line_total


def create_order(
    source,
    items_data,
    room_id=None,
    table_id=None,
    customer_name=None,
    customer_email=None,
    special_instructions=None,
    discount=0,
    service_charge=None,
    created_by_id=None,
    folio_id=None,
):
    """
    items_data: list of {menu_item_id, quantity, notes?}
    Server-side price calculation only.
    """
    tax = TaxSettings.get_settings()
    pos = POSSettings.get_settings()
    vat_rate = money(tax.vat_rate or 13)

    order = Order(
        order_number=Order.next_order_number(),
        source=source.upper(),
        room_id=room_id,
        table_id=table_id,
        folio_id=folio_id,
        customer_name=(customer_name or "").strip() or None,
        customer_email=(customer_email or "").strip() or None,
        special_instructions=special_instructions,
        status="NEW",
        vat_rate_at_time=vat_rate,
        created_by_id=created_by_id,
    )
    db.session.add(order)
    db.session.flush()

    subtotal = Decimal("0.00")
    for row in items_data:
        mi = db.session.get(MenuItem, int(row["menu_item_id"]))
        if not mi or not mi.is_available or not mi.is_active:
            raise ValueError(f"Item unavailable: {row.get('menu_item_id')}")
        qty = max(1, int(row.get("quantity", 1)))
        unit = money(mi.price)
        lt = line_total(unit, qty)
        oi = OrderItem(
            order_id=order.id,
            menu_item_id=mi.id,
            item_name=mi.name,
            unit_price=unit,
            quantity=qty,
            line_total=lt,
            notes=row.get("notes"),
        )
        db.session.add(oi)
        subtotal += lt

    discount = money(discount or 0)
    if service_charge is None:
        sc_pct = money(pos.service_charge_percent or 0)
        service_charge = money(subtotal * sc_pct / Decimal("100"))
    else:
        service_charge = money(service_charge)

    # Inclusive total after discount + service
    inclusive = money(subtotal - discount + service_charge)
    if inclusive < 0:
        inclusive = Decimal("0.00")

    before, vat, final = calc_vat_inclusive(inclusive, vat_rate)

    order.subtotal = subtotal
    order.discount = discount
    order.service_charge = service_charge
    order.price_before_vat = before
    order.vat_amount = vat
    order.total = final

    hist = OrderStatusHistory(order_id=order.id, status="NEW", changed_by_id=created_by_id)
    db.session.add(hist)
    db.session.commit()
    return order


def change_order_status(order, new_status, user_id=None, note=None):
    allowed = {
        "NEW": ["ACCEPTED", "CANCELLED"],
        "ACCEPTED": ["PREPARING", "CANCELLED"],
        "PREPARING": ["READY", "CANCELLED"],
        "READY": ["DELIVERED", "CANCELLED"],
        "DELIVERED": ["COMPLETED"],
        "COMPLETED": [],
        "CANCELLED": [],
    }
    current = order.status
    if new_status not in allowed.get(current, []):
        # Allow admin force for simplicity in some transitions
        if new_status not in ("ACCEPTED", "PREPARING", "READY", "DELIVERED", "COMPLETED", "CANCELLED"):
            raise ValueError(f"Invalid status transition {current} → {new_status}")

    order.status = new_status
    order.updated_at = npt_now_naive()
    if new_status == "COMPLETED":
        order.completed_at = npt_now_naive()
    db.session.add(
        OrderStatusHistory(
            order_id=order.id,
            status=new_status,
            changed_by_id=user_id,
            note=note,
        )
    )
    db.session.commit()
    # Web push by role
    try:
        from app.services.push_service import notify_roles, notify_customer_email
        title_map = {
            "ACCEPTED": ("🔔 Order Accepted", ["staff", "admin", "super_admin", "kitchen"]),
            "PREPARING": ("🔔 Preparing", ["staff", "kitchen", "admin", "super_admin"]),
            "READY": ("🔔 Ready", ["staff", "kitchen", "reception", "admin", "super_admin"]),
            "DELIVERED": ("🔔 Served", ["staff", "admin", "super_admin"]),
            "COMPLETED": ("🔔 Bill/Payment update", ["reception", "admin", "super_admin", "cashier"]),
            "CANCELLED": ("🔔 Order Cancelled", ["kitchen", "staff", "admin", "super_admin"]),
        }
        if new_status in title_map:
            title, roles = title_map[new_status]
            body = f"{order.order_number} · Rs. {order.total}"
            notify_roles(roles, title, body, url=f"/orders/{order.id}", tag=f"order-{order.id}-{new_status}")
            if order.customer_email:
                notify_customer_email(
                    order.customer_email,
                    title,
                    body,
                    url="/",
                    tag=f"cust-{order.id}-{new_status}",
                )
        if new_status == "NEW" or (note and "special" in (note or "").lower()):
            notify_roles(
                ["kitchen", "staff", "admin", "super_admin"],
                "🔔 Special Request" if note else "🔔 New Order",
                f"{order.order_number}",
                url=f"/orders/{order.id}",
                tag=f"order-{order.id}",
            )
    except Exception:
        pass
    return order
