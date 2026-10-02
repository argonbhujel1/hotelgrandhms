from datetime import datetime
from app.utils.timeutil import npt_now_naive
from flask_login import UserMixin
from app import db


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=npt_now_naive)

    users = db.relationship("User", back_populates="role")
    permissions = db.relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")


class Permission(db.Model):
    __tablename__ = "permissions"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    module = db.Column(db.String(50))
    description = db.Column(db.String(255))


class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    permission_id = db.Column(db.Integer, db.ForeignKey("permissions.id"), nullable=False)

    role = db.relationship("Role", back_populates="permissions")
    permission = db.relationship("Permission")

    __table_args__ = (db.UniqueConstraint("role_id", "permission_id"),)


class StaffPermission(db.Model):
    """Override / extra permissions per staff."""
    __tablename__ = "staff_permissions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    permission_id = db.Column(db.Integer, db.ForeignKey("permissions.id"), nullable=False)
    granted = db.Column(db.Boolean, default=True)  # False = explicit deny

    user = db.relationship("User", back_populates="extra_permissions")
    permission = db.relationship("Permission")

    __table_args__ = (db.UniqueConstraint("user_id", "permission_id"),)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    employee_id = db.Column(db.String(50), unique=True, index=True)
    phone = db.Column(db.String(30))
    department = db.Column(db.String(100))
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, index=True)
    joining_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=npt_now_naive)
    updated_at = db.Column(db.DateTime, default=npt_now_naive, onupdate=npt_now_naive)
    last_login_at = db.Column(db.DateTime)
    device_label = db.Column(db.String(100))  # e.g. Reception PC

    role = db.relationship("Role", back_populates="users")
    extra_permissions = db.relationship("StaffPermission", back_populates="user", cascade="all, delete-orphan")
    sessions = db.relationship("StaffSession", back_populates="user", cascade="all, delete-orphan")
    salary_profile = db.relationship("StaffSalaryProfile", back_populates="user", uselist=False)

    def has_permission(self, code: str) -> bool:
        if not self.is_active:
            return False
        # Explicit staff deny
        for sp in self.extra_permissions:
            if sp.permission and sp.permission.code == code and not sp.granted:
                return False
        # Explicit staff grant
        for sp in self.extra_permissions:
            if sp.permission and sp.permission.code == code and sp.granted:
                return True
        # Role permissions
        if self.role:
            for rp in self.role.permissions:
                if rp.permission and rp.permission.code == code:
                    return True
        # Super admin & Admin full access
        if self.role and self.role.code in ("super_admin", "admin"):
            return True
        return False

    def has_any_permission(self, *codes) -> bool:
        return any(self.has_permission(c) for c in codes)

    @property
    def role_code(self):
        return self.role.code if self.role else None

    def get_id(self):
        return str(self.id)


class StaffSession(db.Model):
    __tablename__ = "staff_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    session_token = db.Column(db.String(128), unique=True, index=True)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(512))
    device_label = db.Column(db.String(100))
    login_at = db.Column(db.DateTime, default=npt_now_naive)
    last_activity = db.Column(db.DateTime, default=npt_now_naive)
    is_active = db.Column(db.Boolean, default=True, index=True)
    status = db.Column(db.String(20), default="online")  # online, idle, offline

    user = db.relationship("User", back_populates="sessions")


class StaffLoginHistory(db.Model):
    __tablename__ = "staff_login_history"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(512))
    success = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=npt_now_naive)
