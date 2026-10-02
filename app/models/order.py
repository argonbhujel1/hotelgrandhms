from datetime import datetime
from decimal import Decimal
from app import db


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    source = db.Column(db.String(20), nullable=False, index=True)  # ROOM, TABLE, COUNTER
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), index=True)
    table_id = db.Column(db.Integer, db.ForeignKey("restaurant_tables.id"), index=True)
    customer_name = db.Column(db.String(150))  # optional
    special_instructions = db.Column(db.Text)
    status = db.Column(db.String(30), default="NEW", index=True)
    # NEW, ACCEPTED, PREPARING, READY, DELIVERED, COMPLETED, CANCELLED
    subtotal = db.Column(db.Numeric(12, 2), default=0)
    discount = db.Column(db.Numeric(12, 2), default=0)
    service_charge = db.Column(db.Numeric(12, 2), default=0)
    price_before_vat = db.Column(db.Numeric(12, 2), default=0)
    vat_amount = db.Column(db.Numeric(12, 2), default=0)
    total = db.Column(db.Numeric(12, 2), default=0)
    vat_rate_at_time = db.Column(db.Numeric(5, 2), default=13)
    folio_id = db.Column(db.Integer, db.ForeignKey("folios.id"), index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    status_history = db.relationship("OrderStatusHistory", back_populates="order", cascade="all, delete-orphan")
    bill = db.relationship("Bill", back_populates="order", uselist=False)
    folio = db.relationship("Folio", back_populates="orders")
    room = db.relationship("Room")
    table = db.relationship("RestaurantTable")

    @staticmethod
    def next_order_number():
        last = Order.query.order_by(Order.id.desc()).first()
        n = (last.id + 1) if last else 1
        return f"HG-{n:05d}"

    @property
    def source_label(self):
        if self.source == "ROOM" and self.room:
            return f"ROOM {self.room.number}"
        if self.source == "TABLE" and self.table:
            return f"TABLE {self.table.number}"
        return "COUNTER"


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"))
    item_name = db.Column(db.String(150), nullable=False)  # snapshot
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    notes = db.Column(db.String(255))

    order = db.relationship("Order", back_populates="items")
    menu_item = db.relationship("MenuItem")


class OrderStatusHistory(db.Model):
    __tablename__ = "order_status_history"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    order = db.relationship("Order", back_populates="status_history")
