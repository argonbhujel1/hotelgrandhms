from datetime import datetime
from app.utils.timeutil import npt_now_naive, date
from app import db


class Folio(db.Model):
    """Open bill / guest folio — accumulates orders + room charges until closed."""
    __tablename__ = "folios"
    id = db.Column(db.Integer, primary_key=True)
    folio_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    source = db.Column(db.String(20), nullable=False)  # ROOM, TABLE, COUNTER
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), index=True)
    table_id = db.Column(db.Integer, db.ForeignKey("restaurant_tables.id"), index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), index=True)
    customer_name = db.Column(db.String(150))
    status = db.Column(db.String(20), default="open", index=True)  # open, closed
    notes = db.Column(db.Text)
    opened_at = db.Column(db.DateTime, default=npt_now_naive)
    closed_at = db.Column(db.DateTime)
    opened_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    closed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    # Multi-day room
    check_in_date = db.Column(db.Date)
    last_rent_charged_date = db.Column(db.Date)  # last date room rent was posted
    room_rate = db.Column(db.Numeric(12, 2), default=0)

    room = db.relationship("Room")
    table = db.relationship("RestaurantTable")
    orders = db.relationship("Order", back_populates="folio")
    charges = db.relationship("FolioCharge", back_populates="folio", cascade="all, delete-orphan")
    bill = db.relationship("Bill", back_populates="folio", uselist=False)

    @staticmethod
    def next_number():
        last = Folio.query.order_by(Folio.id.desc()).first()
        n = (last.id + 1) if last else 1
        return f"FOL-{n:06d}"

    @property
    def label(self):
        if self.source == "ROOM" and self.room:
            return f"ROOM {self.room.number}"
        if self.source == "TABLE" and self.table:
            return f"TABLE {self.table.number}"
        return "COUNTER"

    def food_total(self):
        from decimal import Decimal
        t = Decimal("0")
        for o in self.orders:
            if o.status != "CANCELLED":
                t += o.total or 0
        return t

    def charges_total(self):
        from decimal import Decimal
        t = Decimal("0")
        for c in self.charges:
            t += c.amount or 0
        return t

    def grand_total(self):
        return self.food_total() + self.charges_total()


class FolioCharge(db.Model):
    """Room rent / extra charges on folio."""
    __tablename__ = "folio_charges"
    id = db.Column(db.Integer, primary_key=True)
    folio_id = db.Column(db.Integer, db.ForeignKey("folios.id"), nullable=False, index=True)
    charge_type = db.Column(db.String(40), default="room_rent")  # room_rent, extra, adjustment
    description = db.Column(db.String(255))
    charge_date = db.Column(db.Date, default=date.today)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=npt_now_naive)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    folio = db.relationship("Folio", back_populates="charges")
