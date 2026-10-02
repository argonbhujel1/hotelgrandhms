from datetime import datetime
from app.utils.timeutil import npt_now_naive
from app import db


class Booking(db.Model):
    __tablename__ = "bookings"
    __table_args__ = {"extend_existing": True}

    id = db.Column(db.Integer, primary_key=True)
    guest_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=True, index=True)
    check_in = db.Column(db.DateTime, nullable=True)
    check_out = db.Column(db.DateTime, nullable=True)
    num_guests = db.Column(db.Integer, default=1)
    advance_amount = db.Column(db.Numeric(12, 2), default=0)
    total_amount = db.Column(db.Numeric(12, 2), default=0)
    payment_status = db.Column(db.String(30), default="pending")
    status = db.Column(db.String(30), default="pending", index=True)
    notes = db.Column(db.Text)
    id_document = db.Column(db.String(100))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)
    updated_at = db.Column(db.DateTime, default=npt_now_naive, onupdate=npt_now_naive)

    # Website extras (shared DB — public site writes these)
    booking_ref = db.Column(db.String(32), index=True)
    guest_phone = db.Column(db.String(30))
    guest_email = db.Column(db.String(150))
    message = db.Column(db.Text)
    room_type_id = db.Column(db.Integer)
    room_number = db.Column(db.String(20))
    base_price_snapshot = db.Column(db.Numeric(10, 2))
    total_nights = db.Column(db.Integer)
    nightly_rates = db.Column(db.Text)
    source = db.Column(db.String(30), default="hms")
    advance_txn_number = db.Column(db.String(100))
    advance_paid_claimed = db.Column(db.Boolean, default=False)
    payment_proof_url = db.Column(db.String(500))
    client_ip = db.Column(db.String(64))
    ip_location = db.Column(db.String(255))

    room = db.relationship("Room", back_populates="bookings")
