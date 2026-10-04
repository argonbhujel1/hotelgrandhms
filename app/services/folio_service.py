from datetime import datetime, date, timedelta
from decimal import Decimal
from app import db
from app.models.folio import Folio, FolioCharge
from app.models.room import Room, RestaurantTable
from app.models.order import Order
from app.models.billing import Bill, Payment
from app.models.settings import BusinessSettings, TaxSettings
from app.utils.vat import money, calc_vat_inclusive


def get_or_open_folio(source, room_id=None, table_id=None, customer_name=None, user_id=None, room_rate=None):
    source = (source or "COUNTER").upper()
    q = Folio.query.filter_by(status="open", source=source)
    if source == "ROOM" and room_id:
        q = q.filter_by(room_id=int(room_id))
        existing = q.first()
        if existing:
            return existing
        room = db.session.get(Room, int(room_id))
        rate = room_rate if room_rate is not None else (room.price if room else 0)
        folio = Folio(
            folio_number=Folio.next_number(),
            source="ROOM",
            room_id=int(room_id),
            customer_name=customer_name,
            status="open",
            opened_by_id=user_id,
            check_in_date=date.today(),
            last_rent_charged_date=date.today(),
            room_rate=money(rate or 0),
        )
        db.session.add(folio)
        db.session.flush()
        # Day 1 room rent
        if folio.room_rate and folio.room_rate > 0:
            db.session.add(FolioCharge(
                folio_id=folio.id,
                charge_type="room_rent",
                description=f"Room rent — {date.today().isoformat()} (Day 1)",
                charge_date=date.today(),
                amount=folio.room_rate,
                created_by_id=user_id,
            ))
        db.session.commit()
        return folio
    if source == "TABLE" and table_id:
        q = q.filter_by(table_id=int(table_id))
        existing = q.first()
        if existing:
            return existing
        folio = Folio(
            folio_number=Folio.next_number(),
            source="TABLE",
            table_id=int(table_id),
            customer_name=customer_name,
            status="open",
            opened_by_id=user_id,
        )
        db.session.add(folio)
        db.session.commit()
        return folio
    # Counter — always new open folio per sale session (or none until checkout)
    folio = Folio(
        folio_number=Folio.next_number(),
        source="COUNTER",
        customer_name=customer_name,
        status="open",
        opened_by_id=user_id,
    )
    db.session.add(folio)
    db.session.commit()
    return folio


def ensure_room_nights(folio, user_id=None):
    """Auto-add room rent for each night until today if guest not checked out."""
    if not folio or folio.source != "ROOM" or folio.status != "open":
        return
    if not folio.check_in_date or not folio.room_rate:
        return
    today = date.today()
    last = folio.last_rent_charged_date or folio.check_in_date
    # Charge for each calendar day after last charged through today
    d = last + timedelta(days=1)
    while d <= today:
        exists = FolioCharge.query.filter_by(
            folio_id=folio.id, charge_type="room_rent", charge_date=d
        ).first()
        if not exists:
            day_num = (d - folio.check_in_date).days + 1
            db.session.add(FolioCharge(
                folio_id=folio.id,
                charge_type="room_rent",
                description=f"Room rent — {d.isoformat()} (Day {day_num})",
                charge_date=d,
                amount=folio.room_rate,
                created_by_id=user_id,
            ))
        folio.last_rent_charged_date = d
        d += timedelta(days=1)
    db.session.commit()


def close_folio_and_bill(folio, payment_method="cash", amount_received=None, user=None, discount=0):
    """Close folio: ensure nights, create aggregated bill, mark orders completed."""
    ensure_room_nights(folio, user.id if user else None)

    settings = BusinessSettings.get_settings()
    pan_value = (settings.pan or "").strip() or "N/A"

    tax = TaxSettings.get_settings()
    vat_rate = money(tax.vat_rate or 13)

    food = money(folio.food_total())
    charges = money(folio.charges_total())
    disc = money(discount or 0)
    inclusive = money(food + charges - disc)
    if inclusive < 0:
        inclusive = money(0)
    before, vat, final = calc_vat_inclusive(inclusive, vat_rate)

    received = money(amount_received if amount_received is not None else final)
    change = money(received - final)
    if change < 0:
        change = money(0)

    # Prefer linking first order if single-order folio
    first_order = next((o for o in folio.orders if o.status != "CANCELLED"), None)

    bill = Bill(
        bill_number=Bill.next_bill_number(),
        order_id=first_order.id if first_order else None,
        folio_id=folio.id,
        hotel_name=settings.hotel_name,
        business_name=settings.business_name,
        address=settings.address,
        phone=settings.phone,
        pan=pan_value,
        vat_number=settings.vat_number or None,
        customer_name=folio.customer_name or (first_order.customer_name if first_order else "—"),
        order_type=folio.source,
        source_label=folio.label,
        subtotal=food + charges,
        discount=disc,
        service_charge=money(0),
        price_before_vat=before,
        vat_amount=vat,
        vat_rate=vat_rate,
        total=final,
        payment_method=payment_method,
        amount_received=received,
        change_amount=change,
        status="completed",
        generated_by_id=user.id if user else None,
        generated_by_name=user.full_name if user else None,
    )
    db.session.add(bill)
    db.session.flush()
    db.session.add(Payment(
        bill_id=bill.id,
        method=payment_method,
        amount=received,
        created_by_id=user.id if user else None,
    ))

    for o in folio.orders:
        if o.status not in ("CANCELLED",):
            o.status = "COMPLETED"
            o.completed_at = npt_now_naive()
            if not o.bill:
                # only attach if no separate bill
                pass

    folio.status = "closed"
    folio.closed_at = npt_now_naive()
    folio.closed_by_id = user.id if user else None

    # Free room/table
    if folio.room_id and folio.room:
        folio.room.status = "available"
    if folio.table_id and folio.table:
        folio.table.status = "available"

    db.session.commit()
    
    # Email bill to customer / admin
    try:
        from app.services.email_service import send_email, get_admin_emails
        html = (
            f"<p>Bill <strong>{bill.bill_number}</strong> has been generated.</p>"
            f"<p>Customer: {bill.customer_name or '—'}<br>"
            f"Total: <strong>Rs. {bill.total}</strong><br>"
            f"Payment: {bill.payment_method}</p>"
        )
        for email in get_admin_emails() or []:
            send_email(email, f"Bill {bill.bill_number}", html, f"Bill {bill.bill_number}")
        cust = getattr(bill, "customer_email", None) or (first_order.customer_email if first_order and getattr(first_order, "customer_email", None) else None)
        if cust:
            send_email(cust, f"Your bill {bill.bill_number} · Hotel Grand", html, f"Bill {bill.bill_number}")
    except Exception:
        pass

    return bill
