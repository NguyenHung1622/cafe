"""Bean & Brew Café - website bán hàng + trang quản trị, dữ liệu lưu trong MongoDB.
Chạy:  uvicorn app:app --reload   ->  http://127.0.0.1:8000
"""
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo import ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError, WriteError

import db as database
from db import categories, customers, menu, orders, slugify

ADMIN_KEY = os.getenv("ADMIN_KEY", "admin123")
SHIPPING_FEE = 15000
FREE_SHIP_FROM = 150000
TABLES = 20
FLOW = {  # luồng trạng thái hợp lệ của đơn hàng
    "pending": ["preparing", "cancelled"],
    "preparing": ["ready", "cancelled"],
    "ready": ["completed", "cancelled"],
    "completed": [],
    "cancelled": [],
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.ensure_schema()
    yield


app = FastAPI(title="Bean & Brew Café", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


# ===================== Helpers =====================
def clean(x):
    """ObjectId / datetime -> JSON."""
    if isinstance(x, ObjectId):
        return str(x)
    if isinstance(x, datetime):
        return (x if x.tzinfo else x.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    return x


def require_admin(x_admin_key: str = Header(default="")):
    if not secrets.compare_digest(x_admin_key.encode(), ADMIN_KEY.encode()):
        raise HTTPException(401, "Sai mã quản trị")


def now_utc():
    return datetime.now(timezone.utc)


# ===================== Schemas =====================
class CartLine(BaseModel):
    sku: str
    qty: int = Field(ge=1, le=20)
    toppings: list[str] = []
    sugar: int | None = Field(None, ge=0, le=100)
    ice: int | None = Field(None, ge=0, le=100)
    note: str = Field("", max_length=200)


class CustomerIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(pattern=r"^0\d{9}$")


class OrderIn(BaseModel):
    customer: CustomerIn
    type: Literal["dine_in", "takeaway", "delivery"]
    tableNumber: int | None = Field(None, ge=1, le=TABLES)
    address: str | None = Field(None, max_length=200)
    paymentMethod: Literal["cash", "transfer", "momo"] = "cash"
    items: list[CartLine] = Field(min_length=1, max_length=30)
    note: str = Field("", max_length=300)


class ReviewIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    stars: int = Field(ge=1, le=5)
    comment: str = Field("", max_length=500)


class StatusIn(BaseModel):
    status: Literal["preparing", "ready", "completed", "cancelled"]


class VariantIn(BaseModel):
    size: str = Field(min_length=1, max_length=20)
    price: int = Field(gt=0)
    stock: int | None = Field(None, ge=0)


class ToppingIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    price: int = Field(ge=0)


class MenuIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    category: str
    description: str = Field("", max_length=300)
    variants: list[VariantIn] = Field(min_length=1, max_length=6)
    toppings: list[ToppingIn] = []
    tags: list[str] = []
    trackStock: bool = False
    customizable: bool = False


# ===================== Pages & config =====================
@app.get("/")
def home():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.get("/api/config")
def config():
    return {"shippingFee": SHIPPING_FEE, "freeShipFrom": FREE_SHIP_FROM, "tables": TABLES}


@app.get("/api/categories")
def list_categories():
    return clean(list(categories.find().sort("order", 1)))


# ===================== Thực đơn (khách hàng) =====================
SORTS = {
    "popular": [("sold", -1), ("name", 1)],
    "price_asc": [("price", 1), ("name", 1)],
    "price_desc": [("price", -1), ("name", 1)],
    "rating": [("rating.avg", -1), ("rating.count", -1)],
    "name": [("name", 1)],
}
LIST_PROJECTION = {"reviews": 0, "ingredients": 0}


@app.get("/api/menu")
def list_menu(q: str = "", category: str = "", maxPrice: int | None = Query(None, ge=0),
              sort: str = "popular", page: int = Query(1, ge=1), size: int = Query(12, ge=1, le=50)):
    base = {"available": True}
    if category:
        base["category"] = category
    if maxPrice:
        base["price"] = {"$lte": maxPrice}

    flt, use_text = dict(base), False
    if q.strip():
        flt["$text"] = {"$search": q.strip()}      # tìm toàn văn, không phân biệt dấu/hoa thường
        use_text = True
    total = menu.count_documents(flt)
    if q.strip() and total == 0:                   # không có kết quả toàn văn -> tìm theo tiền tố tên
        flt = {**base, "name": {"$regex": re.escape(q.strip()), "$options": "i"}}
        use_text = False
        total = menu.count_documents(flt)

    cur = menu.find(flt, LIST_PROJECTION)
    if use_text and sort == "popular":
        cur = cur.sort([("score", {"$meta": "textScore"})])
    else:
        cur = cur.sort(SORTS.get(sort, SORTS["popular"]))
    items = list(cur.skip((page - 1) * size).limit(size))
    return {"total": total, "page": page, "size": size, "items": clean(items)}


@app.get("/api/menu/{slug}")
def get_item(slug: str):
    item = menu.find_one({"slug": slug, "available": True})   # 1 document chứa toàn bộ thông tin
    if not item:
        raise HTTPException(404, "Không tìm thấy món")
    pairs = list(menu.find({"slug": {"$in": item.get("pairsWith", [])}, "available": True}, LIST_PROJECTION))
    return {"item": clean(item), "pairs": clean(pairs)}


@app.post("/api/menu/{slug}/reviews", status_code=201)
def add_review(slug: str, body: ReviewIn):
    review = {"name": body.name.strip(), "stars": body.stars, "comment": body.comment.strip(), "at": now_utc()}
    # Một lệnh update dạng pipeline: chèn đánh giá mới (giữ 20 cái mới nhất - Subset pattern)
    # và cập nhật điểm trung bình (Computed pattern). $literal: nội dung người dùng không bị hiểu là biểu thức.
    r = menu.update_one({"slug": slug}, [{"$set": {
        "reviews": {"$slice": [{"$concatArrays": [[{"$literal": review}], {"$ifNull": ["$reviews", []]}]}, 20]},
        "rating": {
            "avg": {"$round": [{"$divide": [
                {"$add": [{"$multiply": ["$rating.avg", "$rating.count"]}, body.stars]},
                {"$add": ["$rating.count", 1]}]}, 1]},
            "count": {"$add": ["$rating.count", 1]},
        },
    }}])
    if r.matched_count == 0:
        raise HTTPException(404, "Không tìm thấy món")
    return {"ok": True}


# ===================== Đặt hàng =====================
def restore_stock(taken):
    for sku, qty in taken:
        menu.update_one({"variants.sku": sku}, {"$inc": {"variants.$.stock": qty}})


def adjust_sold(lines, sign):
    ops = [UpdateOne({"_id": l["itemId"]}, {"$inc": {"sold": sign * l["qty"]}}) for l in lines]
    if ops:
        menu.bulk_write(ops, ordered=False)


def place_order(o: OrderIn):
    if o.type == "dine_in" and not o.tableNumber:
        raise HTTPException(400, "Vui lòng chọn số bàn")
    if o.type == "delivery" and not (o.address and o.address.strip()):
        raise HTTPException(400, "Vui lòng nhập địa chỉ giao hàng")

    taken = []  # (sku, qty) đã trừ kho - hoàn lại nếu bước sau thất bại
    try:
        lines, subtotal = [], 0
        for it in o.items:
            item = menu.find_one({"variants.sku": it.sku, "available": True}, {"reviews": 0})
            if not item:
                raise HTTPException(409, f"Món {it.sku} không tồn tại hoặc đã ngừng bán")
            var = next(v for v in item["variants"] if v["sku"] == it.sku)

            tops = []
            for tname in dict.fromkeys(it.toppings):
                t = next((x for x in item.get("toppings", []) if x["name"] == tname), None)
                if not t:
                    raise HTTPException(400, f"Topping '{tname}' không áp dụng cho {item['name']}")
                tops.append({"name": t["name"], "price": t["price"]})

            # Giá luôn lấy từ DB, bỏ qua mọi giá do trình duyệt gửi lên
            unit = var["price"] + sum(t["price"] for t in tops)

            if item.get("trackStock"):
                # Kiểm tra + trừ kho trong MỘT thao tác nguyên tử ($elemMatch + toán tử vị trí $)
                r = menu.update_one(
                    {"variants": {"$elemMatch": {"sku": it.sku, "stock": {"$gte": it.qty}}}},
                    {"$inc": {"variants.$.stock": -it.qty}})
                if r.modified_count == 0:
                    left = max(var.get("stock") or 0, 0)
                    raise HTTPException(409, f"{item['name']} ({var['size']}) không đủ hàng, chỉ còn {left}")
                taken.append((it.sku, it.qty))

            custom = item.get("customizable", False)
            lines.append({
                "itemId": item["_id"], "slug": item["slug"], "sku": it.sku, "name": item["name"],
                "category": item["category"], "variant": var["size"], "toppings": tops,
                "sugar": it.sugar if custom else None, "ice": it.ice if custom else None,
                "note": it.note.strip(), "price": unit, "qty": it.qty, "tracked": bool(item.get("trackStock")),
            })
            subtotal += unit * it.qty

        shipping = SHIPPING_FEE if (o.type == "delivery" and subtotal < FREE_SHIP_FROM) else 0
        now = now_utc()
        upd = {"$set": {"name": o.customer.name.strip()},
               "$setOnInsert": {"points": 0, "createdAt": now}}
        if o.type == "delivery":
            upd["$addToSet"] = {"addresses": o.address.strip()}
        cust = customers.find_one_and_update({"phone": o.customer.phone}, upd, upsert=True,
                                             return_document=ReturnDocument.AFTER)
        doc = {
            "code": "CF" + uuid.uuid4().hex[:8].upper(),
            "customerId": cust["_id"],
            "customer": {"name": o.customer.name.strip(), "phone": o.customer.phone},
            "type": o.type, "tableNumber": o.tableNumber if o.type == "dine_in" else None,
            "address": o.address.strip() if o.type == "delivery" else None,
            "items": lines, "subtotal": subtotal, "shippingFee": shipping, "total": subtotal + shipping,
            "paymentMethod": o.paymentMethod, "note": o.note.strip(),
            "status": "pending", "statusHistory": [{"status": "pending", "at": now}], "createdAt": now,
        }
        orders.insert_one(doc)
        adjust_sold(lines, +1)
        return doc
    except Exception:
        restore_stock(taken)
        raise


@app.post("/api/orders", status_code=201)
def create_order(body: OrderIn):
    return clean(place_order(body))


@app.get("/api/orders")
def track_orders(phone: str = Query(pattern=r"^0\d{9}$")):
    cust = customers.find_one({"phone": phone})
    if not cust:
        return {"customer": None, "orders": []}
    rows = list(orders.find({"customerId": cust["_id"]}).sort("createdAt", -1).limit(30))
    return {"customer": clean({"name": cust["name"], "points": cust.get("points", 0)}), "orders": clean(rows)}


# ===================== Quản trị =====================
@app.get("/api/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats():
    not_cancelled = {"status": {"$ne": "cancelled"}}
    since = now_utc() - timedelta(days=14)
    line_revenue = {"$sum": {"$multiply": ["$items.price", "$items.qty"]}}
    # $facet: nhiều báo cáo trên cùng collection orders, chạy song song trong 1 lần gọi
    facet = orders.aggregate([{"$facet": {
        "summary": [{"$match": not_cancelled},
                    {"$group": {"_id": None, "orders": {"$sum": 1}, "revenue": {"$sum": "$total"},
                                "avg": {"$avg": "$total"}}}],
        "byStatus": [{"$group": {"_id": "$status", "n": {"$sum": 1}}}],
        "byType": [{"$match": not_cancelled}, {"$group": {"_id": "$type", "n": {"$sum": 1}, "revenue": {"$sum": "$total"}}}],
        "byCategory": [{"$match": not_cancelled}, {"$unwind": "$items"},
                       {"$group": {"_id": "$items.category", "qty": {"$sum": "$items.qty"}, "revenue": line_revenue}},
                       {"$sort": {"revenue": -1}}],
        "topItems": [{"$match": not_cancelled}, {"$unwind": "$items"},
                     {"$group": {"_id": "$items.name", "qty": {"$sum": "$items.qty"}, "revenue": line_revenue}},
                     {"$sort": {"qty": -1}}, {"$limit": 5}],
        "byDay": [{"$match": {**not_cancelled, "createdAt": {"$gte": since}}},
                  {"$group": {"_id": {"$dateToString": {"format": "%d/%m", "date": "$createdAt",
                                                        "timezone": "Asia/Ho_Chi_Minh"}},
                              "revenue": {"$sum": "$total"}, "orders": {"$sum": 1}, "first": {"$min": "$createdAt"}}},
                  {"$sort": {"first": 1}}, {"$project": {"first": 0}}],
        "recent": [{"$sort": {"createdAt": -1}}, {"$limit": 8},
                   {"$lookup": {"from": "customers", "localField": "customerId", "foreignField": "_id", "as": "cust"}},
                   {"$project": {"code": 1, "total": 1, "status": 1, "type": 1, "createdAt": 1, "customer": 1,
                                 "points": {"$arrayElemAt": ["$cust.points", 0]}}}],
    }}]).next()
    low = list(menu.aggregate([
        {"$match": {"trackStock": True}}, {"$unwind": "$variants"},
        {"$match": {"variants.stock": {"$lte": 5}}},
        {"$project": {"_id": 0, "name": 1, "sku": "$variants.sku", "size": "$variants.size", "stock": "$variants.stock"}},
        {"$sort": {"stock": 1}}]))
    summary = facet["summary"][0] if facet["summary"] else {"orders": 0, "revenue": 0, "avg": 0}
    summary.pop("_id", None)
    facet["summary"] = summary
    facet["lowStock"] = low
    return clean(facet)


@app.get("/api/admin/orders", dependencies=[Depends(require_admin)])
def admin_orders(status: str = "", page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    flt = {"status": status} if status else {}
    total = orders.count_documents(flt)
    rows = list(orders.find(flt).sort("createdAt", -1).skip((page - 1) * size).limit(size))
    return {"total": total, "page": page, "size": size, "items": clean(rows), "flow": FLOW}


@app.patch("/api/admin/orders/{code}/status", dependencies=[Depends(require_admin)])
def update_status(code: str, body: StatusIn):
    order = orders.find_one({"code": code})
    if not order:
        raise HTTPException(404, "Không tìm thấy đơn")
    if body.status not in FLOW[order["status"]]:
        raise HTTPException(409, f"Không thể chuyển từ '{order['status']}' sang '{body.status}'")
    # Điều kiện status hiện tại trong bộ lọc: 2 quản trị viên bấm cùng lúc thì chỉ 1 người thành công
    upd = orders.find_one_and_update(
        {"code": code, "status": order["status"]},
        {"$set": {"status": body.status}, "$push": {"statusHistory": {"status": body.status, "at": now_utc()}}},
        return_document=ReturnDocument.AFTER)
    if not upd:
        raise HTTPException(409, "Đơn vừa được người khác cập nhật, hãy tải lại")
    if body.status == "cancelled":
        restore_stock([(l["sku"], l["qty"]) for l in upd["items"] if l.get("tracked")])
        adjust_sold(upd["items"], -1)
    if body.status == "completed":
        customers.update_one({"_id": upd["customerId"]}, {"$inc": {"points": upd["total"] // 10000}})
    return clean(upd)


def build_item(body: MenuIn, slug: str):
    if not categories.find_one({"_id": body.category}):
        raise HTTPException(400, "Nhóm món không tồn tại")
    variants = [{"sku": f"{slug}-{slugify(v.size)}", "size": v.size, "price": v.price,
                 "stock": v.stock if body.trackStock else None} for v in body.variants]
    if len({v["sku"] for v in variants}) != len(variants):
        raise HTTPException(400, "Kích cỡ bị trùng nhau")
    if body.trackStock and any(v["stock"] is None for v in variants):
        raise HTTPException(400, "Món theo dõi kho cần nhập số lượng tồn cho từng dòng")
    return {
        "name": body.name.strip(), "category": body.category, "description": body.description.strip(),
        "variants": variants, "price": min(v["price"] for v in variants),
        "toppings": [t.model_dump() for t in body.toppings], "tags": body.tags,
        "trackStock": body.trackStock, "customizable": body.customizable,
    }


@app.get("/api/admin/menu", dependencies=[Depends(require_admin)])
def admin_menu():
    return clean(list(menu.find({}, {"reviews": 0}).sort([("category", 1), ("name", 1)])))


@app.post("/api/admin/menu", status_code=201, dependencies=[Depends(require_admin)])
def admin_create_item(body: MenuIn):
    slug = slugify(body.name)
    doc = build_item(body, slug)
    doc.update({"slug": slug, "available": True, "rating": {"avg": 0, "count": 0}, "reviews": [],
                "sold": 0, "ingredients": [], "pairsWith": []})
    try:
        menu.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Tên món đã tồn tại")
    except WriteError:
        raise HTTPException(400, "Dữ liệu không đạt schema validation")
    return {"slug": slug}


@app.put("/api/admin/menu/{slug}", dependencies=[Depends(require_admin)])
def admin_update_item(slug: str, body: MenuIn):
    fields = build_item(body, slug)
    try:
        r = menu.update_one({"slug": slug}, {"$set": fields})
    except WriteError:
        raise HTTPException(400, "Dữ liệu không đạt schema validation")
    if r.matched_count == 0:
        raise HTTPException(404, "Không tìm thấy món")
    return {"ok": True}


@app.post("/api/admin/menu/{slug}/toggle", dependencies=[Depends(require_admin)])
def admin_toggle_item(slug: str):
    r = menu.update_one({"slug": slug}, [{"$set": {"available": {"$not": "$available"}}}])
    if r.matched_count == 0:
        raise HTTPException(404, "Không tìm thấy món")
    return {"ok": True}


@app.delete("/api/admin/menu/{slug}", dependencies=[Depends(require_admin)])
def admin_delete_item(slug: str):
    if menu.delete_one({"slug": slug}).deleted_count == 0:
        raise HTTPException(404, "Không tìm thấy món")
    return {"ok": True}
