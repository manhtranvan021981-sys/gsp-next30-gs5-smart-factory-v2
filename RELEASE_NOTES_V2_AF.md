# GS5 Smart Factory V2 – Dòng hàng mẹ AF

Ngày build kiểm thử: 27/07/2026  
Nguồn: `P3_Tong_Hop_LTT_2507.xlsx`  
Nhà máy: `GS5`

## Phạm vi thay đổi

- Chuẩn hóa bộ lọc thành `Dòng hàng mẹ (AF)`.
- AF là khóa phân loại duy nhất: `TRIM → UPPER → exact match`.
- Dùng đủ master 19 mã GSBB.
- Tách riêng `00` AF trống, `98` xung đột AF theo LTT/phiếu, `99` AF ngoài master.
- Không suy luận từ máy, công đoạn, vật tư, AG hoặc AH.
- Giữ `KHC` là dòng hàng hợp lệ số 17.
- Đồng bộ dữ liệu chính, OEE/Capa, Downtime Pareto, Loss Map, LTT, Máy/Thợ, lịch máy và Data Quality.
- Schema mới: `gs5-static-shards-v2-af`.
- Cache/workflow V2 độc lập với GS5 V1.

## Kết quả build nguồn thật

| Chỉ tiêu | Kết quả |
|---|---:|
| Dòng GS5 được chấp nhận | 280.071 |
| Phân vùng dữ liệu | 8 |
| Dòng lịch máy hiện hành | 315 |
| AF trống – nhóm 00 | 0 |
| Dòng xung đột – nhóm 98 | 85 |
| AF ngoài master – nhóm 99 | 27 |
| LTT xung đột AF | 18 |
| Phiếu xung đột AF | 3 |

Mã AF ngoài master: `SOB=15`, `IVR=7`, `SOC=3`, `SOA=2`.

## Đối soát hợp đồng

- Tổng 19 nhóm hợp lệ + `00/98/99` = 280.071 dòng.
- FLC chỉ nhận `AF=FLC`; máy YRK/công đoạn Flexo không còn quyền tự gán mảng.
- Các dòng xung đột được đưa sang `98`, không đồng thời nằm trong nhóm AF hợp lệ.
- Gói build đã qua:
  - `python scripts/test_af_contract.py`
  - `python scripts/verify_build.py --data site/data`
  - kiểm tra cú pháp toàn bộ JavaScript nhúng trong `index.html`.

## Phát hành

- Repository mới: `gsp-next30-gs5-smart-factory-v2`.
- GitHub Pages: `https://manhtranvan021981-sys.github.io/gsp-next30-gs5-smart-factory-v2/`.
- Không upload gói này vào repository GS5 V1.
- Không upload file Excel hoặc thư mục `site/`; workflow sẽ tạo dữ liệu live.
