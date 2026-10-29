"""Thực nghiệm chỉ mục: nạp 50.000 đơn vào collection orders_bench rồi so sánh
COLLSCAN và IXSCAN bằng explain("executionStats").   Chạy:  python explain_demo.py
(orders_bench tách riêng nên không ảnh hưởng dữ liệu của website)
"""
import random
from datetime import datetime, timedelta, timezone

import db as database

bench = database.db.orders_bench
N = 50000
# "cookie-socola" là món hiếm (trọng số 1/301) -> truy vấn Q2 chọn lọc, chỉ mục phát huy tác dụng
SLUGS = ["ca-phe-sua-da", "bac-xiu", "tra-dao-cam-sa", "tiramisu", "latte", "matcha-da-xay", "cookie-socola"]


def stages(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        if "stage" in node:
            out.append(node["stage"])
        for v in node.values():
            stages(v, out)
    elif isinstance(node, list):
        for v in node:
            stages(v, out)
    return out


def run(label, cmd):
    res = database.db.command("explain", cmd, verbosity="executionStats")
    st = res["executionStats"]
    plan = " > ".join(dict.fromkeys(stages(res["queryPlanner"]["winningPlan"])))
    print(f"  {label:<40} {plan:<22} docsExamined={st['totalDocsExamined']:<7} "
          f"returned={st['nReturned']:<6} {st['executionTimeMillis']} ms")


print(f"Nạp {N} đơn vào orders_bench ...")
bench.drop()
now = datetime.now(timezone.utc)
buf = []
for i in range(N):
    buf.append({"code": f"B{i}", "status": random.choice(["completed"] * 8 + ["pending", "cancelled"]),
                "createdAt": now - timedelta(days=random.random() * 365),
                "items": [{"slug": random.choices(SLUGS, [50] * 6 + [1])[0], "qty": random.randint(1, 3)} for _ in range(random.randint(1, 3))],
                "total": random.randint(2, 40) * 10000})
    if len(buf) == 5000:
        bench.insert_many(buf)
        buf = []

since = now - timedelta(days=7)
Q1 = {"find": "orders_bench", "filter": {"status": "pending", "createdAt": {"$gte": since}}, "sort": {"createdAt": -1}}
Q2 = {"find": "orders_bench", "filter": {"items.slug": "cookie-socola"}}

print("\nA. KHÔNG CÓ CHỈ MỤC")
run("Q1: đơn 'pending' trong 7 ngày gần nhất", Q1)
run("Q2: đơn có món 'cookie-socola' (mảng items)", Q2)

bench.create_index([("status", 1), ("createdAt", -1)], name="status_recent")
bench.create_index("items.slug", name="items_slug_multikey")
print("\nB. CÓ CHỈ MỤC  {status, createdAt:-1}  và  {items.slug} (multikey)")
run("Q1: đơn 'pending' trong 7 ngày gần nhất", Q1)
run("Q2: đơn có món 'cookie-socola' (mảng items)", Q2)

sizes = database.db.command("collStats", "orders_bench")["indexSizes"]
print("\nKích thước chỉ mục:", {k: f"{v // 1024} KB" for k, v in sizes.items()})
bench.drop()
print("Đã xóa orders_bench.")
