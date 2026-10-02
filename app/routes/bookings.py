from datetime import datetime
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.booking import Booking
from app.models.room import Room
from app.utils.decorators import permission_required
from app.utils.audit import log_activity
from app.services.folio_service import get_or_open_folio

bookings_bp = Blueprint("bookings", __name__)


@bookings_bp.route("/")
@login_required
@permission_required("bookings.view")
def list_bookings():
    status = request.args.get("status", "")
    q = Booking.query
    if status:
        q = q.filter_by(status=status)
    bookings = q.order_by(Booking.created_at.desc()).limit(200).all()
    return render_template("bookings/list.html", bookings=bookings, status=status)


@bookings_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required("bookings.create")
def add_booking():
    rooms = Room.query.filter(Room.is_active == True, Room.status.in_(["available", "reserved"])).order_by(Room.number).all()
    if request.method == "POST":
        room_id = int(request.form.get("room_id"))
        check_in = datetime.strptime(request.form.get("check_in"), "%Y-%m-%dT%H:%M")
        check_out = datetime.strptime(request.form.get("check_out"), "%Y-%m-%dT%H:%M")
        advance = Decimal(request.form.get("advance_amount") or "0")
        if advance <= 0:
            flash("Advance payment is mandatory.", "danger")
            return render_template("bookings/form.html", booking=None, rooms=rooms)
        b = Booking(
            guest_name=request.form.get("guest_name"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            room_id=room_id,
            check_in=check_in,
            check_out=check_out,
            num_guests=int(request.form.get("num_guests") or 1),
            advance_amount=advance,
            total_amount=Decimal(request.form.get("total_amount") or "0"),
            status=request.form.get("status") or "confirmed",
            notes=request.form.get("notes"),
            created_by_id=current_user.id,
        )
        room = db.session.get(Room, room_id)
        if room and b.status in ("confirmed", "checked_in"):
            room.status = "occupied" if b.status == "checked_in" else "reserved"
        db.session.add(b)
        db.session.commit()
        log_activity("create_booking", module="bookings", record_id=b.id)
        try:
            from app.services.email_service import notify_admin
            notify_admin(
                "admin_new_booking",
                ref=getattr(b, "booking_ref", None) or b.id,
                guest=b.guest_name or "Guest",
                check_in=str(b.check_in),
                check_out=str(b.check_out),
                room=str(b.room_id),
            )
        except Exception:
            pass
        flash("Booking created.", "success")
        return redirect(url_for("bookings.list_bookings"))
    return render_template("bookings/form.html", booking=None, rooms=rooms)


@bookings_bp.route("/<int:bid>/status", methods=["POST"])
@login_required
@permission_required("bookings.edit")
def update_status(bid):
    b = db.session.get(Booking, bid)
    if not b:
        flash("Not found.", "danger")
        return redirect(url_for("bookings.list_bookings"))
    new_status = request.form.get("status")
    b.status = new_status
    room = b.room
    if new_status == "checked_in" and room:
        room.status = "occupied"
        get_or_open_folio(
            source="ROOM",
            room_id=room.id,
            customer_name=b.guest_name,
            user_id=current_user.id,
            room_rate=room.price,
        )
    elif new_status == "checked_out" and room:
        room.status = "available"
        from app.models.folio import Folio
        from app.services.folio_service import close_folio_and_bill
        folio = Folio.query.filter_by(status="open", source="ROOM", room_id=room.id).first()
        if folio:
            try:
                close_folio_and_bill(folio, payment_method="cash", user=current_user)
            except ValueError:
                pass  # PAN missing etc. — leave open for billing desk
    elif new_status == "cancelled" and room and room.status == "reserved":
        room.status = "available"
    db.session.commit()
    log_activity("booking_status", module="bookings", record_id=b.id, details=new_status)
    try:
        from app.services.email_service import send_email
        guest = getattr(b, "email", None) or ""
        if guest:
            subj = f"Booking {new_status} — #{b.id}"
            html = f"<p>Dear {b.guest_name},</p><p>Your booking status is now <strong>{new_status}</strong>.</p><p>Check-in: {b.check_in}<br>Check-out: {b.check_out}</p><p>— Hotel Grand Garden</p>"
            send_email(guest, subj, html, f"Booking {b.id}: {new_status}")
    except Exception:
        pass
    flash("Status updated.", "success")
    return redirect(url_for("bookings.list_bookings"))
