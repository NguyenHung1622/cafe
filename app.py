"""Bean & Brew Café - website bán hàng + trang quản trị, dữ liệu lưu trong MongoDB.
Chạy:  uvicorn app:app --reload   ->  http://127.0.0.1:8000
"""
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo import ReturnDocument, UpdateOne
from pymongo.errors import BulkWriteError, DuplicateKeyError, WriteError

from report_xlsx import build_workbook

import db as database
from db import categories, customers, menu, orders, slugify, tables

ADMIN_KEY = os.getenv("ADMIN_KEY", "admin123")
SHIPPING_FEE = 15000
FREE_SHIP_FROM = 150000
VN = timezone(timedelta(hours=7))   # giờ Việt Nam (không có giờ mùa hè)
TABLE_LABEL = {"free": "Trống", "occupied": "Có khách", "reserved": "Đã đặt trước", "disabled": "Tạm ngưng"}
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
    tableNumber: int | None = Field(None, ge=1, le=999)
    address: str | None = Field(None, max_length=200)
    paymentMethod: Literal["cash", "transfer", "momo"] = "cash"
    items: list[CartLine] = Field(min_length=1, max_length=30)
    note: str = Field("", max_length=300)


class TableCreate(BaseModel):
    number: int | None = Field(None, ge=1, le=999)   # bỏ trống = tự đánh số tiếp theo
    count: int = Field(1, ge=1, le=50)               # thêm nhiều bàn liên tiếp một lúc
    seats: int = Field(4, ge=1, le=50)
    area: str = Field("Tầng 1", min_length=1, max_length=40)


class TableUpdate(BaseModel):
    seats: int = Field(ge=1, le=50)
    area: str = Field(min_length=1, max_length=40)
    status: Literal["free", "occupied", "reserved", "disabled"]


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
    return {"shippingFee": SHIPPING_FEE, "freeShipFrom": FREE_SHIP_FROM}


@app.get("/api/categories")
def list_categories():
    return clean(list(categories.find().sort("order", 1)))


@app.get("/api/tables")
def public_tables():
    return clean(list(tables.find({}, {"_id": 0, "number": 1, "seats": 1, "area": 1, "status": 1}).sort("number", 1)))


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
    table_taken = None
    try:
        if o.type == "dine_in":
            # Chiếm bàn bằng 1 thao tác nguyên tử: chỉ khớp khi bàn đang "free" -> 2 khách không thể ngồi cùng 1 bàn
            r = tables.update_one({"number": o.tableNumber, "status": "free"}, {"$set": {"status": "occupied"}})
            if r.modified_count == 0:
                t = tables.find_one({"number": o.tableNumber})
                raise HTTPException(409, f"Bàn {o.tableNumber} không tồn tại" if not t else
                                    f"Bàn {o.tableNumber} hiện không trống ({TABLE_LABEL[t['status']].lower()})")
            table_taken = o.tableNumber
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
        if table_taken:
            tables.update_one({"number": table_taken, "status": "occupied"}, {"$set": {"status": "free"}})
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
    if body.status in ("completed", "cancelled") and upd["type"] == "dine_in" and upd.get("tableNumber"):
        tables.update_one({"number": upd["tableNumber"], "status": "occupied"}, {"$set": {"status": "free"}})
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


# ===================== Quản lý bàn =====================
ACTIVE = ["pending", "preparing", "ready"]


@app.get("/api/admin/tables", dependencies=[Depends(require_admin)])
def admin_tables():
    rows = list(tables.aggregate([
        {"$sort": {"number": 1}},
        # $lookup có pipeline: lấy đơn dùng tại quán đang phục vụ của từng bàn
        {"$lookup": {"from": "orders", "let": {"n": "$number"}, "pipeline": [
            {"$match": {"$expr": {"$and": [{"$eq": ["$tableNumber", "$$n"]}, {"$eq": ["$type", "dine_in"]},
                                           {"$in": ["$status", ACTIVE]}]}}},
            {"$sort": {"createdAt": -1}}, {"$limit": 1},
            {"$project": {"_id": 0, "code": 1, "total": 1, "status": 1, "createdAt": 1}}], "as": "current"}},
        {"$addFields": {"current": {"$arrayElemAt": ["$current", 0]}}},
    ]))
    return clean(rows)


