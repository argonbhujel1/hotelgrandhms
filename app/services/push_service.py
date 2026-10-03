"""Web Push helpers. Requires VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_CLAIM_EMAIL in env.
Falls back to no-op if keys or pywebpush missing so app still runs.
"""
import json
import os
from app import db

try:
    from pywebpush import webpush, WebPushException
    HAS_WEBPUSH = True
except ImportError:
    HAS_WEBPUSH = False


def vapid_keys():
    return {
        "public": os.environ.get("VAPID_PUBLIC_KEY") or os.environ.get("VAPID_PUBLIC") or "",
        "private": os.environ.get("VAPID_PRIVATE_KEY") or os.environ.get("VAPID_PRIVATE") or "",
        "email": os.environ.get("VAPID_CLAIM_EMAIL") or os.environ.get("ADMIN_EMAIL") or "mailto:admin@hotelgrand.com.np",
    }


def save_subscription(endpoint, p256dh, auth, user_id=None, role_code=None, user_agent=None):
    from app.models.push import PushSubscription
    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if not sub:
        sub = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth)
        db.session.add(sub)
    sub.p256dh = p256dh
    sub.auth = auth
    if user_id is not None:
        sub.user_id = user_id
    if role_code:
        sub.role_code = role_code
    if user_agent:
        sub.user_agent = (user_agent or "")[:255]
    db.session.commit()
    return sub


def send_push_to_subscription(sub, title, body, url="/", tag="hms"):
    keys = vapid_keys()
    if not HAS_WEBPUSH or not keys["public"] or not keys["private"]:
        return False
    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "tag": tag,
        "icon": "/static/img/icon-192.png",
        "badge": "/static/img/icon-192.png",
    })
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=payload,
            vapid_private_key=keys["private"],
            vapid_claims={"sub": keys["email"] if keys["email"].startswith("mailto:") else f"mailto:{keys['email']}"},
        )
        return True
    except Exception:
        # Drop dead subscriptions
        try:
            db.session.delete(sub)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return False


def notify_roles(role_codes, title, body, url="/", tag="hms"):
    """Notify all push subscriptions matching any role code (and super_admin always for admin alerts)."""
    from app.models.push import PushSubscription
    from app.models.user import User
    codes = set(role_codes or [])
    subs = PushSubscription.query.filter(PushSubscription.role_code.in_(list(codes))).all()
    # Also match by user.role
    if codes:
        users = User.query.filter(User.is_active.is_(True)).all()
        user_ids = [u.id for u in users if u.role and u.role.code in codes]
        if user_ids:
            more = PushSubscription.query.filter(PushSubscription.user_id.in_(user_ids)).all()
            seen = {s.id for s in subs}
            for s in more:
                if s.id not in seen:
                    subs.append(s)
    for sub in subs:
        send_push_to_subscription(sub, title, body, url=url, tag=tag)
    return len(subs)


def notify_user(user_id, title, body, url="/", tag="hms"):
    from app.models.push import PushSubscription
    for sub in PushSubscription.query.filter_by(user_id=user_id).all():
        send_push_to_subscription(sub, title, body, url=url, tag=tag)


def notify_customer_email(email, title, body, url="/", tag="customer"):
    """Guest subscriptions stored with role_code=customer and endpoint keyed; we match by storing email in user_agent prefix or skip if none."""
    from app.models.push import PushSubscription
    # Customer subs may use role_code customer; optional email in user_agent as "email:..."
    for sub in PushSubscription.query.filter_by(role_code="customer").all():
        ua = sub.user_agent or ""
        if email and f"email:{email}" in ua:
            send_push_to_subscription(sub, title, body, url=url, tag=tag)
