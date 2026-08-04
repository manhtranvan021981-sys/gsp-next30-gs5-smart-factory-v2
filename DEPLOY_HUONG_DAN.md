# Hướng dẫn triển khai GitHub Pages – GS5 V2 – Dòng hàng mẹ AF

## Cập nhật bản V2 hiện có

Tải đè toàn bộ nội dung gói này vào đúng thư mục gốc repository GS5 V2. Không tải
nguyên ZIP và không tạo thư mục bọc ngoài. Sau khi commit, vào **Actions → Cập
nhật dashboard GS5 V2 – AF → Run workflow**. Lần chạy thủ công luôn tải lại Excel,
tính SHA-256 và dựng lại toàn bộ dữ liệu theo tháng.

Sau khi Actions xanh, mở dashboard và nhấn `Ctrl + F5`. Đối chiếu trạng thái nguồn:
thời điểm tạo dữ liệu, tổng số dòng nhận và tháng mới nhất phải khớp file Excel mới.

## 1. Đưa bộ mã lên repository

Upload toàn bộ nội dung **bên trong** gói này vào thư mục gốc của repository:

- `.github/workflows/update-dashboard.yml`
- `scripts/process_excel.py`
- `scripts/verify_build.py`
- `scripts/test_af_contract.py`
- `scripts/test_source_refresh.py`
- `index.html`
- `README.md`
- `requirements.txt`
- `.gitignore`

Không upload file Excel.

## 2. Bật GitHub Pages

Mở:

`Settings` → `Pages` → `Build and deployment` → `Source`

Chọn:

`GitHub Actions`

## 3. Cho phép workflow chạy

Mở:

`Actions`

Nếu GitHub hiển thị nút xác nhận workflow, bấm:

`I understand my workflows, go ahead and enable them`

## 4. Chạy lần đầu

Mở:

`Actions` → `Cập nhật dashboard GS5 V2 – AF` → `Run workflow` → `Run workflow`

Lần đầu sẽ tải và xử lý file Excel 148 MB nên lâu hơn các lần sau. Chỉ coi là thành công khi tất cả bước đều xanh, đặc biệt:

- `Xử lý Excel thành dữ liệu theo tháng`
- `Kiểm tra hợp đồng Dòng hàng mẹ AF`
- `Kiểm tra dữ liệu trước khi phát hành`
- `Phát hành dashboard`

## 5. Mở dashboard

Sau khi workflow xanh, đường dẫn dự kiến:

`https://manhtranvan021981-sys.github.io/gsp-next30-gs5-smart-factory-v2/`

## 6. Quyền file Excel

Đổi quyền Google Drive từ `Anyone – Editor` thành:

`Anyone with the link – Viewer`

Nếu chuyển file sang `Restricted`, workflow công khai này sẽ không tải được nếu chưa bổ sung cơ chế xác thực.

## 7. Kiểm tra vận hành

- Trạng thái đầu trang phải ghi đúng `GS5`.
- Nguồn phải là `P3_Tong_Hop_LTT_2507.xlsx`.
- Bộ lọc phải ghi `Dòng hàng mẹ (AF)` và có đủ 19 mã chuẩn.
- Có ba nhóm kiểm soát ở cuối: `00`, `98`, `99`.
- Chọn `FLC` không được nhận dữ liệu chỉ vì chạy máy YRK/công đoạn Flexo.
- Dữ liệu mặc định là tháng mới nhất.
- Có thể chuyển từng tháng; dashboard không nạp cả 279 nghìn dòng cùng lúc.
- `Action tuần này` phải báo chưa cấu hình nguồn GS5, không được hiện công việc GS6.
- Khi Excel không đổi, workflow dùng cache và không xử lý lại.

## 8. Nguyên tắc backup

- Không upload gói này vào repository `gsp-next30-gs5-smart-factory` hiện tại.
- Tạo repository mới hoàn toàn: `gsp-next30-gs5-smart-factory-v2`.
- Bật Pages theo `GitHub Actions`.
- Chỉ chuyển V2 thành đường dẫn chính sau khi workflow xanh và nghiệm thu đủ tiêu chí AF.