@app.post("/api/admin/tables", status_code=201, dependencies=[Depends(require_admin)])
def admin_add_tables(body: TableCreate):
    if body.number is None:
        last = tables.find_one(sort=[("number", -1)])
        start = (last["number"] + 1) if last else 1
    else:
        start = body.number
    nums = list(range(start, start + body.count))
    if nums[-1] > 999:
        raise HTTPException(400, "Số bàn tối đa là 999")
    dup = [t["number"] for t in tables.find({"number": {"$in": nums}}, {"number": 1})]
    if dup:
        raise HTTPException(409, "Bàn đã tồn tại: " + ", ".join(map(str, sorted(dup))))
    now = now_utc()
    try:
        tables.insert_many([{"number": n, "name": f"Bàn {n}", "seats": body.seats, "area": body.area.strip(),
                             "status": "free", "createdAt": now} for n in nums], ordered=False)
    except BulkWriteError:
        raise HTTPException(409, "Số bàn bị trùng, hãy thử lại")
    return {"added": nums}


@app.put("/api/admin/tables/{number}", dependencies=[Depends(require_admin)])
def admin_update_table(number: int, body: TableUpdate):
    t = tables.find_one({"number": number})
    if not t:
        raise HTTPException(404, "Không tìm thấy bàn")
    if body.status == "occupied" and t["status"] != "occupied":
        raise HTTPException(409, "Trạng thái “Có khách” tự động đặt khi khách gọi món tại bàn")
    if t["status"] == "occupied" and body.status != "occupied":
        raise HTTPException(409, "Bàn đang có khách, hãy hoàn tất hoặc hủy đơn của bàn để giải phóng")
    tables.update_one({"number": number}, {"$set": {"seats": body.seats, "area": body.area.strip(), "status": body.status}})
    return {"ok": True}


@app.delete("/api/admin/tables/{number}", dependencies=[Depends(require_admin)])
def admin_delete_table(number: int):
    t = tables.find_one({"number": number})
    if not t:
        raise HTTPException(404, "Không tìm thấy bàn")
    if t["status"] == "occupied":
        raise HTTPException(409, "Bàn đang có khách, không thể xóa")
    tables.delete_one({"number": number})   # đơn cũ vẫn giữ nguyên số bàn (bản chụp)
    return {"ok": True}


# ===================== Báo cáo tuần / tháng =====================
WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def local_start(d: date) -> datetime:
    """00:00 giờ Việt Nam của ngày d, đổi sang UTC để truy vấn."""
    return datetime.combine(d, time.min, tzinfo=VN).astimezone(timezone.utc)


def period_bounds(period: str, d: date):
    if period == "week":                                    # thứ Hai -> Chủ nhật
        start = d - timedelta(days=d.weekday())
        end = start + timedelta(days=6)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)
        label = f"Tuần {start:%d/%m/%Y} – {end:%d/%m/%Y}"
        prev_label = f"Tuần {prev_start:%d/%m} – {prev_end:%d/%m/%Y}"
    else:                                                   # cả tháng chứa ngày d
        start = d.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        label = f"Tháng {start:%m/%Y}"
        prev_label = f"Tháng {prev_start:%m/%Y}"
    return start, end, prev_start, prev_end, label, prev_label


