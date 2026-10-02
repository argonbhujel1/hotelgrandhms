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
        from datetime import datetime
        order.completed_at = datetime.utcnow()

    db.session.commit()
    return bill
