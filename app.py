# -*- coding: utf-8 -*-
"""二維碼掃碼點餐系統 - 主應用"""

import os
import time
import uuid
import qrcode
import base64
from io import BytesIO
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, session
from functools import wraps
from PIL import Image

from database import db, init_db, Table, Category, Dish, Order, OrderItem, Combo, ComboItem

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///qr_order.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
app.config['QR_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'qrcodes')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.config['SECRET_KEY'] = 'qr-order-system-2024'

# 創建上傳目錄
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['QR_FOLDER'], exist_ok=True)

init_db(app)


def generate_qr_code(table_number, base_url=None):
    """生成檯號二維碼，返回 base64 圖片數據"""
    if base_url is None:
        base_url = request.host_url.rstrip('/')
    order_url = f"{base_url}/order/{table_number}"

    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(order_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    img_str = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{img_str}", order_url


# ======================== 前台路由 ========================

@app.route('/')
def index():
    tables = Table.query.order_by(Table.table_number).all()
    return render_template('index.html', tables=tables)


@app.route('/order/<table_number>')
def order_page(table_number):
    table = Table.query.filter_by(table_number=table_number).first_or_404()
    categories = Category.query.order_by(Category.sort_order).all()
    dishes_by_category = {}
    for cat in categories:
        dishes = Dish.query.filter_by(category_id=cat.id, is_available=True).all()
        if dishes:
            dishes_by_category[cat] = dishes
    combos = Combo.query.filter_by(is_available=True).all()
    from_home = request.args.get('ref') == 'home'
    return render_template('table_order.html', table=table,
                          categories=dishes_by_category, combos=combos, from_home=from_home)


@app.route('/api/order/<table_number>/orders', methods=['GET'])
def get_table_orders(table_number):
    """獲取指定檯號的活躍訂單列表（仅 pending/confirmed）"""
    table = Table.query.filter_by(table_number=table_number).first_or_404()
    orders = Order.query.filter(
        Order.table_id == table.id,
        Order.status.in_(['pending', 'confirmed'])
    ).order_by(Order.created_at.desc()).limit(20).all()
    result = []
    for o in orders:
        items = [{
            'dish_name': i.dish_name,
            'quantity': i.quantity,
            'unit_price': i.unit_price
        } for i in o.items]
        result.append({
            'id': o.id,
            'status': o.status,
            'total_price': o.total_price,
            'remark': o.remark,
            'items': items,
            'created_at': o.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    return jsonify(result)


@app.route('/api/order/<table_number>', methods=['POST'])
def submit_order(table_number):
    table = Table.query.filter_by(table_number=table_number).first_or_404()
    data = request.get_json()
    items = data.get('items', [])
    remark = data.get('remark', '')

    if not items:
        return jsonify({'error': '請選擇菜式'}), 400

    order = Order(table_id=table.id, status='pending', remark=remark)
    db.session.add(order)
    db.session.flush()

    total = 0
    for item in items:
        qty = int(item.get('quantity', 1))

        # 套餐下單
        if item.get('combo_id'):
            combo = Combo.query.get(item['combo_id'])
            if not combo or not combo.is_available:
                return jsonify({'error': f'套餐「{combo.name if combo else "未知"}」已下架'}), 400
            total += combo.price * qty
            order_item = OrderItem(
                order_id=order.id,
                dish_id=None,
                combo_id=combo.id,
                dish_name=combo.name,
                quantity=qty,
                unit_price=combo.price
            )
            db.session.add(order_item)
        else:
            dish = Dish.query.get(item['dish_id'])
            if not dish or not dish.is_available:
                return jsonify({'error': f'菜式「{dish.name if dish else "未知"}」已下架'}), 400
            if dish.stock > 0 and dish.stock < qty:
                return jsonify({'error': f'「{dish.name}」庫存不足，剩餘 {dish.stock}'}), 400
            subtotal = dish.price * qty
            total += subtotal
            order_item = OrderItem(
                order_id=order.id,
                dish_id=dish.id,
                combo_id=None,
                dish_name=dish.name,
                quantity=qty,
                unit_price=dish.price
            )
            db.session.add(order_item)
            if dish.stock > 0:
                dish.stock -= qty

    order.total_price = total
    db.session.commit()
    return jsonify({'success': True, 'order_id': order.id, 'total': total})


# ======================== 管理後台認證 ========================

ADMIN_PASSWORD = 'admin888'

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin'))
        error = '密碼錯誤'
    return render_template('admin_login.html', error=error)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))


# ======================== 管理後台路由 ========================

@app.route('/admin')
@admin_required
def admin():
    return render_template('admin.html')


@app.route('/admin/dishes')
@admin_required
def admin_dishes():
    categories = Category.query.order_by(Category.sort_order).all()
    dishes = Dish.query.order_by(Dish.id.desc()).all()
    return render_template('admin_dishes.html', categories=categories, dishes=dishes)


@app.route('/admin/tables')
@admin_required
def admin_tables():
    tables = Table.query.order_by(Table.table_number).all()
    return render_template('admin_tables.html', tables=tables)


@app.route('/admin/orders')
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin_orders.html', orders=orders)


@app.route('/admin/categories')
@admin_required
def admin_categories():
    return render_template('admin_categories.html')


@app.route('/admin/combos')
@admin_required
def admin_combos():
    categories = Category.query.order_by(Category.sort_order).all()
    return render_template('admin_combos.html', categories=categories)


@app.route('/admin/reports')
@admin_required
def admin_reports():
    return render_template('admin_reports.html')


# ======================== 管理 API ========================

@app.route('/api/admin/categories', methods=['GET'])
@admin_required
def get_categories():
    cats = Category.query.order_by(Category.sort_order).all()
    result = []
    for c in cats:
        dish_count = Dish.query.filter_by(category_id=c.id).count()
        result.append({
            'id': c.id,
            'name': c.name,
            'sort_order': c.sort_order,
            'dish_count': dish_count
        })
    return jsonify(result)


@app.route('/api/admin/categories', methods=['POST'])
@admin_required
def add_category():
    data = request.get_json()
    if not data:
        return jsonify({'error': '數據不能為空'}), 400

    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '分類名稱不能為空'}), 400

    if Category.query.filter_by(name=name).first():
        return jsonify({'error': f'分類「{name}」已存在'}), 400

    sort_order = int(data.get('sort_order', 0))
    cat = Category(name=name, sort_order=sort_order)
    db.session.add(cat)
    db.session.commit()
    return jsonify({'success': True, 'category': {'id': cat.id, 'name': cat.name, 'sort_order': cat.sort_order, 'dish_count': 0}})


@app.route('/api/admin/categories/<int:cat_id>', methods=['PUT'])
@admin_required
def update_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': '數據不能為空'}), 400

    new_name = data.get('name', '').strip()
    if not new_name:
        return jsonify({'error': '分類名稱不能為空'}), 400

    existing = Category.query.filter(Category.name == new_name, Category.id != cat_id).first()
    if existing:
        return jsonify({'error': f'分類「{new_name}」已存在'}), 400

    cat.name = new_name
    if 'sort_order' in data:
        cat.sort_order = int(data['sort_order'])
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/categories/<int:cat_id>', methods=['DELETE'])
@admin_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    dish_count = Dish.query.filter_by(category_id=cat_id).count()
    if dish_count > 0:
        return jsonify({'error': f'分類「{cat.name}」下有 {dish_count} 個菜式，無法刪除。請先將菜式移走或刪除。'}), 400
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'success': True, 'message': f'分類「{cat.name}」已刪除'})


@app.route('/api/admin/dishes', methods=['GET'])
@admin_required
def get_dishes():
    dishes = Dish.query.order_by(Dish.id.desc()).all()
    result = []
    for d in dishes:
        result.append({
            'id': d.id,
            'name': d.name,
            'category_id': d.category_id,
            'category_name': d.category.name if d.category else '',
            'price': d.price,
            'description': d.description,
            'image_path': d.image_path,
            'stock': d.stock,
            'is_available': d.is_available
        })
    return jsonify(result)


