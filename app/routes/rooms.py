from flask import current_app, Blueprint, render_template, request, redirect, url_for, flash, send_file, make_response
import qrcode
from io import BytesIO
from flask_login import login_required, current_user
from app import db
from app.models.room import Room, RestaurantTable, QRCode
from app.utils.decorators import permission_required
from app.utils.audit import log_activity, log_audit
from app.utils.uploads import save_upload
from decimal import Decimal

rooms_bp = Blueprint("rooms", __name__)


@rooms_bp.route("/")
@login_required
@permission_required("rooms.view")
def list_rooms():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    query = Room.query.filter_by(is_active=True)
    if q:
        query = query.filter(Room.number.contains(q) | Room.room_type.contains(q))
    if status:
        query = query.filter_by(status=status)
    rooms = query.order_by(Room.number).all()
    return render_template("rooms/list.html", rooms=rooms, q=q, status=status)


@rooms_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required("rooms.add")
def add_room():
    if request.method == "POST":
        number = (request.form.get("number") or "").strip()
        if Room.query.filter_by(number=number).first():
            flash("Room number already exists.", "danger")
            return render_template("rooms/form.html", room=None)
        room = Room(
            number=number,
            room_type=request.form.get("room_type") or "Standard",
            price=Decimal(request.form.get("price") or "0"),
            floor=(request.form.get("floor") or "").strip() or None,
            description=request.form.get("description"),
            amenities=request.form.get("amenities"),
            status=request.form.get("status") or "available",
            show_on_website=False,  # QR/ops only — never on public website
        )
        f = request.files.get("image")
        if f and f.filename:
            try:
                room.image_path = save_upload(f, "rooms")
            except ValueError as e:
                flash(str(e), "danger")
                return render_template("rooms/form.html", room=None)
        db.session.add(room)
        db.session.flush()
        # Auto-create QR
        qr = QRCode(token=QRCode.generate_token(), source_type="room", room_id=room.id, is_active=True)
        db.session.add(qr)
        db.session.commit()
        log_activity("create_room", module="rooms", record_type="Room", record_id=room.id)
        flash(f"Room {number} created with QR.", "success")
        return redirect(url_for("rooms.list_rooms"))
    return render_template("rooms/form.html", room=None)


