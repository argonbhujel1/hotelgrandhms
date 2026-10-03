from datetime import datetime
from app.utils.timeutil import npt_now_naive
import secrets
from app import db


class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    floor = db.Column(db.String(20))  # e.g. 1, 2, Ground
    room_type = db.Column(db.String(50), nullable=False)  # Standard, Deluxe, Suite...
    price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    description = db.Column(db.Text)
    amenities = db.Column(db.Text)  # JSON or comma-separated
    image_path = db.Column(db.String(255))
    image_url = db.Column(db.String(500))
    show_on_website = db.Column(db.Boolean, default=False)  # HMS rooms stay internal unless public admin enables
    status = db.Column(db.String(20), default="available", index=True)
    # available, occupied, reserved, dirty, cleaning, maintenance, disabled
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=npt_now_naive)
    updated_at = db.Column(db.DateTime, default=npt_now_naive, onupdate=npt_now_naive)

    qr_codes = db.relationship("QRCode", back_populates="room", cascade="all, delete-orphan")
    bookings = db.relationship("Booking", back_populates="room")


class RestaurantTable(db.Model):
    __tablename__ = "restaurant_tables"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    seating_capacity = db.Column(db.Integer, default=4)
    status = db.Column(db.String(20), default="available", index=True)
    # available, occupied, reserved, dirty, cleaning, maintenance, disabled
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=npt_now_naive)
    updated_at = db.Column(db.DateTime, default=npt_now_naive, onupdate=npt_now_naive)

    qr_codes = db.relationship("QRCode", back_populates="table", cascade="all, delete-orphan")


class QRCode(db.Model):
    __tablename__ = "qr_codes"
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    source_type = db.Column(db.String(20), nullable=False)  # room, table
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), index=True)
    table_id = db.Column(db.Integer, db.ForeignKey("restaurant_tables.id"), index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=npt_now_naive)
    regenerated_at = db.Column(db.DateTime)

    room = db.relationship("Room", back_populates="qr_codes")
    table = db.relationship("RestaurantTable", back_populates="qr_codes")

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(32)

    @property
    def label(self):
        if self.source_type == "room" and self.room:
            return f"ROOM {self.room.number}"
        if self.source_type == "table" and self.table:
            return f"TABLE {self.table.number}"
        return "UNKNOWN"



class CleaningTask(db.Model):
    """Housekeeping assignment: Dirty → Assign → Cleaning → Complete (Ready)."""
    __tablename__ = "cleaning_tasks"
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False, index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(db.String(20), default="pending", index=True)
    # pending, cleaning, completed, cancelled
    notes = db.Column(db.String(255))
    assigned_at = db.Column(db.DateTime, default=npt_now_naive)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=npt_now_naive)

    room = db.relationship("Room", backref=db.backref("cleaning_tasks", lazy="dynamic"))
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    assigned_by = db.relationship("User", foreign_keys=[assigned_by_id])
