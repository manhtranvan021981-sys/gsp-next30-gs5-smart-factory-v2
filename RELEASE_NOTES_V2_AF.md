# GS5 Smart Factory V2 – Dòng hàng mẹ AF

## Bản AF Quality Independent + Content SHA-256

- Thay nhận diện phiên bản bằng metadata Drive bằng SHA-256 của toàn bộ nội dung Excel.
- Chạy thủ công bắt buộc rebuild; cache không còn chặn đọc file mới.
- Bổ sung trigger `push` để thay mã nguồn được phát hành ngay.
- Manifest bổ sung checksum, dung lượng, số dòng quét/nhận, khoảng ngày và tháng mới nhất.
- Đồng bộ 19 dòng hàng mẹ với GS1 V2.
- Quy đổi 10 alias về PHOI và DUP về HBL trước khi kiểm tra xung đột.
- Giữ đồng thời AF gốc và AF chuẩn để truy vết.
- Tách mảng KPI khỏi cờ chất lượng dữ liệu; xung đột không còn kéo dòng hợp lệ sang mảng 98.
- Chỉ hai AF chuẩn khác nhau trong cùng LTT/phiếu mới là xung đột thật.
- AF trống và AF chưa ánh xạ giữ riêng tại 00/99.
- Bảng Data Quality hiển thị LTT, phiếu, AF gốc, AF chuẩn và cặp AF gây xung đột.

Ngày build kiểm thử: 04/08/2026  
Nguồn: `P3_Tong_Hop_LTT_2507.xlsx`  
Nhà máy: `GS5`

## Phạm vi thay đổi

- Chuẩn hóa bộ lọc thành `Dòng hàng mẹ (AF)`.
- AF là khóa phân loại duy nhất: `TRIM → UPPER → exact match`.
- Dùng đủ master 19 mã GSBB.
- Tách riêng `00` AF trống và `99` AF ngoài master; `98` là bộ lọc kiểm soát độc lập.
- Không suy luận từ máy, công đoạn, vật tư, AG hoặc AH.
- Giữ `KHC` là dòng hàng hợp lệ số 17.
- Đồng bộ dữ liệu chính, OEE/Capa, Downtime Pareto, Loss Map, LTT, Máy/Thợ, lịch máy và Data Quality.
- Schema mới: `gs5-static-shards-v4-af-quality-independent`.
- Cache/workflow V2 độc lập với GS5 V1.

## Điều kiện nghiệm thu khi workflow đọc nguồn thật

- Tổng dòng trước/sau không đổi.
- Tổng sản lượng, lỗi, lỗi định mức, downtime và các KPI lõi trước/sau không đổi.
- Không có dòng dữ liệu nào mang `segment_code=98`; số dòng của bộ lọc 98 lấy từ cờ xung đột.
- `PHOI + trống` giữ PHOI và 00; `HBL + mã lạ` giữ HBL và 99.
- `PHOI + HBL` bật cờ 98 nhưng hai dòng vẫn thuộc đúng PHOI/HBL.

## Đối soát hợp đồng

- Tổng 19 nhóm hợp lệ + `00/99` = tổng dòng GS5; 98 là lớp lọc chồng lên các dòng hợp lệ nên không cộng thêm vào tổng.
- FLC chỉ nhận `AF=FLC`; máy YRK/công đoạn Flexo không còn quyền tự gán mảng.
- Các dòng xung đột vẫn nằm trong nhóm AF hợp lệ và đồng thời được tìm thấy bằng bộ lọc 98.
- Gói build đã qua:
  - `python scripts/test_af_contract.py`
  - `python scripts/verify_build.py --data site/data`
  - kiểm tra cú pháp toàn bộ JavaScript nhúng trong `index.html`.

## Phát hành

- Repository mới: `gsp-next30-gs5-smart-factory-v2`.
- GitHub Pages: `https://manhtranvan021981-sys.github.io/gsp-next30-gs5-smart-factory-v2/`.
- Không upload gói này vào repository GS5 V1.
- Không upload file Excel hoặc thư mục `site/`; workflow sẽ tạo dữ liệu live.
