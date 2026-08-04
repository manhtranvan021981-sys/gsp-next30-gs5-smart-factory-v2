# GSP NEXT30 – GS5 Smart Factory V2 – Dòng hàng mẹ AF + SHA-256

## Cập nhật nguồn Excel không giới hạn số dòng cũ

- Mỗi lượt chạy tải nội dung Excel hiện hành và tính SHA-256 toàn file.
- Chỉ cần thêm dòng, thêm tháng hoặc đổi một ô thì checksum và khóa dữ liệu đổi.
- Chạy thủ công bằng `Run workflow` luôn xử lý lại toàn bộ file, kể cả khi cache tồn tại.
- Manifest công bố checksum, dung lượng, số dòng quét/nhận, ngày đầu-cuối và tháng mới nhất.
- Workflow tự chạy khi thay mã nguồn trên nhánh `main` và vẫn chạy định kỳ như trước.

## Alias Dòng hàng mẹ AF

- `SOB, SOE, SOA, SBA, SBC, SBE, SOC, SOG, SEE, SEC` → `PHOI`.
- `DUP` → `HBL`.
- Xung đột được kiểm tra sau quy đổi alias; mã AF gốc vẫn nằm trong dữ liệu để truy vết.

Dashboard nhà máy thông minh GS5 V2, phát hành độc lập bằng GitHub Actions và GitHub Pages. Bộ GS5 hiện tại được giữ nguyên để backup/rollback.

## Kiến trúc

1. Workflow kiểm tra phiên bản file `P3_Tong_Hop_LTT_2507.xlsx` trên Google Drive mỗi 15 phút, lệch khỏi đầu giờ để giảm nguy cơ GitHub xếp hàng chậm.
2. Nếu file không đổi, workflow dừng và giữ nguyên bản dashboard đang chạy.
3. Nếu file đổi, bộ xử lý đọc streaming sheet `P3.Tổng hợp lệnh thao tác`, vùng `A9:CT`.
4. Chỉ các dòng có cột E bằng `GS5` được chấp nhận.
5. Bộ xử lý quét trước các AF hợp lệ theo LTT và phiếu thống kê; chỉ từ hai AF chuẩn khác nhau mới tạo cờ xung đột thật.
6. Dữ liệu được chia theo tháng và nén gzip; dashboard chỉ tải một tháng mỗi lần để bảo vệ RAM.
7. Bản dữ liệu đạt kiểm tra hợp đồng AF và kiểm tra gói build mới được phát hành lên GitHub Pages.

## Nguồn dữ liệu cố định

- File ID: `1ZCe-HgzUxoWV91JdsjSEF16rN5cn0W0e`
- Sheet: `P3.Tổng hợp lệnh thao tác`
- Header: dòng 9
- Phạm vi: `A9:CT`
- Nhà máy: `GS5`
- Mapping điều hành: cố định theo vị trí cột, không tự dò header cho `AR/AT/BG/BI/CH`
- Khóa dòng hàng: chỉ dùng cột `AF`, chuẩn hóa `TRIM + UPPER + exact match`

## Hợp đồng Dòng hàng mẹ AF

- 19 mã chuẩn: `HOC/HOT/HBD/HBL/FLC/FLP/FPK/SHD/PLL/PHOI/GCI/KHA/TUI/NVLC/NVLP/PTRO/KHC/LE/TCKT`.
- `00`: AF trống.
- `98`: bộ lọc chất lượng cho LTT/phiếu có từ hai AF chuẩn khác nhau; không phải mảng KPI thay thế.
- `99`: AF ngoài master 19 mã.
- `KHC` là dòng hàng hợp lệ số 17, không dùng để chứa AF lỗi.
- Không suy luận AF từ máy, công đoạn, vật tư, AG hoặc AH.
- AF trống và AF chưa ánh xạ không được dùng để tạo xung đột thật; chúng giữ riêng ở `00` và `99`.
- Dòng có xung đột thật vẫn giữ nguyên mảng KPI theo AF chuẩn của chính dòng đó.
- Schema dữ liệu: `gs5-static-shards-v4-af-quality-independent`.

## Chạy thủ công

Mở `Actions` → `Cập nhật dashboard GS5 V2 – AF` → `Run workflow`.

## Cơ chế an toàn

- Không upload file Excel 148 MB vào repository.
- Không lưu mật khẩu, cookie hoặc token Google Drive trong mã nguồn.
- Nếu tải/xử lý/kiểm tra lỗi, workflow dừng; GitHub Pages tiếp tục giữ bản hợp lệ gần nhất.
- Cache nội dung dùng namespace `gs5-v4-af-quality-*`, độc lập với GS5 V1/V2 cũ.
- `Action tuần này` chưa kết nối vì chưa có sheet `00_Task_Schedule` riêng cho GS5. Không dùng nhầm nguồn GS6.
- Repository và dữ liệu đã xử lý là công khai theo lựa chọn phương án A.
- GitHub tự tắt workflow theo lịch ở repository public nếu 60 ngày không có hoạt động; khi đó cần mở `Actions` và bật lại.

## Chạy kiểm thử cục bộ

```bash
python scripts/process_excel.py --input P3_Tong_Hop_LTT_2507.xlsx --out site/data
python scripts/test_af_contract.py
python scripts/test_source_refresh.py
python scripts/verify_build.py --data site/data
python -m http.server 8000 --directory site
```