@rooms_bp.route("/<int:room_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("rooms.edit")
def edit_room(room_id):
    room = db.session.get(Room, room_id) or abort_404()
    if request.method == "POST":
        old = f"{room.number}/{room.status}/{room.price}"
        room.number = (request.form.get("number") or room.number).strip()
        room.room_type = request.form.get("room_type") or room.room_type
        room.price = Decimal(request.form.get("price") or room.price)
        room.description = request.form.get("description")
        room.amenities = request.form.get("amenities")
        room.status = request.form.get("status") or room.status
        room.floor = (request.form.get("floor") or "").strip() or getattr(room, "floor", None)
        room.show_on_website = False  # HMS rooms never on public site
        # Keep HMS rooms off public site unless explicitly enabled
        if "show_on_website" in request.form:
            room.show_on_website = request.form.get("show_on_website") in ("1", "on", "true", "True")
        f = request.files.get("image")
        if f and f.filename:
            try:
                room.image_path = save_upload(f, "rooms")
            except ValueError as e:
                flash(str(e), "danger")
                return render_template("rooms/form.html", room=room)
        db.session.commit()
        log_audit("edit_room", module="rooms", record_type="Room", record_id=room.id, previous=old, new=f"{room.number}/{room.status}/{room.price}")
        flash("Room updated.", "success")
        return redirect(url_for("rooms.list_rooms"))
    return render_template("rooms/form.html", room=room)


@rooms_bp.route("/<int:room_id>/delete", methods=["POST"])
@login_required
@permission_required("rooms.delete")
def delete_room(room_id):
    room = db.session.get(Room, room_id)
    if room:
        room.is_active = False
        room.status = "disabled"
        for qr in room.qr_codes:
            qr.is_active = False
        db.session.commit()
        log_activity("deactivate_room", module="rooms", record_id=room.id)
        flash("Room deactivated.", "info")
    return redirect(url_for("rooms.list_rooms"))


@rooms_bp.route("/qr")
@login_required
@permission_required("rooms.qr")
def qr_list():
    """List active QR codes for rooms and tables."""
    try:
        rooms = Room.query.filter_by(is_active=True).order_by(Room.number).all()
    except Exception:
        db.session.rollback()
        rooms = []
    try:
        tables = RestaurantTable.query.filter_by(is_active=True).order_by(RestaurantTable.number).all()
    except Exception:
        db.session.rollback()
        tables = []
    public_site_url = current_app.config.get("HMS_SITE_URL") or current_app.config.get("PUBLIC_SITE_URL", "https://hms.hotelgrand.com.np")
    public_site_url = public_site_url.rstrip("/")
    return render_template("rooms/qr_list.html", rooms=rooms, tables=tables, public_site_url=public_site_url)


@rooms_bp.route("/qr/<int:qr_id>/regenerate", methods=["POST"])
@login_required
@permission_required("rooms.qr")
def regenerate_qr(qr_id):
    from datetime import datetime
    qr = db.session.get(QRCode, qr_id)
    if qr:
        qr.is_active = False
        new_qr = QRCode(
            token=QRCode.generate_token(),
            source_type=qr.source_type,
            room_id=qr.room_id,
            table_id=qr.table_id,
            is_active=True,
        )
        db.session.add(new_qr)
        db.session.commit()
        log_activity("regenerate_qr", module="rooms", record_id=new_qr.id)
        flash("QR regenerated. Old token disabled.", "success")
    return redirect(url_for("rooms.qr_list"))


@rooms_bp.route("/tables")
@login_required
@permission_required("rooms.view")
def list_tables():
    try:
        tables = RestaurantTable.query.filter_by(is_active=True).order_by(RestaurantTable.number).all()
    except Exception as e:
        db.session.rollback()
        flash(f"Tables load issue: {e}", "danger")
        tables = []
    return render_template("rooms/tables.html", tables=tables)


@rooms_bp.route("/tables/add", methods=["GET", "POST"])
@login_required
@permission_required("rooms.add")
def add_table():
    if request.method == "POST":
        number = (request.form.get("number") or "").strip()
        if RestaurantTable.query.filter_by(number=number).first():
            flash("Table number exists.", "danger")
            return render_template("rooms/table_form.html", table=None)
        t = RestaurantTable(
            number=number,
            seating_capacity=int(request.form.get("seating_capacity") or 4),
            status=request.form.get("status") or "available",
        )
        db.session.add(t)
        db.session.flush()
        qr = QRCode(token=QRCode.generate_token(), source_type="table", table_id=t.id, is_active=True)
        db.session.add(qr)
        db.session.commit()
        flash(f"Table {number} created.", "success")
        return redirect(url_for("rooms.list_tables"))
    return render_template("rooms/table_form.html", table=None)


def abort_404():
    from flask import abort
    abort(404)


@rooms_bp.route("/qr/<int:qr_id>/image")
@login_required
@permission_required("rooms.qr")
def qr_image(qr_id):
    qr = db.session.get(QRCode, qr_id)
    if not qr:
        from flask import abort
        abort(404)
    base = request.url_root.rstrip("/")
    public = (current_app.config.get("HMS_SITE_URL") or current_app.config.get("PUBLIC_SITE_URL") or "https://hms.hotelgrand.com.np").rstrip("/")
    # QR opens HMS order page: https://hms.hotelgrand.com.np/qr/order/<token>
    url = f"{public}/qr/order/{qr.token}"
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name=f"qr-{qr.id}.png")


@rooms_bp.route("/qr/<int:qr_id>/print")
@login_required
@permission_required("rooms.qr")
def qr_print(qr_id):
    qr = db.session.get(QRCode, qr_id)
    if not qr:
        from flask import abort
        abort(404)
    return render_template("rooms/qr_print.html", qr=qr, label=qr.label)


