from functools import wraps
from flask import abort, flash, redirect, url_for, request
from flask_login import current_user, login_required


def permission_required(*perm_codes):
    """Require at least one of the given permission codes."""
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.url))
            if not current_user.is_active:
                flash("Your account is disabled.", "danger")
                return redirect(url_for("auth.logout"))
            if not current_user.has_any_permission(*perm_codes):
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def role_required(*role_codes):
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.role:
                abort(403)
            if current_user.role.code not in role_codes and current_user.role.code != "super_admin":
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator
