# -*- coding: utf-8 -*-
"""資料庫初始化與模型定義"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Table(db.Model):
    __tablename__ = 'tables'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    table_number = db.Column(db.String(20), unique=True, nullable=False)
    qr_code_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)

    orders = db.relationship('Order', backref='table', lazy=True)


class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    dishes = db.relationship('Dish', backref='category', lazy=True)


class Dish(db.Model):
    __tablename__ = 'dishes'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    price = db.Column(db.Float, nullable=False, default=0)
    description = db.Column(db.Text, default='')
    image_path = db.Column(db.String(500), default='')
    stock = db.Column(db.Integer, default=0)
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    table_id = db.Column(db.Integer, db.ForeignKey('tables.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending / confirmed / completed / cancelled
    total_price = db.Column(db.Float, default=0)
    remark = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)

    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')


class OrderItem(db.Model):
    __tablename__ = 'order_items'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    dish_id = db.Column(db.Integer, db.ForeignKey('dishes.id'), nullable=False)
    dish_name = db.Column(db.String(100))
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False, default=0)

    dish = db.relationship('Dish', backref='order_items')


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # 初始化預設分類
        if Category.query.count() == 0:
            default_categories = ['熱菜', '涼菜', '湯品', '飲品', '主食', '甜品']
            for i, name in enumerate(default_categories):
                db.session.add(Category(name=name, sort_order=i + 1))
            db.session.commit()
