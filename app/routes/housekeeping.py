"""Housekeeping workflow: Dirty → Assign → Cleaning → Complete."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.room import Room, CleaningTask
from app.models.user import User, Role
from app.utils.decorators import permission_required
from app.utils.audit import log_activity
from app.utils.timeutil import npt_now_naive, now_npt

hk_bp = Blueprint("housekeeping", __name__)


def _hk_staff():
    """Users with housekeeping role or rooms.status permission."""
    role = Role.query.filter_by(code="housekeeping").first()
    q = User.query.filter_by(is_active=True)
    if role:
        return q.filter_by(role_id=role.id).order_by(User.full_name).all()
    return q.order_by(User.full_name).all()


@hk_bp.route("/")
@login_required
def home():
    """Staff home: today's assigned tasks + room counts."""
    uid = current_user.id
    my_pending = CleaningTask.query.filter_by(assigned_to_id=uid, status="pending").order_by(CleaningTask.assigned_at.desc()).all()
    my_cleaning = CleaningTask.query.filter_by(assigned_to_id=uid, status="cleaning").order_by(CleaningTask.started_at.desc()).all()
    my_done = (
        CleaningTask.query.filter_by(assigned_to_id=uid, status="completed")
        .order_by(CleaningTask.completed_at.desc())
        .limit(10)
        .all()
    )
    dirty_count = Room.query.filter_by(is_active=True, status="dirty").count()
    cleaning_count = Room.query.filter_by(is_active=True, status="cleaning").count()
    ready_count = Room.query.filter(Room.is_active.is_(True), Room.status.in_(["available"])).count()
    return render_template(
        "housekeeping/home.html",
        my_pending=my_pending,
        my_cleaning=my_cleaning,
        my_done=my_done,
        dirty_count=dirty_count,
        cleaning_count=cleaning_count,
        ready_count=ready_count,
        npt_now=now_npt(),
    )


@hk_bp.route("/rooms")
@login_required
@permission_required("rooms.view")
def rooms():
    status = request.args.get("status") or ""
    q = Room.query.filter_by(is_active=True)
    if status:
        q = q.filter_by(status=status)
    else:
        q = q.filter(Room.status.in_(["dirty", "cleaning", "available", "maintenance"]))
    rooms = q.order_by(Room.number).all()
    # open tasks map
    open_tasks = {
        t.room_id: t
        for t in CleaningTask.query.filter(CleaningTask.status.in_(["pending", "cleaning"])).all()
    }
    return render_template("housekeeping/rooms.html", rooms=rooms, status=status, open_tasks=open_tasks)


@hk_bp.route("/tasks")
@login_required
def tasks():
    """My cleaning tasks (or all if admin)."""
    is_admin = current_user.role_code in ("admin", "super_admin") or current_user.has_permission("staff.view")
    if is_admin and request.args.get("all"):
        items = CleaningTask.query.order_by(CleaningTask.assigned_at.desc()).limit(100).all()
    else:
        items = (
            CleaningTask.query.filter_by(assigned_to_id=current_user.id)
            .order_by(CleaningTask.assigned_at.desc())
            .limit(50)
            .all()
        )
    return render_template("housekeeping/tasks.html", tasks=items, is_admin=is_admin)


@hk_bp.route("/alerts")
@login_required
def alerts():
    """Simple alerts: new pending assignments for this user + dirty unassigned."""
    my_new = CleaningTask.query.filter_by(assigned_to_id=current_user.id, status="pending").order_by(CleaningTask.assigned_at.desc()).all()
    dirty_unassigned = []
    if current_user.role_code in ("admin", "super_admin") or current_user.has_permission("rooms.status"):
        assigned_room_ids = {
            t.room_id
            for t in CleaningTask.query.filter(CleaningTask.status.in_(["pending", "cleaning"])).all()
        }
        dirty_unassigned = [
            r for r in Room.query.filter_by(is_active=True, status="dirty").order_by(Room.number).all()
            if r.id not in assigned_room_ids
        ]
    return render_template("housekeeping/alerts.html", my_new=my_new, dirty_unassigned=dirty_unassigned)


