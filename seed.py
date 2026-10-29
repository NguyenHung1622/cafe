"""Nạp dữ liệu mẫu: 5 nhóm, 27 món, 6 khách hàng, ~300 đơn hàng 30 ngày gần nhất.
Chạy:  python seed.py      (xóa dữ liệu cũ của database trong DB_NAME rồi nạp lại)
"""
import random
from datetime import datetime, timedelta, timezone

import db as database
from db import categories, customers, menu, orders, slugify

CATS = [  # _id dạng chuỗi dễ đọc (tham chiếu từ menu_items.category)
    ("ca-phe", "Cà phê", "#6f4e37", 1),
    ("tra", "Trà & trà sữa", "#c98a3b", 2),
    ("sinh-to", "Sinh tố & nước ép", "#e58a3a", 3),
    ("da-xay", "Đá xay", "#7aa35b", 4),
    ("banh", "Bánh ngọt", "#d9a066", 5),
]
TOP_DRINK = [("Trân châu đen", 8000), ("Thạch dừa", 7000), ("Kem cheese", 12000), ("Pudding trứng", 9000)]
TOP_COFFEE = [("Shot espresso", 10000), ("Kem sữa", 8000), ("Thạch cà phê", 7000)]
ING = {
    "ca-phe": [("Cà phê hạt", 18, "g"), ("Nước", 60, "ml")],
    "tra": [("Trà", 5, "g"), ("Đường", 20, "g")],
    "sinh-to": [("Trái cây tươi", 150, "g"), ("Sữa đặc", 30, "ml")],
    "da-xay": [("Đá", 200, "g"), ("Sữa tươi", 100, "ml")],
    "banh": [("Bột mì", 80, "g"), ("Bơ", 30, "g")],
}
PAIRS = {"ca-phe": ["croissant-bo", "tiramisu"], "tra": ["cookie-socola", "cheesecake-chanh-day"],
         "sinh-to": ["banh-mi-que-pate", "cookie-socola"], "da-xay": ["cookie-socola", "croissant-bo"],
         "banh": ["ca-phe-sua-da", "bac-xiu"]}

