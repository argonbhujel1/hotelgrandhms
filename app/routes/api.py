from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from app.models.order import Order
from app.models.user import StaffSession
from app import db
from datetime import datetime
from app.utils.timeutil import npt_now_naive

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
            s.last_activity = npt_now_naive()
            s.status = "online"
            db.session.commit()
    return jsonify({"ok": True})


@api_bp.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    from flask import request
    from app.services.push_service import save_subscription
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return jsonify({"ok": False, "error": "invalid subscription"}), 400
    role = data.get("role") or (current_user.role.code if current_user.role else None)
    save_subscription(
        endpoint=endpoint,
        p256dh=keys["p256dh"],
        auth=keys["auth"],
        user_id=current_user.id,
        role_code=role,
        user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"ok": True})


@api_bp.route("/push/vapid-public")
def vapid_public():
    from app.services.push_service import vapid_keys
    return jsonify({"publicKey": vapid_keys()["public"]})