@app.route('/api/admin/dishes', methods=['POST'])
@admin_required
def add_dish():
    data = request.form if request.form else request.get_json()
    if not data:
        return jsonify({'error': '數據不能為空'}), 400

    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '菜式名稱不能為空'}), 400

    dish = Dish(
        name=name,
        category_id=int(data.get('category_id', 1)),
        price=float(data.get('price', 0)),
        description=data.get('description', ''),
        stock=int(data.get('stock', 0)),
        is_available=data.get('is_available', 'true') in [True, 'true', '1']
    )

    # 處理圖片上傳
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            filename = f"dish_{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            dish.image_path = f"/static/uploads/{filename}"

    db.session.add(dish)
    db.session.commit()
    return jsonify({'success': True, 'dish_id': dish.id})


@app.route('/api/admin/dishes/<int:dish_id>', methods=['PUT'])
@admin_required
def update_dish(dish_id):
    dish = Dish.query.get_or_404(dish_id)

    # 兼容 JSON 和 FormData 兩種請求
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    dish.name = data.get('name', dish.name)
    dish.category_id = int(data.get('category_id', dish.category_id))
    dish.price = float(data.get('price', dish.price))
    dish.description = data.get('description', dish.description)
    dish.stock = int(data.get('stock', dish.stock))
    dish.is_available = str(data.get('is_available', '')).lower() in ('true', '1', 'on')

    # 處理圖片上傳
    if 'image' in request.files:
        img = request.files['image']
        if img and img.filename:
            filename = f"dish_{dish_id}_{int(time.time())}{os.path.splitext(img.filename)[1]}"
            img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
            os.makedirs(img_dir, exist_ok=True)
            img_path = os.path.join(img_dir, filename)
            img.save(img_path)
            # 刪除舊圖片
            if dish.image_path:
                old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), dish.image_path.lstrip('/'))
                if os.path.exists(old_path):
                    os.remove(old_path)
            dish.image_path = f'/static/uploads/{filename}'

    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/dishes/<int:dish_id>', methods=['DELETE'])
@admin_required
def delete_dish(dish_id):
    dish = Dish.query.get_or_404(dish_id)

    # 檢查是否有歷史訂單關聯（order_items 中有 dish_id 引用）
    has_orders = OrderItem.query.filter_by(dish_id=dish_id).count() > 0

    if has_orders:
        # 有歷史訂單 → 軟刪除（下架）
        dish.is_available = False
        db.session.commit()
        return jsonify({
            'success': True,
            'action': 'soft_delete',
            'message': f'「{dish.name}」存在歷史訂單記錄，已下架處理（軟刪除）'
        })
    else:
        # 無歷史訂單 → 硬刪除
        if dish.image_path:
            img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), dish.image_path.lstrip('/'))
            if os.path.exists(img_path):
                os.remove(img_path)
        db.session.delete(dish)
        db.session.commit()
        return jsonify({
            'success': True,
            'action': 'hard_delete',
            'message': f'「{dish.name}」已永久刪除'
        })


# ======================== 套餐管理 API ========================

@app.route('/api/admin/combos', methods=['GET'])
@admin_required
def get_combos():
    combos = Combo.query.order_by(Combo.id.desc()).all()
    result = []
    for c in combos:
        dishes = [{'dish_id': ci.dish_id, 'dish_name': ci.dish.name} for ci in c.items]
        result.append({
            'id': c.id,
            'name': c.name,
            'price': c.price,
            'description': c.description,
            'image_path': c.image_path,
            'is_available': c.is_available,
            'dishes': dishes
        })
    return jsonify(result)


@app.route('/api/admin/combos/<int:combo_id>', methods=['GET'])
@admin_required
def get_combo(combo_id):
    c = Combo.query.get_or_404(combo_id)
    dishes = [{'dish_id': ci.dish_id, 'dish_name': ci.dish.name} for ci in c.items]
    return jsonify({
        'id': c.id,
        'name': c.name,
        'price': c.price,
        'description': c.description,
        'image_path': c.image_path,
        'is_available': c.is_available,
        'dishes': dishes
    })