# (tên, nhóm, mô tả, [(size, giá)], tồn kho nếu là bánh)
DRINKS = [
    ("Cà phê đen đá", "ca-phe", "Đậm đà, đắng nhẹ, hậu ngọt.", [("S", 25000), ("M", 29000)]),
    ("Cà phê sữa đá", "ca-phe", "Cà phê phin pha sữa đặc, món bán chạy nhất.", [("S", 29000), ("M", 35000), ("L", 39000)]),
    ("Bạc xỉu", "ca-phe", "Nhiều sữa, ít cà phê, ngọt dịu.", [("S", 32000), ("M", 38000)]),
    ("Cà phê muối", "ca-phe", "Lớp kem muối béo mặn trên nền cà phê.", [("M", 39000), ("L", 45000)]),
    ("Espresso", "ca-phe", "Một shot nguyên chất.", [("Single", 35000), ("Double", 45000)]),
    ("Americano", "ca-phe", "Espresso pha loãng với nước nóng.", [("M", 39000), ("L", 45000)]),
    ("Cappuccino", "ca-phe", "Espresso, sữa nóng và lớp bọt dày.", [("M", 45000), ("L", 52000)]),
    ("Latte", "ca-phe", "Espresso với sữa tươi mềm mịn.", [("M", 45000), ("L", 52000)]),
    ("Cold brew cam sả", "ca-phe", "Ủ lạnh 18 giờ, thơm cam sả.", [("M", 49000), ("L", 55000)]),
    ("Trà đào cam sả", "tra", "Trà đen, đào miếng, cam và sả tươi.", [("S", 39000), ("M", 45000), ("L", 52000)]),
    ("Trà vải", "tra", "Trà hoa nhài với vải thiều.", [("M", 42000), ("L", 48000)]),
    ("Trà sữa trân châu", "tra", "Trà sữa béo ngậy với trân châu đen dẻo.", [("M", 38000), ("L", 44000)]),
    ("Trà sữa matcha", "tra", "Matcha Nhật Bản và sữa tươi.", [("M", 45000), ("L", 52000)]),
    ("Sinh tố bơ", "sinh-to", "Bơ sáp xay sữa đặc, sánh mịn.", [("M", 45000), ("L", 52000)]),
    ("Sinh tố xoài", "sinh-to", "Xoài cát chín, vị chua ngọt.", [("M", 42000), ("L", 48000)]),
    ("Sinh tố dâu", "sinh-to", "Dâu tươi xay cùng sữa chua.", [("M", 45000), ("L", 52000)]),
    ("Nước cam ép", "sinh-to", "100% cam vắt, không đường.", [("M", 40000), ("L", 46000)]),
    ("Matcha đá xay", "da-xay", "Matcha xay đá, phủ kem tươi.", [("M", 50000), ("L", 57000)]),
    ("Cookie đá xay", "da-xay", "Bánh Oreo xay cùng kem sữa.", [("M", 52000), ("L", 59000)]),
    ("Cacao đá xay", "da-xay", "Cacao đậm vị, béo ngọt.", [("M", 48000), ("L", 55000)]),
]
BAKERY = [
    ("Tiramisu", "banh", "Bánh Ý vị cà phê và mascarpone.", [("Phần", 45000, 6)]),
    ("Croissant bơ", "banh", "Nướng mới mỗi sáng, vỏ giòn tan.", [("Cái", 35000, 4)]),
    ("Bánh mì que pate", "banh", "Vỏ giòn, nhân pate thơm béo.", [("Cái", 20000, 20)]),
    ("Cheesecake chanh dây", "banh", "Phô mai mềm, chua nhẹ chanh dây.", [("Phần", 48000, 8)]),
    ("Cookie socola", "banh", "Cookie mềm với chip socola đen.", [("Cái", 25000, 15)]),
    ("Bông lan trứng muối", "banh", "Bông lan mềm, sốt trứng muối.", [("Phần", 39000, 10)]),
    ("Bánh flan caramel", "banh", "Flan mịn, caramel đắng nhẹ.", [("Hũ", 22000, 12)]),
]
NAMES = ["Nguyễn Văn An", "Trần Thị Bình", "Lê Minh Cường", "Phạm Thanh Dung", "Hoàng Quốc Huy", "Võ Thị Lan"]
PHONES = ["0901234501", "0901234502", "0901234503", "0901234504", "0901234505", "0901234506"]
COMMENTS = ["Rất ngon, sẽ quay lại!", "Vị vừa miệng, phục vụ nhanh.", "Hơi ngọt với mình nhưng ổn.",
            "Đáng tiền, không gian đẹp.", "Món yêu thích của mình."]


def make_item(name, cat, desc, vars_, tracked):
    slug = slugify(name)
    variants = [{"sku": f"{slug}-{slugify(v[0])}", "size": v[0], "price": v[1],
                 "stock": v[2] if tracked else None} for v in vars_]
    return {
        "slug": slug, "name": name, "category": cat, "description": desc,
        "price": min(v["price"] for v in variants), "variants": variants,
        "toppings": [] if tracked else [{"name": n, "price": p} for n, p in (TOP_COFFEE if cat == "ca-phe" else TOP_DRINK)],
        "ingredients": [{"name": n, "qty": q, "unit": u} for n, q, u in ING[cat]],
        "tags": [cat.replace("-", " "), name.lower()], "pairsWith": [p for p in PAIRS[cat] if p != slug],
        "trackStock": tracked, "customizable": not tracked and cat != "banh",
        "available": True, "sold": 0, "rating": {"avg": 0, "count": 0}, "reviews": [],
    }


