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