@app.route('/api/admin/combos', methods=['POST'])
@admin_required
def add_combo():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '套餐名稱不能為空'}), 400

    combo = Combo(
        name=name,
        price=float(data.get('price', 0)),
        description=data.get('description', ''),
        is_available=str(data.get('is_available', 'true')).lower() in ('true', '1', 'on')
    )

    # 處理圖片上傳
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            filename = f"combo_{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            combo.image_path = f"/static/uploads/{filename}"

    db.session.add(combo)
    db.session.flush()

    # 處理關聯菜式
    dish_ids = data.get('dish_ids')
    if dish_ids:
        if isinstance(dish_ids, str):
            import json
            dish_ids = json.loads(dish_ids)
        if isinstance(dish_ids, list) and len(dish_ids) >= 2:
            for did in dish_ids[:2]:
                dish = Dish.query.get(int(did))
                if dish:
                    db.session.add(ComboItem(combo_id=combo.id, dish_id=dish.id))

    db.session.commit()
    return jsonify({'success': True, 'combo_id': combo.id})


@app.route('/api/admin/combos/<int:combo_id>', methods=['PUT'])
@admin_required
def update_combo(combo_id):
    combo = Combo.query.get_or_404(combo_id)

    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    combo.name = data.get('name', combo.name)
    combo.price = float(data.get('price', combo.price))
    combo.description = data.get('description', combo.description)
    combo.is_available = str(data.get('is_available', '')).lower() in ('true', '1', 'on')

    # 處理圖片上傳
    if 'image' in request.files:
        img = request.files['image']
        if img and img.filename:
            filename = f"combo_{combo_id}_{int(time.time())}{os.path.splitext(img.filename)[1]}"
            img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
            os.makedirs(img_dir, exist_ok=True)
            img_path = os.path.join(img_dir, filename)
            img.save(img_path)
            if combo.image_path:
                old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), combo.image_path.lstrip('/'))
                if os.path.exists(old_path):
                    os.remove(old_path)
            combo.image_path = f'/static/uploads/{filename}'

    # 處理關聯菜式
    dish_ids = data.get('dish_ids')
    if dish_ids is not None:
        if isinstance(dish_ids, str):
            import json
            dish_ids = json.loads(dish_ids)
        # 清除舊關聯
        ComboItem.query.filter_by(combo_id=combo.id).delete()
        if isinstance(dish_ids, list) and len(dish_ids) >= 2:
            for did in dish_ids[:2]:
                dish = Dish.query.get(int(did))
                if dish:
                    db.session.add(ComboItem(combo_id=combo.id, dish_id=dish.id))

    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/combos/<int:combo_id>', methods=['DELETE'])
@admin_required
def delete_combo(combo_id):
    combo = Combo.query.get_or_404(combo_id)
    # 刪除關聯
    ComboItem.query.filter_by(combo_id=combo.id).delete()
    # 刪除圖片
    if combo.image_path:
        img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), combo.image_path.lstrip('/'))
        if os.path.exists(img_path):
            os.remove(img_path)
    db.session.delete(combo)
    db.session.commit()
    return jsonify({'success': True, 'message': f'套餐「{combo.name}」已刪除'})


@app.route('/api/admin/tables', methods=['GET'])
@admin_required
def get_tables():
    tables = Table.query.order_by(Table.table_number).all()
    result = []
    for t in tables:
        qr_data, url = generate_qr_code(t.table_number)
        
        # 獲取檯號狀態：只檢查是否有活躍訂單（pending/confirmed）
        active_order = Order.query.filter(
            Order.table_id == t.id,
            Order.status.in_(['pending', 'confirmed'])
        ).order_by(Order.created_at.desc()).first()
        
        status = '閒置'
        if active_order:
            if active_order.status == 'pending':
                status = '下單'
            elif active_order.status == 'confirmed':
                status = '確認'
        # 結賬後沒有活躍訂單，狀態就是"閒置"，不再显示"結賬"狀態
        
        result.append({
            'id': t.id,
            'table_number': t.table_number,
            'qr_code': qr_data,
            'order_url': url,
            'status': status
        })
    return jsonify(result)