def build_report(period: str, d: date, with_orders=False):
    start, end, p_start, p_end, label, prev_label = period_bounds(period, d)
    lo, hi = local_start(start), local_start(end + timedelta(days=1))
    rng = {"createdAt": {"$gte": lo, "$lt": hi}}
    nc = {"status": {"$ne": "cancelled"}}
    line_rev = {"$sum": {"$multiply": ["$items.price", "$items.qty"]}}
    f = orders.aggregate([{"$match": rng}, {"$facet": {
        "summary": [{"$match": nc}, {"$group": {"_id": None, "orders": {"$sum": 1}, "revenue": {"$sum": "$total"},
                                                "customers": {"$addToSet": "$customerId"}}},
                    {"$project": {"_id": 0, "orders": 1, "revenue": 1, "customers": {"$size": "$customers"}}}],
        "cancelled": [{"$match": {"status": "cancelled"}}, {"$count": "n"}],
        "qty": [{"$match": nc}, {"$unwind": "$items"}, {"$group": {"_id": None, "qty": {"$sum": "$items.qty"}}}],
        "byDay": [{"$match": nc}, {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$createdAt", "timezone": "+07:00"}},
                                              "orders": {"$sum": 1}, "revenue": {"$sum": "$total"}}}],
        "byCategory": [{"$match": nc}, {"$unwind": "$items"},
                       {"$group": {"_id": "$items.category", "qty": {"$sum": "$items.qty"}, "revenue": line_rev}},
                       {"$sort": {"revenue": -1}}],
        "topItems": [{"$match": nc}, {"$unwind": "$items"},
                     {"$group": {"_id": "$items.name", "qty": {"$sum": "$items.qty"}, "revenue": line_rev}},
                     {"$sort": {"qty": -1, "revenue": -1}}, {"$limit": 10}],
        "byType": [{"$match": nc}, {"$group": {"_id": "$type", "orders": {"$sum": 1}, "revenue": {"$sum": "$total"}}}, {"$sort": {"revenue": -1}}],
        "byPayment": [{"$match": nc}, {"$group": {"_id": "$paymentMethod", "orders": {"$sum": 1}, "revenue": {"$sum": "$total"}}}, {"$sort": {"revenue": -1}}],
    }}]).next()
    prev = list(orders.aggregate([
        {"$match": {"createdAt": {"$gte": local_start(p_start), "$lt": local_start(p_end + timedelta(days=1))}, **nc}},
        {"$group": {"_id": None, "orders": {"$sum": 1}, "revenue": {"$sum": "$total"}}}]))
    s = f["summary"][0] if f["summary"] else {"orders": 0, "revenue": 0, "customers": 0}
    s["avg"] = round(s["revenue"] / s["orders"]) if s["orders"] else 0
    s["cancelled"] = f["cancelled"][0]["n"] if f["cancelled"] else 0
    s["itemsQty"] = f["qty"][0]["qty"] if f["qty"] else 0
    by_day_map = {x["_id"]: x for x in f["byDay"]}
    by_day = []
    for i in range((end - start).days + 1):                 # điền đủ các ngày, ngày không bán = 0
        day = start + timedelta(days=i)
        x = by_day_map.get(day.isoformat(), {})
        by_day.append({"date": f"{day:%d/%m/%Y}", "weekday": WEEKDAYS[day.weekday()],
                       "orders": x.get("orders", 0), "revenue": x.get("revenue", 0)})
    rep = {
        "period": {"type": period, "label": label, "start": start.isoformat(), "end": end.isoformat(),
                   "filename": f"bao-cao-{'tuan' if period == 'week' else 'thang'}-{start.isoformat()}_{end.isoformat()}"},
        "summary": s, "prev": {"label": prev_label, **(prev[0] if prev else {"orders": 0, "revenue": 0}), "_id": None},
        "byDay": by_day, "byCategory": f["byCategory"], "topItems": f["topItems"],
        "byType": f["byType"], "byPayment": f["byPayment"],
    }
    rep["prev"].pop("_id")
    if with_orders:
        rep["orders"] = list(orders.find(rng).sort("createdAt", 1).limit(5000))
    return rep


@app.get("/api/admin/report", dependencies=[Depends(require_admin)])
def admin_report(period: Literal["week", "month"] = "week", date_: str = Query("", alias="date"),
                 format: Literal["json", "xlsx"] = "json"):
    try:
        d = date.fromisoformat(date_) if date_ else datetime.now(VN).date()
    except ValueError:
        raise HTTPException(400, "Ngày không hợp lệ (định dạng YYYY-MM-DD)")
    if format == "xlsx":
        rep = build_report(period, d, with_orders=True)
        data = build_workbook(rep, categories={c["_id"]: c["name"] for c in categories.find()})
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{rep["period"]["filename"]}.xlsx"'})
    return clean(build_report(period, d))