@rooms_bp.route("/<int:room_id>/generate-qr", methods=["POST"])
@login_required
@permission_required("rooms.qr")
def generate_room_qr(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        flash("Room not found.", "danger")
        return redirect(url_for("rooms.qr_list"))
    # deactivate old
    for q in room.qr_codes:
        q.is_active = False
    qr = QRCode(token=QRCode.generate_token(), source_type="room", room_id=room.id, is_active=True)
    db.session.add(qr)
    db.session.commit()
    log_activity("generate_qr", module="rooms", record_id=qr.id)
    flash(f"QR generated for Room {room.number}.", "success")
    return redirect(url_for("rooms.qr_list"))


@rooms_bp.route("/tables/<int:table_id>/generate-qr", methods=["POST"])
@login_required
@permission_required("rooms.qr")
def generate_table_qr(table_id):
    t = db.session.get(RestaurantTable, table_id)
    if not t:
        flash("Table not found.", "danger")
        return redirect(url_for("rooms.qr_list"))
    for q in t.qr_codes:
        q.is_active = False
    qr = QRCode(token=QRCode.generate_token(), source_type="table", table_id=t.id, is_active=True)
    db.session.add(qr)
    db.session.commit()
    log_activity("generate_qr", module="rooms", record_id=qr.id)
    flash(f"QR generated for Table {t.number}.", "success")
    return redirect(url_for("rooms.qr_list"))




@rooms_bp.route("/qr/bulk-print/rooms")
@login_required
@permission_required("rooms.qr")
def qr_bulk_print_rooms():
    """Print sheet of all active room QR codes."""
    from app.models.room import QRCode
    qrs = (
        QRCode.query.filter_by(source_type="room", is_active=True)
        .order_by(QRCode.room_id)
        .all()
    )
    public = (current_app.config.get("HMS_SITE_URL") or "https://hms.hotelgrand.com.np").rstrip("/")
    return render_template(
        "rooms/qr_bulk_print.html",
        qrs=qrs,
        kind="rooms",
        title="Room QR Codes",
        public_base=public,
    )


@rooms_bp.route("/qr/bulk-print/tables")
@login_required
@permission_required("rooms.qr")
def qr_bulk_print_tables():
    """Print sheet of all active table QR codes."""
    from app.models.room import QRCode
    qrs = (
        QRCode.query.filter_by(source_type="table", is_active=True)
        .order_by(QRCode.table_id)
        .all()
    )
    public = (current_app.config.get("HMS_SITE_URL") or "https://hms.hotelgrand.com.np").rstrip("/")
    return render_template(
        "rooms/qr_bulk_print.html",
        qrs=qrs,
        kind="tables",
        title="Table QR Codes",
        public_base=public,
    )



@rooms_bp.route("/qr/generate-all", methods=["POST"])
@login_required
@permission_required("rooms.qr")
def generate_all_qr():
    """Create active QR for every room and table that has none."""
    created = 0
    rooms = Room.query.filter_by(is_active=True).all()
    for room in rooms:
        active = QRCode.query.filter_by(room_id=room.id, is_active=True, source_type="room").first()
        if not active:
            db.session.add(QRCode(
                token=QRCode.generate_token(),
                source_type="room",
                room_id=room.id,
                is_active=True,
            ))
            created += 1
    tables = RestaurantTable.query.filter_by(is_active=True).all()
    for table in tables:
        active = QRCode.query.filter_by(table_id=table.id, is_active=True, source_type="table").first()
        if not active:
            db.session.add(QRCode(
                token=QRCode.generate_token(),
                source_type="table",
                table_id=table.id,
                is_active=True,
            ))
            created += 1
    db.session.commit()
    flash(f"Generated {created} new QR code(s).", "success")
    return redirect(url_for("rooms.qr_list"))


@rooms_bp.route("/qr/generate-all-rooms", methods=["POST"])
@login_required
@permission_required("rooms.qr")
def generate_all_room_qr():
    created = 0
    for room in Room.query.filter_by(is_active=True).all():
        if not QRCode.query.filter_by(room_id=room.id, is_active=True, source_type="room").first():
            db.session.add(QRCode(token=QRCode.generate_token(), source_type="room", room_id=room.id, is_active=True))
            created += 1
    db.session.commit()
    flash(f"Generated {created} room QR code(s).", "success")
    return redirect(url_for("rooms.qr_list"))


@rooms_bp.route("/qr/generate-all-tables", methods=["POST"])
@login_required
@permission_required("rooms.qr")
def generate_all_table_qr():
    created = 0
    for table in RestaurantTable.query.filter_by(is_active=True).all():
        if not QRCode.query.filter_by(table_id=table.id, is_active=True, source_type="table").first():
            db.session.add(QRCode(token=QRCode.generate_token(), source_type="table", table_id=table.id, is_active=True))
            created += 1
    db.session.commit()
    flash(f"Generated {created} table QR code(s).", "success")
    return redirect(url_for("rooms.qr_list"))