@app.route('/api/admin/tables', methods=['POST'])
@admin_required
def add_table():
    data = request.get_json()
    table_number = data.get('table_number', '').strip()
    if not table_number:
        return jsonify({'error': '檯號不能為空'}), 400

    if Table.query.filter_by(table_number=table_number).first():
        return jsonify({'error': f'檯號「{table_number}」已存在'}), 400

    table = Table(table_number=table_number)
    db.session.add(table)
    db.session.commit()

    qr_data, url = generate_qr_code(table.table_number)
    return jsonify({'success': True, 'table': {
        'id': table.id,
        'table_number': table.table_number,
        'qr_code': qr_data,
        'order_url': url
    }})


@app.route('/api/admin/tables/batch', methods=['POST'])
@admin_required
def batch_add_tables():
    """批量生成檯號，格式 1001-1012"""
    data = request.get_json()
    range_str = data.get('range', '').strip()
    if not range_str or '-' not in range_str:
        return jsonify({'error': '格式錯誤，請輸入如 1001-1012'}), 400
    
    parts = range_str.split('-')
    if len(parts) != 2:
        return jsonify({'error': '格式錯誤，請輸入如 1001-1012'}), 400
    
    try:
        start = int(parts[0])
        end = int(parts[1])
    except ValueError:
        return jsonify({'error': '檯號必須為數字'}), 400
    
    if start > end:
        start, end = end, start
    
    if end - start > 200:
        return jsonify({'error': '單次最多批量生成 200 個檯號'}), 400
    
    created = []
    skipped = []
    for num in range(start, end + 1):
        tn = str(num)
        if Table.query.filter_by(table_number=tn).first():
            skipped.append(tn)
            continue
        table = Table(table_number=tn)
        db.session.add(table)
        db.session.flush()
        qr_data, url = generate_qr_code(table.table_number)
        created.append({
            'id': table.id,
            'table_number': table.table_number,
            'qr_code': qr_data,
            'order_url': url,
            'status': '閒置',
            'last_order_time': None
        })
    
    db.session.commit()
    return jsonify({
        'success': True,
        'created': created,
        'skipped': skipped,
        'created_count': len(created),
        'skipped_count': len(skipped)
    })


@app.route('/api/admin/tables/<int:table_id>', methods=['DELETE'])
@admin_required
def delete_table(table_id):
    table = Table.query.get_or_404(table_id)
    # 檢查是否有未完成訂單
    pending = Order.query.filter_by(table_id=table.id, status='pending').count()
    if pending > 0:
        return jsonify({'error': f'該檯號有 {pending} 個未完成訂單，無法刪除'}), 400
    db.session.delete(table)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/orders', methods=['GET'])