@hk_bp.route("/assign", methods=["GET", "POST"])
@login_required
@permission_required("rooms.status")
def assign():
    """Admin: Dirty Room List → select staff → assign task."""
    dirty = Room.query.filter_by(is_active=True, status="dirty").order_by(Room.number).all()
    # also show cleaning rooms without active task
    staff = _hk_staff()
    if request.method == "POST":
        room_id = int(request.form.get("room_id") or 0)
        staff_id = int(request.form.get("staff_id") or 0)
        notes = (request.form.get("notes") or "").strip() or None
        room = db.session.get(Room, room_id)
        user = db.session.get(User, staff_id)
        if not room or not user:
            flash("Select room and staff.", "danger")
            return redirect(url_for("housekeeping.assign"))
        # cancel previous open tasks for this room
        for t in CleaningTask.query.filter_by(room_id=room.id).filter(CleaningTask.status.in_(["pending", "cleaning"])).all():
            t.status = "cancelled"
        task = CleaningTask(
            room_id=room.id,
            assigned_to_id=user.id,
            assigned_by_id=current_user.id,
            status="pending",
            notes=notes,
            assigned_at=npt_now_naive(),
        )
        db.session.add(task)
        # keep room dirty until staff starts
        if room.status not in ("dirty", "cleaning"):
            room.status = "dirty"
        db.session.commit()
        log_activity("hk_assign", module="housekeeping", record_id=task.id, details=f"room {room.number} → {user.full_name}")
        # Push to assigned staff
        try:
            from app.services.push_service import notify_user, notify_roles
            notify_user(
                user.id,
                "🔔 Cleaning task assigned",
                f"Room {room.number} cleaning task assigned to you.",
                url="/housekeeping/tasks",
                tag=f"hk-task-{task.id}",
            )
            notify_roles(
                ["admin", "super_admin", "reception"],
                "🔔 HK task assigned",
                f"Room {room.number} → {user.full_name}",
                url="/housekeeping/assign",
                tag=f"hk-assign-{task.id}",
            )
        except Exception:
            pass
        flash(f"Room {room.number} assigned to {user.full_name}. Notification sent.", "success")
        return redirect(url_for("housekeeping.assign"))
    # map open tasks
    open_map = {
        t.room_id: t
        for t in CleaningTask.query.filter(CleaningTask.status.in_(["pending", "cleaning"])).all()
    }
    return render_template("housekeeping/assign.html", dirty=dirty, staff=staff, open_map=open_map)


@hk_bp.route("/tasks/<int:tid>/start", methods=["POST"])
@login_required
def task_start(tid):
    task = db.session.get(CleaningTask, tid)
    if not task:
        flash("Task not found.", "danger")
        return redirect(url_for("housekeeping.tasks"))
    if task.assigned_to_id != current_user.id and current_user.role_code not in ("admin", "super_admin"):
        flash("Not your task.", "danger")
        return redirect(url_for("housekeeping.tasks"))
    task.status = "cleaning"
    task.started_at = npt_now_naive()
    if task.room:
        task.room.status = "cleaning"
    db.session.commit()
    log_activity("hk_start", module="housekeeping", record_id=task.id)
    flash(f"Started cleaning room {task.room.number if task.room else tid}.", "success")
    return redirect(request.referrer or url_for("housekeeping.tasks"))


@hk_bp.route("/tasks/<int:tid>/complete", methods=["POST"])
@login_required
def task_complete(tid):
    task = db.session.get(CleaningTask, tid)
    if not task:
        flash("Task not found.", "danger")
        return redirect(url_for("housekeeping.tasks"))
    if task.assigned_to_id != current_user.id and current_user.role_code not in ("admin", "super_admin"):
        flash("Not your task.", "danger")
        return redirect(url_for("housekeeping.tasks"))
    task.status = "completed"
    task.completed_at = npt_now_naive()
    if task.room:
        task.room.status = "available"  # CLEAN / READY
    db.session.commit()
    log_activity("hk_complete", module="housekeeping", record_id=task.id)
    try:
        from app.services.push_service import notify_roles
        num = task.room.number if task.room else "?"
        notify_roles(
            ["reception", "admin", "super_admin"],
            "🔔 Room ready",
            f"Room {num} cleaned and ready",
            url="/rooms/",
            tag=f"hk-done-{task.id}",
        )
    except Exception:
        pass
    flash(f"Room {task.room.number if task.room else ''} marked CLEAN / READY.", "success")
    return redirect(request.referrer or url_for("housekeeping.tasks"))
