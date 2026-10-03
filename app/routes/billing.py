from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.billing import Bill
from app.models.order import Order
from app.models.folio import Folio
from app.services.billing_service import create_bill_from_order
from app.services.folio_service import close_folio_and_bill, ensure_room_nights
from app.utils.decorators import permission_required
from app.utils.audit import log_activity
from decimal import Decimal

billing_bp = Blueprint("billing", __name__)


@billing_bp.route("/")
@login_required
@permission_required("billing.view")
def list_bills():
    # Auto-open room folios for active bookings missing one
    try:
        from app.models.booking import Booking
        from app.services.folio_service import get_or_open_folio
        from app.models.room import Room
        active = Booking.query.filter(
            Booking.status.in_(["confirmed", "checked_in", "booked", "pending"])
        ).all()
        for b in active:
            if not b.room_id:
                continue
            existing = Folio.query.filter_by(status="open", source="ROOM", room_id=b.room_id).first()
            if existing:
                continue
            room = db.session.get(Room, b.room_id)
            folio = get_or_open_folio(
                "ROOM",
                room_id=b.room_id,
                customer_name=getattr(b, "guest_name", None) or "Guest",
                user_id=current_user.id,
                room_rate=(room.price if room else 0) or 0,
            )
            try:
                ci = getattr(b, "check_in", None)
                if ci and hasattr(folio, "check_in_date"):
                    folio.check_in_date = ci.date() if hasattr(ci, "date") else ci
            except Exception:
                pass
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    bills = Bill.query.order_by(Bill.created_at.desc()).limit(100).all()
    # Pending: delivered orders without bill, and open folios
    pending_orders = (
        Order.query.filter(
            Order.status.in_(["DELIVERED", "READY", "COMPLETED"]),
            Order.bill == None,  # noqa: E711
        )
        .order_by(Order.created_at.desc())
        .limit(50)
        .all()
    )
    # Filter those not already on closed folio bill
    pending_orders = [o for o in pending_orders if not (o.folio and o.folio.status == "closed")]
    open_folios = Folio.query.filter_by(status="open").order_by(Folio.opened_at.desc()).all()
    for f in open_folios:
        if f.source == "ROOM":
            ensure_room_nights(f, current_user.id)
    open_folios = Folio.query.filter_by(status="open").order_by(Folio.opened_at.desc()).all()
    return render_template(
        "billing/list.html",
        bills=bills,
        pending_orders=pending_orders,
        open_folios=open_folios,
    )


@billing_bp.route("/<int:bill_id>")
@login_required
@permission_required("billing.view")
def view_bill(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        flash("Bill not found.", "danger")
        return redirect(url_for("billing.list_bills"))
    return render_template("billing/view.html", bill=bill, reprint=False)


@billing_bp.route("/<int:bill_id>/print")
@login_required
@permission_required("billing.print")
def print_bill(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        flash("Bill not found.", "danger")
        return redirect(url_for("billing.list_bills"))
    log_activity("bill_print", module="billing", record_id=bill.id)
    return render_template("billing/print.html", bill=bill, reprint=False)


@billing_bp.route("/<int:bill_id>/reprint")
@login_required
@permission_required("billing.reprint")
def reprint_bill(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        flash("Bill not found.", "danger")
        return redirect(url_for("billing.list_bills"))
    log_activity("bill_reprint", module="billing", record_id=bill.id)
    return render_template("billing/print.html", bill=bill, reprint=True)


@billing_bp.route("/from-order/<int:order_id>", methods=["POST"])
@login_required
@permission_required("billing.create")
def bill_from_order(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("orders.list_orders"))
    if order.folio_id and order.folio and order.folio.status == "open":
        # Close whole folio
        try:
            bill = close_folio_and_bill(
                order.folio,
                payment_method=request.form.get("payment_method") or "cash",
                amount_received=request.form.get("amount_received"),
                user=current_user,
            )
            flash(f"Folio closed · Bill {bill.bill_number}", "success")
            return redirect(url_for("billing.print_bill", bill_id=bill.id))
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("billing.list_bills"))
    if order.bill:
        flash("Bill already exists.", "info")
        return redirect(url_for("billing.view_bill", bill_id=order.bill.id))
    try:
        bill = create_bill_from_order(
            order,
            payment_method=request.form.get("payment_method") or "cash",
            amount_received=request.form.get("amount_received"),
            user=current_user,
        )
        flash(f"Bill {bill.bill_number} created.", "success")
        return redirect(url_for("billing.print_bill", bill_id=bill.id))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("orders.detail", oid=order_id))


@billing_bp.route("/folio/<int:folio_id>")
@login_required
@permission_required("billing.view")
def view_folio(folio_id):
    folio = db.session.get(Folio, folio_id)
    if not folio:
        flash("Folio not found.", "danger")
        return redirect(url_for("billing.list_bills"))
    if folio.status == "open" and folio.source == "ROOM":
        ensure_room_nights(folio, current_user.id)
        folio = db.session.get(Folio, folio_id)
    return render_template("billing/folio.html", folio=folio)


@billing_bp.route("/folio/<int:folio_id>/close", methods=["POST"])
@login_required
@permission_required("billing.create")
def close_folio(folio_id):
    folio = db.session.get(Folio, folio_id)
    if not folio or folio.status != "open":
        flash("Open folio not found.", "danger")
        return redirect(url_for("billing.list_bills"))
    try:
        bill = close_folio_and_bill(
            folio,
            payment_method=request.form.get("payment_method") or "cash",
            amount_received=request.form.get("amount_received"),
            user=current_user,
            discount=Decimal(request.form.get("discount") or "0"),
        )
        flash(f"Bill {bill.bill_number} created.", "success")
        return redirect(url_for("billing.print_bill", bill_id=bill.id))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("billing.view_folio", folio_id=folio_id))



def _send_bill_email(bill) -> bool:
    """Email bill to guest (from order/folio customer_email)."""
    if not bill:
        return False
    to_email = None
    try:
        if bill.order and getattr(bill.order, "customer_email", None):
            to_email = bill.order.customer_email
        if not to_email and bill.folio:
            for o in bill.folio.orders or []:
                if getattr(o, "customer_email", None):
                    to_email = o.customer_email
                    break
        if not to_email:
            to_email = getattr(bill, "customer_email", None)
    except Exception:
        pass
    if not to_email:
        return False
    try:
        from app.services.email_service import notify
        class _G:
            email = to_email
            full_name = bill.customer_name or "Guest"
        items_html = ""
        try:
            lines = []
            if bill.order:
                for i in bill.order.items:
                    lines.append(f"<li>{i.item_name} x{i.quantity} — Rs. {i.line_total}</li>")
            if bill.folio:
                for o in bill.folio.orders:
                    if o.status == "CANCELLED":
                        continue
                    if bill.order and o.id == bill.order.id:
                        continue
                    for i in o.items:
                        lines.append(f"<li>{i.item_name} x{i.quantity} — Rs. {i.line_total}</li>")
            if lines:
                items_html = "<ul>" + "".join(lines) + "</ul>"
        except Exception:
            items_html = ""
        notify(
            _G(),
            "bill_receipt",
            bill_number=bill.bill_number,
            total=str(bill.total),
            payment_method=bill.payment_method or "—",
            source=getattr(bill, "source_label", None) or "—",
            items_html=items_html,
        )
        return True
    except Exception:
        return False
