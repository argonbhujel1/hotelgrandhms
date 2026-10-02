from datetime import datetime
from app import db


class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    guest_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False, index=True)
    check_in = db.Column(db.DateTime, nullable=False)
    check_out = db.Column(db.DateTime, nullable=False)
    num_guests = db.Column(db.Integer, default=1)
    advance_amount = db.Column(db.Numeric(12, 2), default=0)
    total_amount = db.Column(db.Numeric(12, 2), default=0)
    payment_status = db.Column(db.String(30), default="pending")  # pending, partial, paid
    status = db.Column(db.String(30), default="pending", index=True)
    # pending, confirmed, checked_in, checked_out, cancelled
    notes = db.Column(db.Text)
    id_document = db.Column(db.String(100))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    room = db.relationship("Room", back_populates="bookings")