@admin_required
def get_orders():
    status = request.args.get('status', '')
    query = Order.query
    if status:
        query = query.filter_by(status=status)
    orders = query.order_by(Order.created_at.desc()).all()

    result = []
    for o in orders:
        items = [{
            'dish_name': i.dish_name,
            'quantity': i.quantity,
            'unit_price': i.unit_price
        } for i in o.items]
        result.append({
            'id': o.id,
            'table_number': o.table.table_number if o.table else '',
            'status': o.status,
            'total_price': o.total_price,
            'remark': o.remark,
            'items': items,
            'created_at': o.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    return jsonify(result)


@app.route('/api/admin/orders/<int:order_id>/status', methods=['PUT'])
@admin_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    data = request.get_json()
    status = data.get('status', '')
    if status not in ['pending', 'confirmed', 'completed', 'cancelled']:
        return jsonify({'error': '無效狀態'}), 400
    order.status = status
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/table/<int:table_id>/checkout', methods=['POST'])
def table_checkout(table_id):
    """檯號結賬：将所有该桌订单標記為已完成，並返回重置狀態"""
    table = Table.query.get_or_404(table_id)
    
    # 找到该桌所有未完成订单
    active_orders = Order.query.filter(
        Order.table_id == table.id,
        Order.status.in_(['pending', 'confirmed'])
    ).all()
    
    for order in active_orders:
        order.status = 'completed'
    
    db.session.commit()
    return jsonify({
        'success': True,
        'message': f'檯號 {table.table_number} 已結賬，共完成 {len(active_orders)} 个订单',
        'table_reset': True,
        'table_number': table.table_number
    })


@app.route('/api/admin/reports/daily', methods=['GET'])
@admin_required
def get_daily_report():
    """獲取每日營業額統計"""
    date_str = request.args.get('date')
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': '日期格式錯誤，請使用 YYYY-MM-DD'}), 400
    else:
        target_date = datetime.now().date()
    
    # 查询当天的订单
    orders = Order.query.filter(
        db.func.date(Order.created_at) == target_date,
        Order.status == 'completed'  # 只統計已完成的訂單
    ).all()
    
    total_amount = sum(o.total_price for o in orders)
    order_count = len(orders)
    dish_count = sum(len(o.items) for o in orders)
    
    # 按小時統計
    hourly_stats = {}
    for o in orders:
        hour = o.created_at.hour
        if hour not in hourly_stats:
            hourly_stats[hour] = {'amount': 0, 'orders': 0}
        hourly_stats[hour]['amount'] += o.total_price
        hourly_stats[hour]['orders'] += 1
    
    return jsonify({
        'date': target_date.strftime('%Y-%m-%d'),
        'total_amount': total_amount,
        'order_count': order_count,
        'dish_count': dish_count,
        'hourly_stats': hourly_stats,
        'orders': [{
            'id': o.id,
            'table_number': o.table.table_number if o.table else '',
            'total_price': o.total_price,
            'created_at': o.created_at.strftime('%H:%M:%S')
        } for o in orders]
    })


@app.route('/api/admin/reports/monthly', methods=['GET'])
@admin_required
def get_monthly_report():
    """獲取月度營業額統計"""
    year = request.args.get('year', datetime.now().year)
    month = request.args.get('month', datetime.now().month)
    
    try:
        year = int(year)
        month = int(month)
    except ValueError:
        return jsonify({'error': '年份和月份必须為數字'}), 400
    
    # 查询该月的订单
    orders = Order.query.filter(
        db.func.extract('year', Order.created_at) == year,
        db.func.extract('month', Order.created_at) == month,
        Order.status == 'completed'
    ).all()
    
    # 按天統計
    daily_stats = {}
    for o in orders:
        day = o.created_at.day
        if day not in daily_stats:
            daily_stats[day] = {'amount': 0, 'orders': 0, 'dishes': 0}
        daily_stats[day]['amount'] += o.total_price
        daily_stats[day]['orders'] += 1
        daily_stats[day]['dishes'] += len(o.items)
    
    total_amount = sum(o.total_price for o in orders)
    total_orders = len(orders)
    total_dishes = sum(len(o.items) for o in orders)
    
    # 計算上個月數據用於對比
    prev_month = month - 1
    prev_year = year
    if prev_month == 0:
        prev_month = 12
        prev_year = year - 1
    
    prev_orders = Order.query.filter(
        db.func.extract('year', Order.created_at) == prev_year,
        db.func.extract('month', Order.created_at) == prev_month,
        Order.status == 'completed'
    ).all()
    
    prev_amount = sum(o.total_price for o in prev_orders)
    if prev_amount > 0:
        growth_rate = ((total_amount - prev_amount) / prev_amount) * 100
    else:
        growth_rate = 100 if total_amount > 0 else 0
    
    return jsonify({
        'year': year,
        'month': month,
        'total_amount': total_amount,
        'total_orders': total_orders,
        'total_dishes': total_dishes,
        'daily_stats': daily_stats,
        'prev_month': {
            'year': prev_year,
            'month': prev_month,
            'amount': prev_amount,
            'orders': len(prev_orders)
        },
        'growth_rate': round(growth_rate, 2)
    })


# ======================== 打印小票 ========================

@app.route('/print/order/<int:order_id>')
def print_order(order_id):
    """根據訂單 ID 渲染打印小票頁面"""
    order = Order.query.get_or_404(order_id)
    table = order.table
    items = [{
        'dish_name': i.dish_name,
        'quantity': i.quantity,
        'unit_price': i.unit_price
    } for i in order.items]
    order_time = order.created_at.strftime('%Y-%m-%d %H:%M:%S')
    return render_template('print_receipt.html',
                          order=order,
                          table_number=table.table_number if table else '',
                          items=items,
                          order_time=order_time)


# ======================== 靜態文件 ========================

@app.route('/static/qrcodes/<filename>')
def serve_qrcode(filename):
    return send_from_directory(app.config['QR_FOLDER'], filename)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