def run(n_orders=300, quiet=False):
    database.reset()
    categories.insert_many([{"_id": i, "name": n, "color": c, "order": o} for i, n, c, o in CATS])

    items = [make_item(n, c, d, v, False) for n, c, d, v in DRINKS]
    items += [make_item(n, c, d, v, True) for n, c, d, v in BAKERY]
    now = datetime.now(timezone.utc)
    for it in items:   # vài đánh giá mẫu
        k = random.choice([0, 0, 1, 2, 3])
        stars = [random.choice([4, 5, 5, 5, 3]) for _ in range(k)]
        it["reviews"] = [{"name": random.choice(NAMES), "stars": s, "comment": random.choice(COMMENTS),
                          "at": now - timedelta(days=random.randint(1, 20))} for s in stars]
        it["rating"] = {"avg": round(sum(stars) / k, 1) if k else 0, "count": k}
    menu.insert_many(items)
    items = list(menu.find())

    custs = [{"name": n, "phone": p, "points": 0, "addresses": ["12 Nguyễn Huệ, Quận 1, TP.HCM"],
              "createdAt": now - timedelta(days=40)} for n, p in zip(NAMES, PHONES)]
    ids = customers.insert_many(custs).inserted_ids
    cust_docs = list(customers.find())

    batch, sold, points = [], {}, {}
    for i in range(n_orders):
        created = now - timedelta(days=random.random() * 30, minutes=random.randint(0, 600))
        c = random.choice(cust_docs)
        lines, subtotal = [], 0
        for it in random.sample(items, random.randint(1, 4)):
            var, qty = random.choice(it["variants"]), random.randint(1, 3)
            tops = random.sample(it["toppings"], random.randint(0, min(2, len(it["toppings"])))) if it["customizable"] else []
            unit = var["price"] + sum(t["price"] for t in tops)
            lines.append({"itemId": it["_id"], "slug": it["slug"], "sku": var["sku"], "name": it["name"],
                          "category": it["category"], "variant": var["size"], "toppings": tops,
                          "sugar": random.choice([30, 50, 70, 100]) if it["customizable"] else None,
                          "ice": random.choice([0, 50, 100]) if it["customizable"] else None,
                          "note": "", "price": unit, "qty": qty, "tracked": it["trackStock"]})
            subtotal += unit * qty
        typ = random.choice(["dine_in", "dine_in", "takeaway", "delivery"])
        ship = 15000 if typ == "delivery" and subtotal < 150000 else 0
        age_h = (now - created).total_seconds() / 3600
        if age_h > 24:
            final = random.choices(["completed", "cancelled"], [92, 8])[0]
        else:
            final = random.choice(["pending", "preparing", "ready", "completed"])
        path = ["pending", "preparing", "ready", "completed"]
        hist = [{"status": "pending", "at": created}]
        if final == "cancelled":
            hist.append({"status": "cancelled", "at": created + timedelta(minutes=5)})
        else:
            for k, s in enumerate(path[1:path.index(final) + 1], 1):
                hist.append({"status": s, "at": created + timedelta(minutes=4 * k)})
        total = subtotal + ship
        if final != "cancelled":
            for l in lines:
                sold[l["itemId"]] = sold.get(l["itemId"], 0) + l["qty"]
        if final == "completed":
            points[c["_id"]] = points.get(c["_id"], 0) + total // 10000
        batch.append({
            "code": f"CF{created:%y%m%d}{i:04d}", "customerId": c["_id"],
            "customer": {"name": c["name"], "phone": c["phone"]}, "type": typ,
            "tableNumber": random.randint(1, 20) if typ == "dine_in" else None,
            "address": c["addresses"][0] if typ == "delivery" else None,
            "items": lines, "subtotal": subtotal, "shippingFee": ship, "total": total,
            "paymentMethod": random.choice(["cash", "momo", "transfer"]), "note": "",
            "status": final, "statusHistory": hist, "createdAt": created})
    orders.insert_many(batch)
    for item_id, q in sold.items():
        menu.update_one({"_id": item_id}, {"$inc": {"sold": q}})
    for cid, p in points.items():
        customers.update_one({"_id": cid}, {"$inc": {"points": p}})
    if not quiet:
        print(f"Xong! categories={categories.count_documents({})} menu_items={menu.count_documents({})} "
              f"customers={customers.count_documents({})} orders={orders.count_documents({})}")
        print("Database:", database.DB_NAME)


if __name__ == "__main__":
    run()
