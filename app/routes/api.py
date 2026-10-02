from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from app.models.order import Order
from app.models.user import StaffSession
from app import db
from datetime import datetime

api_bp = Blueprint("api", __name__)


@api_bp.route("/orders/new-count")
@login_required
def new_orders_count():
    if not current_user.has_permission("orders.view"):
        return jsonify({"count": 0})
    count = Order.query.filter_by(status="NEW").count()
    return jsonify({"count": count})


@api_bp.route("/heartbeat", methods=["POST"])
@login_required
def heartbeat():
    from flask import session
    token = session.get("staff_session_token")
    if token:
        s = StaffSession.query.filter_by(session_token=token, user_id=current_user.id, is_active=True).first()
        if s:
            s.last_activity = datetime.utcnow()
            s.status = "online"
            db.session.commit()
    return jsonify({"ok": True})
