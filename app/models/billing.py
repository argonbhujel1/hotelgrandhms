from datetime import datetime
from app.utils.timeutil import npt_now_naive
from app import db


class PaymentMethod(db.Model):
    __tablename__ = "payment_methods"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)  # Cash, QR Payment, Card, Other
    code = db.Column(db.String(30), unique=True)
    qr_image_path = db.Column(db.String(255))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)


class Bill(db.Model):
    __tablename__ = "bills"
    id = db.Column(db.Integer, primary_key=True)
    bill_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), index=True)
    folio_id = db.Column(db.Integer, db.ForeignKey("folios.id"), index=True)
    # Snapshot of business info at bill time
    hotel_name = db.Column(db.String(150))
    business_name = db.Column(db.String(150))
    address = db.Column(db.String(255))
    phone = db.Column(db.String(30))
    pan = db.Column(db.String(50))
    vat_number = db.Column(db.String(50))
    customer_name = db.Column(db.String(150))
    order_type = db.Column(db.String(30))
    source_label = db.Column(db.String(50))
    subtotal = db.Column(db.Numeric(12, 2), default=0)
    discount = db.Column(db.Numeric(12, 2), default=0)
    service_charge = db.Column(db.Numeric(12, 2), default=0)
    price_before_vat = db.Column(db.Numeric(12, 2), default=0)
    vat_amount = db.Column(db.Numeric(12, 2), default=0)
    vat_rate = db.Column(db.Numeric(5, 2), default=13)
    total = db.Column(db.Numeric(12, 2), default=0)
    payment_method = db.Column(db.String(50))
    amount_received = db.Column(db.Numeric(12, 2), default=0)
    change_amount = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(30), default="completed")  # completed, void, refunded
    is_reprint = db.Column(db.Boolean, default=False)
    generated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    generated_by_name = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=npt_now_naive, index=True)

    order = db.relationship("Order", back_populates="bill")
    folio = db.relationship("Folio", back_populates="bill")
    payments = db.relationship("Payment", back_populates="bill", cascade="all, delete-orphan")

    @staticmethod
    def next_bill_number():
        last = Bill.query.order_by(Bill.id.desc()).first()
        n = (last.id + 1) if last else 1
        return f"BILL-{n:06d}"


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey("bills.id"), index=True)
    method = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reference = db.Column(db.String(100))
    notes = db.Column(db.String(255))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=npt_now_naive)

    bill = db.relationship("Bill", back_populates="payments")
