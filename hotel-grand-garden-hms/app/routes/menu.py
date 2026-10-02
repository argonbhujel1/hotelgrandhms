from decimal import Decimal, InvalidOperation
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.menu import MenuCategory, MenuItem
from app.utils.decorators import permission_required
from app.utils.audit import log_activity, log_audit
from app.utils.uploads import save_upload
from app.utils.cloudinary_upload import upload_media

menu_bp = Blueprint("menu", __name__)


@menu_bp.route("/")
@login_required
@permission_required("menu.view")
def list_items():
    cat_id = request.args.get("category", type=int)
    q = MenuItem.query.filter_by(is_active=True)
    if cat_id:
        q = q.filter_by(category_id=cat_id)
    items = q.order_by(MenuItem.sort_order, MenuItem.name).all()
    categories = MenuCategory.query.filter_by(is_active=True).order_by(MenuCategory.sort_order).all()
    return render_template("menu/list.html", items=items, categories=categories, cat_id=cat_id)


def _parse_price(raw):
    try:
        return Decimal(str(raw or "0").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


@menu_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required("menu.add")
def add_item():
    categories = MenuCategory.query.filter_by(is_active=True).order_by(MenuCategory.sort_order).all()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Item name is required.", "danger")
            return render_template("menu/form.html", item=None, categories=categories)
        cat_raw = request.form.get("category_id") or ""
        category_id = int(cat_raw) if cat_raw.isdigit() else None
        item = MenuItem(
            name=name,
            category_id=category_id,
            description=request.form.get("description"),
            price=_parse_price(request.form.get("price")),
            is_available=request.form.get("is_available") in ("1", "on", "true", "True"),
            show_on_website=request.form.get("show_on_website") in ("1", "on", "true", "True"),
            show_on_qr=request.form.get("show_on_qr") in ("1", "on", "true", "True"),
            sort_order=int(request.form.get("sort_order") or 0),
            created_by_id=current_user.id,
        )
        f = request.files.get("image")
        if f and f.filename:
            try:
                media = upload_media(f, "menu")
                if media:
                    if media.get("url"):
                        item.image_url = media["url"]
                    if media.get("local_path"):
                        item.image_path = media["local_path"]
            except Exception as e:
                flash(f"Image upload issue: {e}. Item saved without new image.", "warning")
        db.session.add(item)
        db.session.commit()
        log_activity("create_menu_item", module="menu", record_id=item.id)
        flash("Menu item added.", "success")
        return redirect(url_for("menu.list_items"))
    return render_template("menu/form.html", item=None, categories=categories)


@menu_bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("menu.edit")
def edit_item(item_id):
    item = db.session.get(MenuItem, item_id)
    categories = MenuCategory.query.filter_by(is_active=True).order_by(MenuCategory.sort_order).all()
    if not item:
        flash("Not found.", "danger")
        return redirect(url_for("menu.list_items"))
    if request.method == "POST":
        old_price = str(item.price)
        name = (request.form.get("name") or "").strip()
        if name:
            item.name = name
        cat_raw = request.form.get("category_id") or ""
        item.category_id = int(cat_raw) if cat_raw.isdigit() else None
        item.description = request.form.get("description")
        item.price = _parse_price(request.form.get("price") or item.price)
        item.is_available = request.form.get("is_available") in ("1", "on", "true", "True")
        item.show_on_website = request.form.get("show_on_website") in ("1", "on", "true", "True")
        item.show_on_qr = request.form.get("show_on_qr") in ("1", "on", "true", "True")
        item.sort_order = int(request.form.get("sort_order") or 0)
        item.updated_by_id = current_user.id
        f = request.files.get("image")
        if f and f.filename:
            try:
                media = upload_media(f, "menu")
                if media:
                    if media.get("url"):
                        item.image_url = media["url"]
                    if media.get("local_path"):
                        item.image_path = media["local_path"]
            except Exception as e:
                flash(f"Image upload: {e}", "warning")
        db.session.commit()
        if old_price != str(item.price):
            log_audit("price_change", module="menu", record_type="MenuItem", record_id=item.id, previous=old_price, new=str(item.price))
        flash("Item updated.", "success")
        return redirect(url_for("menu.list_items"))
    return render_template("menu/form.html", item=item, categories=categories)


@menu_bp.route("/categories")
@login_required
@permission_required("menu.categories")
def categories():
    cats = MenuCategory.query.order_by(MenuCategory.sort_order).all()
    return render_template("menu/categories.html", categories=cats)


@menu_bp.route("/categories/add", methods=["POST"])
@login_required
@permission_required("menu.categories")
def add_category():
    name = (request.form.get("name") or "").strip()
    if name:
        db.session.add(MenuCategory(name=name, sort_order=int(request.form.get("sort_order") or 0)))
        db.session.commit()
        flash("Category added.", "success")
    return redirect(url_for("menu.categories"))
