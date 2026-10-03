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

def _as_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    return v


def rooms_free_for_range(check_in, check_out, exclude_booking_id=None):
    """Rooms not blocked by an overlapping active booking (website or HMS)."""
    busy = set()
    active = Booking.query.filter(
        Booking.status.in_(["pending", "confirmed", "checked_in", "booked", "reserved"])
    ).all()
    ci = _as_dt(check_in)
    co = _as_dt(check_out)
    for b in active:
        if exclude_booking_id and b.id == exclude_booking_id:
            continue
        if not b.room_id:
            continue
        b_ci, b_co = _as_dt(b.check_in), _as_dt(b.check_out)
        if not b_ci or not b_co:
            # no dates — treat room as held if status is active
            busy.add(b.room_id)
            continue
        # normalize date-only comparisons
        try:
            a0 = b_ci.date() if hasattr(b_ci, "date") else b_ci
            a1 = b_co.date() if hasattr(b_co, "date") else b_co
            c0 = ci.date() if hasattr(ci, "date") else ci
            c1 = co.date() if hasattr(co, "date") else co
            if a0 < c1 and a1 > c0:
                busy.add(b.room_id)
        except Exception:
            busy.add(b.room_id)
    q = Room.query.filter(Room.is_active == True).order_by(Room.number)
    rooms = []
    for r in q.all():
        st = (r.status or "available").lower()
        if st in ("maintenance", "disabled", "out_of_order"):
            continue
        if r.id in busy:
            continue
        rooms.append(r)
    return rooms




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
    # Default list: free for next 30 days window starting now (no website double-book)
    from datetime import timedelta
    _now = datetime.now()
    rooms = rooms_free_for_range(_now, _now + timedelta(days=1))
    if request.method == "POST":
        room_id = int(request.form.get("room_id"))
        check_in = datetime.strptime(request.form.get("check_in"), "%Y-%m-%dT%H:%M")
        check_out = datetime.strptime(request.form.get("check_out"), "%Y-%m-%dT%H:%M")
        # Recompute free rooms for selected dates
        rooms = rooms_free_for_range(check_in, check_out)
        advance = Decimal(request.form.get("advance_amount") or "0")
        if advance <= 0:
            flash("Advance payment is mandatory.", "danger")
            return render_template("bookings/form.html", booking=None, rooms=rooms)
        # Block if room already booked on website/HMS for these dates
        if room_id not in [r.id for r in rooms]:
            flash("This room is already booked for those dates (website or HMS). Choose another room or dates.", "danger")
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
        db.session.flush()
        folio_id = None
        try:
            from app.services.folio_service import get_or_open_folio
            folio = get_or_open_folio(
                "ROOM",
                room_id=room_id,
                customer_name=b.guest_name,
                user_id=current_user.id,
                room_rate=(room.price if room else 0) or 0,
            )
            try:
                folio.check_in_date = b.check_in.date() if hasattr(b.check_in, "date") else b.check_in
            except Exception:
                pass
            try:
                folio.check_out_date = b.check_out.date() if hasattr(b.check_out, "date") else b.check_out
            except Exception:
                pass
            folio_id = folio.id
        except Exception as fe:
            from flask import current_app
            current_app.logger.warning("folio open on booking: %s", fe)
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
        if folio_id:
            flash("Booking created — room folio open in Billing (orders auto-add until Print bill).", "success")
            return redirect(url_for("billing.view_folio", folio_id=folio_id))
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
        # Housekeeping: room becomes dirty after checkout
        room.status = "dirty"
        try:
            from app.services.push_service import notify_roles
            notify_roles(
                ["housekeeping", "admin", "super_admin", "reception"],
                "🔔 Room checkout — Dirty",
                f"Room {room.number} checked out. Assign cleaning task.",
                url="/housekeeping/assign",
                tag=f"hk-dirty-{room.id}",
            )
        except Exception:
            pass
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


@bookings_bp.route("/available-rooms")
@login_required
@permission_required("bookings.create")
def available_rooms_api():
    """JSON: rooms free between check_in and check_out (blocks website bookings too)."""
    from flask import jsonify
    ci_s = request.args.get("check_in") or ""
    co_s = request.args.get("check_out") or ""
    try:
        check_in = datetime.strptime(ci_s[:16], "%Y-%m-%dT%H:%M") if "T" in ci_s else datetime.strptime(ci_s[:10], "%Y-%m-%d")
        check_out = datetime.strptime(co_s[:16], "%Y-%m-%dT%H:%M") if "T" in co_s else datetime.strptime(co_s[:10], "%Y-%m-%d")
    except Exception:
        return jsonify({"rooms": [], "error": "Invalid dates"}), 400
    rooms = rooms_free_for_range(check_in, check_out)
    return jsonify({
        "rooms": [
            {"id": r.id, "number": r.number, "room_type": r.room_type, "price": float(r.price or 0)}
            for r in rooms
        ]
    })
