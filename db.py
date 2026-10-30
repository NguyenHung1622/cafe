"""Kết nối MongoDB, schema validation ($jsonSchema) và chỉ mục."""
import os
import re
import unicodedata

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, TEXT, MongoClient

load_dotenv()
URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "cafe")

client = MongoClient(URI, serverSelectionTimeoutMS=10000, tz_aware=True)
db = client[DB_NAME]
categories = db.categories
menu = db.menu_items
customers = db.customers
orders = db.orders
tables = db.tables

NUM = ["int", "long", "double"]
MENU_SCHEMA = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["name", "slug", "category", "price", "variants"],
    "properties": {
        "price": {"bsonType": NUM, "minimum": 0},
        "specs": {"bsonType": "object"},
        "variants": {"bsonType": "array", "minItems": 1, "items": {
            "bsonType": "object", "required": ["sku", "size", "price"],
            "properties": {
                "price": {"bsonType": NUM, "minimum": 0},
                # stock >= 0: lớp bảo vệ cuối cùng, DB từ chối ghi kho âm
                "stock": {"bsonType": ["int", "long", "null"], "minimum": 0},
            }}},
    },
}}
ORDER_SCHEMA = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["code", "customer", "items", "total", "status"],
    "properties": {
        "total": {"bsonType": NUM, "minimum": 0},
        "status": {"enum": ["pending", "preparing", "ready", "completed", "cancelled"]},
        "items": {"bsonType": "array", "minItems": 1},
    },
}}


TABLE_SCHEMA = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["number", "seats", "status"],
    "properties": {
        "number": {"bsonType": ["int", "long"], "minimum": 1},
        "seats": {"bsonType": ["int", "long"], "minimum": 1, "maximum": 50},
        "status": {"enum": ["free", "occupied", "reserved", "disabled"]},
    },
}}


def slugify(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def ensure_schema():
    """Tạo collection + chỉ mục nếu chưa có (chạy lại nhiều lần vẫn an toàn)."""
    existing = set(db.list_collection_names())
    if "menu_items" not in existing:
        db.create_collection("menu_items", validator=MENU_SCHEMA)
    if "orders" not in existing:
        db.create_collection("orders", validator=ORDER_SCHEMA)
    if "tables" not in existing:
        db.create_collection("tables", validator=TABLE_SCHEMA)

    menu.create_index("slug", unique=True, name="slug_unique")
    menu.create_index("variants.sku", unique=True, name="sku_unique")          # multikey
    menu.create_index([("category", ASCENDING), ("price", ASCENDING)], name="category_price")
    menu.create_index("pairsWith", name="pairsWith_multikey")                  # multikey
    menu.create_index([("name", TEXT), ("tags", TEXT), ("description", TEXT)],
                      weights={"name": 10, "tags": 5, "description": 1},
                      default_language="none", name="text_search")
    customers.create_index("phone", unique=True, name="phone_unique")
    orders.create_index("code", unique=True, name="code_unique")
    orders.create_index([("customerId", ASCENDING), ("createdAt", DESCENDING)], name="customer_recent")
    orders.create_index([("status", ASCENDING), ("createdAt", DESCENDING)], name="status_recent")
    orders.create_index([("tableNumber", ASCENDING), ("status", ASCENDING)], name="table_status")
    tables.create_index("number", unique=True, name="number_unique")


def reset():
    for c in ["categories", "menu_items", "customers", "orders", "tables"]:
        db.drop_collection(c)
    ensure_schema()
