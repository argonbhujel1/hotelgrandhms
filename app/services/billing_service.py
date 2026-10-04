from decimal import Decimal
from app import db
from app.models.billing import Bill, Payment
from app.models.settings import BusinessSettings
from app.utils.vat import money


def create_bill_from_order(order, payment_method="cash", amount_received=None, user=None):
    settings = BusinessSettings.get_settings()
    if not settings.pan or not str(settings.pan).strip():
        raise ValueError("PAN is required in Business Settings before billing. Configure PAN first.")

    total = money(order.total)
    received = money(amount_received if amount_received is not None else total)
    change = money(received - total)
    if change < 0:
        change = Decimal("0.00")

    bill = Bill(
        bill_number=Bill.next_bill_number(),
        order_id=order.id,
        hotel_name=settings.hotel_name,
        business_name=settings.business_name,
        address=settings.address,
        phone=settings.phone,
        pan=settings.pan,
        vat_number=settings.vat_number or None,
        customer_name=order.customer_name or "—",
        order_type=order.source,
        source_label=order.source_label,
        subtotal=order.subtotal,
        discount=order.discount,
        service_charge=order.service_charge,
        price_before_vat=order.price_before_vat,
        vat_amount=order.vat_amount,
        vat_rate=order.vat_rate_at_time,
        total=order.total,
        payment_method=payment_method,
        amount_received=received,
        change_amount=change,
        status="completed",
        generated_by_id=user.id if user else None,
        generated_by_name=user.full_name if user else None,
    )
    db.session.add(bill)
    db.session.flush()

    pay = Payment(
        bill_id=bill.id,
        method=payment_method,
        amount=received,
        created_by_id=user.id if user else None,
    )
    db.session.add(pay)

    if order.status not in ("COMPLETED", "CANCELLED"):
        order.status = "COMPLETED"
        from app.utils.timeutil import npt_now_naive
        order.completed_at = npt_now_naive()

    # Free table if this was a table order
    if order.table_id:
        try:
            from app.models.room import RestaurantTable
            from app.models.order import Order
            active = Order.query.filter(
                Order.table_id == order.table_id,
                Order.id != order.id,
                Order.status.in_(["NEW", "ACCEPTED", "PREPARING", "READY", "DELIVERED"]),
            ).count()
            if active == 0:
                tbl = db.session.get(RestaurantTable, order.table_id)
                if tbl:
                    tbl.status = "available"
        except Exception:
            pass

    db.session.commit()

    try:
        from app.services.email_service import send_email, get_admin_emails
        html = (
            f"<p>Bill <strong>{bill.bill_number}</strong> created.</p>"
            f"<p>Customer: {bill.customer_name or '—'}<br>"
            f"Total: <strong>Rs. {bill.total}</strong><br>Payment: {payment_method}</p>"
        )
        for email in get_admin_emails() or []:
            send_email(email, f"Bill {bill.bill_number}", html, f"Bill {bill.bill_number}")
        if order.customer_email:
            send_email(
                order.customer_email,
                f"Your bill {bill.bill_number} · Hotel Grand",
                html,
                f"Bill {bill.bill_number}",
            )
    except Exception:
        pass
    return bill
