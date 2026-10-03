from app.utils.timeutil import npt_now_naive
from app import db


class PushSubscription(db.Model):
    __tablename__ = "push_subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)  # staff; null for guest
    role_code = db.Column(db.String(50), index=True)  # kitchen, reception, admin, staff, customer
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=npt_now_naive)
    last_used_at = db.Column(db.DateTime)

    user = db.relationship("User", backref=db.backref("push_subscriptions", lazy="dynamic"))
