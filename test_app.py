"""Kiểm thử tự động (dùng database riêng 'cafe_test', chạy xong tự xóa).
Chạy:  python test_app.py
"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor

os.environ["DB_NAME"] = "cafe_test"
os.environ["ADMIN_KEY"] = "testkey"

from fastapi import HTTPException            # noqa: E402
from fastapi.testclient import TestClient    # noqa: E402

import db as database                        # noqa: E402
import seed                                  # noqa: E402
from app import OrderIn, app, place_order    # noqa: E402

ADMIN = {"X-Admin-Key": "testkey"}


def order(sku, qty=1, **kw):
    body = {"customer": {"name": "Khách Test", "phone": "0911111111"}, "type": "takeaway",
            "items": [{"sku": sku, "qty": qty, **kw.pop("line", {})}]}
    body.update(kw)
    return body


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.run(n_orders=60, quiet=True)
        cls.c = TestClient(app)
        cls.c.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None, None, None)
        database.client.drop_database("cafe_test")

    def stock(self, sku):
        item = database.menu.find_one({"variants.sku": sku})
        return next(v for v in item["variants"] if v["sku"] == sku)["stock"]

    def test01_filter_sort(self):
        d = self.c.get("/api/menu?category=ca-phe&sort=price_asc").json()
        self.assertTrue(d["items"])
        self.assertTrue(all(i["category"] == "ca-phe" for i in d["items"]))
        prices = [i["price"] for i in d["items"]]
        self.assertEqual(prices, sorted(prices))

    def test02_text_search_no_diacritics(self):
        d = self.c.get("/api/menu?q=ca phe sua").json()
        self.assertIn("ca-phe-sua-da", [i["slug"] for i in d["items"]])
        d = self.c.get("/api/menu?q=Tiram").json()          # tiền tố -> fallback regex
        self.assertIn("tiramisu", [i["slug"] for i in d["items"]])

    def test03_detail_pairs(self):
        d = self.c.get("/api/menu/ca-phe-sua-da").json()
        self.assertIn("variants", d["item"])
        self.assertTrue(d["pairs"])
        self.assertEqual(self.c.get("/api/menu/khong-co").status_code, 404)

    def test04_price_from_db_not_client(self):
        r = self.c.post("/api/orders", json=order("ca-phe-sua-da-m", 2, line={"price": 1},
                                                   **{"customer": {"name": "Khách Test", "phone": "0911111111"}}))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["total"], 70000)

    def test05_toppings_and_delivery_fee(self):
        r = self.c.post("/api/orders", json=order("tra-sua-tran-chau-m", 1, type="delivery", address="1 Lê Lợi",
                                                   line={"toppings": ["Trân châu đen"]}))
        d = r.json()
        self.assertEqual((d["subtotal"], d["shippingFee"], d["total"]), (46000, 15000, 61000))
        bad = self.c.post("/api/orders", json=order("tra-sua-tran-chau-m", 1, line={"toppings": ["Không có"]}))
        self.assertEqual(bad.status_code, 400)

    def test06_over_stock_rolls_back(self):
        before = self.stock("croissant-bo-cai")
        body = order("tiramisu-phan", 1)
        body["items"].append({"sku": "croissant-bo-cai", "qty": before + 5})   # dòng 2 vượt tồn kho
        r = self.c.post("/api/orders", json=body)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.stock("tiramisu-phan"), 6)       # dòng 1 đã trừ phải được hoàn lại
        self.assertEqual(self.stock("croissant-bo-cai"), before)

    def test07_review_literal(self):
        r = self.c.post("/api/menu/latte/reviews", json={"name": "A", "stars": 5, "comment": "$where hack {$gt: 1}"})
        self.assertEqual(r.status_code, 201)
        item = database.menu.find_one({"slug": "latte"})
        self.assertEqual(item["reviews"][0]["comment"], "$where hack {$gt: 1}")
        self.assertGreaterEqual(item["rating"]["count"], 1)

    def test08_admin_auth_and_stats(self):
        self.assertEqual(self.c.get("/api/admin/stats").status_code, 401)
        d = self.c.get("/api/admin/stats", headers=ADMIN).json()
        for k in ("summary", "byCategory", "topItems", "byDay", "recent", "lowStock", "byStatus"):
            self.assertIn(k, d)
        self.assertGreater(d["summary"]["revenue"], 0)

    def test09_status_flow_and_cancel_restores_stock(self):
        r = self.c.post("/api/orders", json=order("cookie-socola-cai", 3))
        code = r.json()["code"]
        after_order = self.stock("cookie-socola-cai")
        self.assertEqual(self.c.patch(f"/api/admin/orders/{code}/status", headers=ADMIN, json={"status": "completed"}).status_code, 409)
        for s in ("preparing", "cancelled"):
            self.assertEqual(self.c.patch(f"/api/admin/orders/{code}/status", headers=ADMIN, json={"status": s}).status_code, 200)
        self.assertEqual(self.stock("cookie-socola-cai"), after_order + 3)

    def test10_concurrent_orders_no_oversell(self):
        """10 khách đặt cùng lúc 1 món chỉ còn 6 -> đúng 6 đơn thành công."""
        sku = "tiramisu-phan"
        database.menu.update_one({"variants.sku": sku}, {"$set": {"variants.$.stock": 6}})

        def go(_):
            try:
                place_order(OrderIn(**order(sku, 1)))
                return True
            except HTTPException:
                return False

        with ThreadPoolExecutor(10) as ex:
            ok = sum(ex.map(go, range(10)))
        self.assertEqual(ok, 6)
        self.assertEqual(self.stock(sku), 0)

    def test11_track_by_phone(self):
        d = self.c.get("/api/orders?phone=0911111111").json()
        self.assertTrue(d["orders"])
        self.assertEqual(self.c.get("/api/orders?phone=abc").status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
