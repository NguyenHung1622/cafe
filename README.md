# Bean & Brew Café — Website bán hàng + quản trị với MongoDB

Đề tài: **Tìm hiểu về CSDL Document và ứng dụng quản lý quán cà phê với MongoDB**
Công nghệ: MongoDB (Atlas hoặc cài trên máy) · Python FastAPI · HTML/CSS/JavaScript thuần

## Chức năng
**Khách hàng:** xem thực đơn, lọc theo nhóm / giá, sắp xếp, phân trang · tìm kiếm toàn văn (gõ không dấu vẫn tìm được) ·
chi tiết món (kích cỡ, topping, độ ngọt, đá, nguyên liệu, món dùng kèm, đánh giá) · giỏ hàng · đặt hàng tại quán / mang đi / giao hàng ·
tra cứu đơn theo số điện thoại · tích điểm · đánh giá món.
**Quản trị** (`#/admin`, mã mặc định `admin123`): thống kê doanh thu bằng Aggregation `$facet` · cập nhật trạng thái đơn
(chờ xác nhận → đang pha chế → sẵn sàng → hoàn tất / hủy) · quản lý thực đơn (thêm, sửa, ẩn/hiện, xóa) · cảnh báo bánh sắp hết.
**Quản lý bàn** (tab *Bàn*): thêm 1 hoặc nhiều bàn một lúc (tự đánh số tiếp), chia theo khu vực, sửa số chỗ / khu vực, đặt trước, tạm ngưng, mở lại, xóa; xem bàn nào đang có khách kèm mã đơn và số tiền. Khách chỉ chọn được **bàn đang trống** khi đặt tại quán; đặt xong bàn tự chuyển “Có khách”, đơn hoàn tất hoặc bị hủy thì bàn tự trống.
**Báo cáo tuần / tháng** (tab *Báo cáo tuần/tháng*): xem trước trên màn hình (so sánh với kỳ trước, biểu đồ theo ngày, nhóm món, top 10 món, hình thức, thanh toán) và **tải file Excel (.xlsx)** với 4 sheet: *Tổng quan*, *Theo ngày* (có biểu đồ cột), *Phân tích*, *Đơn hàng* (chi tiết từng đơn, có bộ lọc). Chọn “Tuần này / Tuần trước / Tháng này / Tháng trước” hoặc một ngày bất kỳ.

## Chạy ứng dụng
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      (rồi sửa MONGODB_URI trong .env, nhớ Ctrl+S)
python seed.py              (nạp dữ liệu mẫu: 27 món, 6 khách, ~300 đơn)
uvicorn app:app --reload    (mở http://127.0.0.1:8000)
```
Kết nối Atlas bị lỗi `SSL handshake failed`: vào Atlas → **Network Access** → thêm IP `0.0.0.0/0` (Allow access from anywhere), đợi Active.
Hoặc cài MongoDB Community Server trên máy và đặt `MONGODB_URI=mongodb://localhost:27017`.

Kiểm thử và thực nghiệm:
```
python test_app.py          (18 kịch bản, dùng database riêng cafe_test rồi tự xóa)
python explain_demo.py      (50.000 đơn, so sánh COLLSCAN và IXSCAN)
```

## Thiết kế dữ liệu (4 collection)
| Quan hệ | Lựa chọn | Lý do |
|---|---|---|
| Món – kích cỡ/giá (`variants`) | **Nhúng** | Luôn hiển thị cùng món; trừ kho nguyên tử trong 1 document |
| Món – topping, nguyên liệu | **Nhúng** | Chỉ đọc cùng món, mỗi loại món có bộ khác nhau |
| Món – đánh giá | **Nhúng có giới hạn** (20 mới nhất) | Hiển thị ngay ở trang chi tiết, tránh vượt 16 MB |
| Món – nhóm (`category`) | **Tham chiếu** (`_id` chuỗi) | Dùng chung, ít đổi |
| Món – món dùng kèm (`pairsWith`) | **Tham chiếu mảng slug** | Quan hệ nhiều–nhiều, có chỉ mục multikey |
| Khách – địa chỉ | **Nhúng** | Ít phần tử, luôn đọc cùng khách |
| Bàn (`tables`) | **Collection riêng**, đơn tham chiếu qua `tableNumber` | Bàn có vòng đời riêng (trống / có khách / đặt trước / tạm ngưng), đơn chỉ lưu bản chụp số bàn |
| Khách – đơn hàng | **Tham chiếu** (`orders.customerId`) | Số đơn tăng không giới hạn |
| Đơn – dòng món (`items`) | **Nhúng bản chụp** | Giữ tên, giá lúc mua dù menu đổi giá sau này |

Chỉ mục: `slug` (unique) · `variants.sku` (unique, multikey) · `{category, price}` · `pairsWith` (multikey) ·
text `{name:10, tags:5, description:1}` · `customers.phone` (unique) · `orders.code` (unique) ·
`{customerId, createdAt:-1}` · `{status, createdAt:-1}` · `orders {tableNumber, status}` (tra đơn đang phục vụ của bàn) · `tables.number` (unique).
Schema validation (`$jsonSchema`) cho `menu_items` và `orders` (xem `db.py`), có ràng buộc `stock ≥ 0` ngay trong database.

## Các kỹ thuật MongoDB đã dùng (để đưa vào báo cáo / thuyết trình)
| Kỹ thuật | Vị trí trong mã |
|---|---|
| CRUD, lọc, sắp xếp, phân trang (`skip/limit`) | `app.py` — `list_menu`, `admin_*` |
| Text index có trọng số, `$meta: textScore` | `db.ensure_schema`, `list_menu` |
| Trừ kho nguyên tử `$elemMatch` + toán tử vị trí `$`, hoàn kho khi lỗi | `app.py` — `place_order` |
| Giá tính phía máy chủ (chống sửa giá từ trình duyệt) | `place_order` |
| Pipeline update: chèn đánh giá + cập nhật điểm trung bình (`$slice`, `$concatArrays`, `$literal`) | `add_review` |
| `$facet`, `$unwind`, `$group`, `$lookup`, `$dateToString` | `admin_stats` |
| Khóa lạc quan khi đổi trạng thái đơn (lọc theo status hiện tại) | `update_status` |
| Upsert khách hàng theo số điện thoại, `$addToSet`, `$setOnInsert`, `$inc` | `place_order`, `update_status` |
| `$jsonSchema` validation | `db.py` |
| `explain("executionStats")`: COLLSCAN và IXSCAN | `explain_demo.py` |
| Đặt hàng đồng thời không bán vượt tồn kho | `test_app.py` — test10 |
| Chiếm bàn nguyên tử (`update_one` chỉ khớp khi `status = free`): 8 khách tranh 1 bàn thì đúng 1 người được ngồi; lỗi thì hoàn bàn | `place_order`, test15 |
| `$lookup` có pipeline + `$expr` (bàn kèm đơn đang phục vụ) | `admin_tables` |
| Báo cáo kỳ: `$facet` 7 nhánh + so sánh kỳ trước, múi giờ `+07:00`, điền đủ ngày không có doanh thu | `build_report` |
| Xuất Excel bằng openpyxl (công thức SUM / SUMIF / % thay đổi, biểu đồ, bộ lọc) | `report_xlsx.py` |

## Gợi ý ảnh chụp cho báo cáo
Trang chủ · lọc nhóm + sắp xếp giá · tìm “ca phe” (không dấu) · chi tiết món + phần “document MongoDB gốc” · giỏ hàng · đặt hàng thành công (document vừa lưu) ·
tra cứu đơn · trang thống kê quản trị · quản lý đơn · **sơ đồ quản lý bàn** · **xem trước báo cáo tuần/tháng** · **mở file Excel báo cáo (4 sheet)** · kết quả `python test_app.py` · kết quả `python explain_demo.py` · MongoDB Atlas/Compass hiển thị các collection.

## API
`GET /api/menu` · `GET /api/menu/{slug}` · `POST /api/menu/{slug}/reviews` · `POST /api/orders` · `GET /api/orders?phone=` ·
`GET /api/tables` · `GET /api/admin/stats` · `GET|POST /api/admin/tables` · `PUT|DELETE /api/admin/tables/{number}` · `GET /api/admin/report?period=week|month&date=YYYY-MM-DD&format=json|xlsx` · `GET /api/admin/orders` · `PATCH /api/admin/orders/{code}/status` · `GET|POST /api/admin/menu` · `PUT|DELETE /api/admin/menu/{slug}` · `POST /api/admin/menu/{slug}/toggle`
(các API admin cần header `X-Admin-Key`). Tài liệu tự sinh: http://127.0.0.1:8000/docs
