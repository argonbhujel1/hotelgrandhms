from datetime import datetime, date
from flask import Blueprint, render_template
from flask_login import login_required, current_user
from sqlalchemy import func
from app import db
from app.models.room import Room
from app.models.booking import Booking
from app.models.order import Order
from app.models.user import StaffSession
from app.models.staff_hr import LeaveRequest, Attendance, OvertimeRequest, StaffConsumption
from app.models.activity import ActivityLog
from app.utils.decorators import permission_required

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
@permission_required("dashboard.view")
def index():
    today = date.today()
    stats = {}

    if current_user.has_permission("rooms.view"):
        stats["total_rooms"] = Room.query.filter_by(is_active=True).count()
        stats["available_rooms"] = Room.query.filter_by(is_active=True, status="available").count()
        stats["occupied_rooms"] = Room.query.filter_by(is_active=True, status="occupied").count()
        stats["reserved_rooms"] = Room.query.filter_by(is_active=True, status="reserved").count()

    if current_user.has_permission("bookings.view"):
        stats["today_bookings"] = Booking.query.filter(
            func.date(Booking.check_in) == today,
            Booking.status.in_(["pending", "confirmed", "checked_in"]),
        ).count()

    if current_user.has_permission("orders.view"):
        stats["new_orders"] = Order.query.filter_by(status="NEW").count()
        stats["preparing_orders"] = Order.query.filter(Order.status.in_(["ACCEPTED", "PREPARING"])).count()
        stats["ready_orders"] = Order.query.filter_by(status="READY").count()
        today_sales = (
            db.session.query(func.coalesce(func.sum(Order.total), 0))
            .filter(func.date(Order.created_at) == today, Order.status != "CANCELLED")
            .scalar()
        )
        stats["today_sales"] = today_sales

    if current_user.has_permission("leave.approve"):
        stats["pending_leave"] = LeaveRequest.query.filter_by(status="pending").count()
        stats["pending_attendance"] = Attendance.query.filter_by(status="pending").count()
        stats["pending_ot"] = OvertimeRequest.query.filter_by(status="pending").count()
        stats["pending_consumption"] = StaffConsumption.query.filter_by(status="pending").count()

    if current_user.has_permission("sessions.view"):
        stats["online_staff"] = StaffSession.query.filter_by(is_active=True, status="online").count()

    recent = []
    if current_user.has_permission("audit.view") or current_user.role_code in ("super_admin", "admin"):
        recent = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(15).all()

    return render_template("dashboard/index.html", stats=stats, recent=recent, today=today)
