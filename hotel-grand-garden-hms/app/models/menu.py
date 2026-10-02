from datetime import datetime
from app import db


class MenuCategory(db.Model):
    __tablename__ = "menu_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("MenuItem", back_populates="category")


class MenuItem(db.Model):
    __tablename__ = "menu_items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("menu_categories.id"), index=True)
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    image_path = db.Column(db.String(255))
    image_url = db.Column(db.String(500))  # Cloudinary / absolute URL
    is_available = db.Column(db.Boolean, default=True, index=True)
    show_on_website = db.Column(db.Boolean, default=True)
    show_on_qr = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    category = db.relationship("MenuCategory", back_populates="items")
