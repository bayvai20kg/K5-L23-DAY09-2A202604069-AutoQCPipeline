# Báo cáo Day 09 — Vũ Gia Khang, 2A202604069

## 1. Kết luận trước

Pipeline kết luận **Hold** (mã thoát: 10).

Trong tổng số 224 ảnh đầu vào ở tập `data/raw/`, bước intake đã quét 224 ảnh và loại bỏ 21 ảnh (hỏng, kích thước nhỏ < 250px, trùng lặp byte/phash, rò rỉ vào kho test/val). 203 ảnh đạt chuẩn được đưa vào pipeline QC. Toàn bộ 36 lỗi bắt buộc ban đầu đã được giải quyết triệt để (`n_errors = 0`) thông qua tự động sửa (35 thay đổi) và người duyệt (80 ảnh). Tuy nhiên, sau khi hết ngân sách duyệt 80 ảnh, vẫn còn 44/203 ảnh mang cảnh báo ngữ nghĩa chưa được xác minh (tỉ lệ 21.67%, vượt ngưỡng giữ lại `warn_ratio_hold = 10.00%`). Do đó, bản xuất tại `submission/export/clean_v1/` là bản nháp để thử nghiệm, chưa đủ điều kiện phát hành chính thức (Release).

---

## 2. Lỗi và phân việc

Thống kê chi tiết từ báo cáo lỗi ban đầu `02_error_list_v1` (tổng hợp trên 203 ảnh được tiếp nhận):

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `BAD_FORMAT` | 3 dòng | Máy (autofix) | Dòng sai cấu trúc 5 cột số YOLO, không thể suy đoán toạ độ; máy xóa dòng (`drop_line`) an toàn. |
| `BAD_CLASS_ID` | 6 dòng | Máy (autofix) | ID lớp ngoài phạm vi 0..3 (-1, 4, 7, 93); máy xóa dòng (`drop_line`) để tránh làm nhiễu nhãn đào tạo. |
| `BAD_CLASS_NAME` | 2 lỗi | Máy (autofix) | Tên lớp trong `data.yaml` bị viết hoa sai ("Person", "Bus"); máy tự chuẩn hóa lại danh sách lớp (`rename_classes`). |
| `BOX_ZERO` | 4 dòng | Máy (autofix) | Box có chiều rộng hoặc chiều cao $\le 0$; không có diện tích hình học nên máy xóa dòng (`drop_line`). |
| `BOX_OUT_OF_IMAGE` | 8 dòng | Máy (autofix) | Box tràn ra ngoài biên $[0, 1]$; máy cắt viền (`clip_box`) đưa về toạ độ hợp lệ. |
| `DUP_BOX` | 7 dòng | Máy (autofix) | Box trùng lặp cùng lớp với box đứng trước ($\text{IoU} > 0.9$); máy xóa box trùng ở dòng sau (`drop_line`). |
| `BAD_SIZE` | 3 ảnh | Máy (autofix) | Cạnh ngắn $< 250\text{px}$; không đảm bảo chất lượng nhận diện nên loại khỏi dataset (`remove_image`). |
| `CORRUPT_IMAGE` | 2 ảnh | Máy (autofix) | File ảnh bị hỏng không thể giải mã; máy tự động xóa (`remove_image`). |
| `DUP_IMAGE_EXACT` | 8 ảnh | Máy (autofix) | Trùng từng byte (hash MD5/SHA1) với ảnh khác; máy loại bỏ để tránh thiên lệch dữ liệu (`remove_image`). |
| `DUP_IMAGE_NEAR` | 3 ảnh | Máy (autofix) | Trùng gần đúng về góc máy và bối cảnh (khoảng cách pHash $\le 8$); máy loại bỏ (`remove_image`). |
| `LEAK_TEST` | 5 ảnh | Máy (autofix) | Trùng lặp với tập test/val đã định sẵn; loại bỏ ngay cửa vào để chống rò rỉ dữ liệu (`remove_image`). |
| `MISSING_LABEL_FILE` | 6 ảnh | Người (hàng đợi) | Ảnh không có file nhãn đi kèm; máy không được tự bịa nhãn mà ghi log chuyển người gán (`needs_label`). |
| `EMPTY_LABEL` | 12 ảnh | Người (hàng đợi) | File nhãn rỗng; cần người phân xử xem đây là ảnh nền (không có vật thể) hay bị sót nhãn. |
| `POSSIBLE_WRONG_CLASS` | 18 lỗi | Người (hàng đợi) | Model lớn dự đoán lớp khác với nhãn người; cần người thẩm định ngữ nghĩa thực tế. |
| `POSSIBLE_MISSING` | 68 lỗi | Người (hàng đợi) | Model lớn nhận diện vật thể rõ ràng nhưng nhãn thiếu; cần người bổ sung box nếu đúng. |
| `POSSIBLE_LOOSE_BOX` | 31 lỗi | Người (hàng đợi) | Box nhãn đúng lớp nhưng viền lỏng/lệch so với vật thể ($\text{IoU} < 0.5$); cần người căn chỉnh lại viền. |
| `POSSIBLE_FALSE_POS` | 29 lỗi | Người (hàng đợi) | Box trong nhãn không khớp với bất kỳ dự đoán nào của model lớn; cần người kiểm tra xem có gán nhầm vùng nhiễu. |
| `BOX_TINY` | 6 dòng | Người (hàng đợi) | Cạnh ngắn $< 12\text{px}$; cảnh báo người xem có phải vật thể ở quá xa hoặc box gán nhầm. |
| `BOX_HUGE` | 3 dòng | Người (hàng đợi) | Box chiếm $> 95\%$ diện tích ảnh; cảnh báo người kiểm tra xem có gán bao trùm toàn bộ khung hình. |
| `CLASS_RARE` | 4 lỗi | Báo cáo | Thống kê ở cấp dataset: các lớp dị thường (-1, 4, 7, 93) xuất hiện lẻ tẻ do nhãn rác. |

**Cơ chế hàng đợi duyệt (`05_review_queue.csv`)**:
Hàng đợi gồm 130 ảnh được sắp xếp theo điểm ưu tiên giảm dần. Điểm ưu tiên tính từ trọng số cấu hình: ảnh `NEEDS_LABEL` có trọng số cao nhất (10) vì nếu không được người gán nhãn thì pipeline sẽ bị Rework; tiếp đến là các ảnh vừa bị xóa dòng `FIXED_DROP_LINE` (trọng số 2) kết hợp với các nghi vấn sai lớp `POSSIBLE_WRONG_CLASS` (trọng số 3) và thiếu nhãn `POSSIBLE_MISSING` (trọng số 2). Điểm số này còn được nhân với độ tin cậy `conf` của model, đẩy các ảnh như `img_0020` (priority 14.528), `img_0185` (priority 10.052) và 6 ảnh thiếu nhãn lên đầu hàng đợi.

**Hiệu quả với ngân sách 80 ảnh**:
Với ngân sách duyệt 80 ảnh, người duyệt mô phỏng đã xử lý toàn bộ 80 ảnh ưu tiên cao nhất, gán nhãn thành công cho 6 ảnh thiếu file nhãn và giải quyết trực tiếp 72 lỗi ngữ nghĩa (giảm `POSSIBLE_MISSING` từ 68 xuống 26; giảm `POSSIBLE_WRONG_CLASS` từ 18 xuống 4; giảm `POSSIBLE_LOOSE_BOX` từ 31 xuống 24; giảm `POSSIBLE_FALSE_POS` từ 29 xuống 20). 50 ảnh còn lại không được duyệt do vượt ngân sách, dẫn đến 44 ảnh mang cảnh báo và cổng quyết định Hold.

---

## 3. Calibration (2 ngưỡng)

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 8 | P: 1.00 → 1.00<br>R: 0.50 → 0.67 (NEAR) | Tăng recall phát hiện ảnh gần trùng (0.50 → 0.67) trên tập calib mà vẫn giữ tuyệt đối Precision = 1.00 (không xóa nhầm). Không chọn ngưỡng cao hơn (như 16) vì trên tập raw thật sẽ xóa nhầm ảnh tốt. |
| `second_opinion.conf` | 0.25 | 0.50 | P: 0.50 → 0.57<br>R: 1.00 → 1.00 (MISSING) | Tăng precision từ 0.50 lên 0.57 để giảm báo động giả đưa vào hàng đợi người duyệt (ngân sách 80 ảnh), trong khi vẫn giữ nguyên Recall = 1.00 cho lỗi thiếu nhãn. Nếu tăng conf >= 0.7 thì recall tụt (0.88, 0.75). |

**Một chỗ calibration có thể đánh lừa bạn**:
Tập `data/calib` chỉ có 39 ảnh dựng sẵn với các lỗi chèn cố ý đơn giản. Khi sweep `duplicates.phash_dist`, ở ngưỡng 16, trên tập calib Recall đạt tới 0.83 và Precision vẫn là 1.00 (dễ tạo ảo giác 16 là ngưỡng tối ưu). Tuy nhiên, khi kiểm tra trên tập `data/raw` (224 ảnh thực tế có nhiều góc chụp liên tiếp trên đường phố), ngưỡng 16 làm số ảnh bị coi là trùng lặp/rò rỉ tăng vọt từ 16 lên 26 ảnh (tức loại bỏ nhầm thêm 10 ảnh bình thường). Do lỗi trùng lặp là lỗi bắt buộc tự động xóa ảnh (`remove_image`), một false positive sẽ xóa vĩnh viễn dữ liệu tốt mà người không kịp duyệt. Vì vậy, ta cần chọn ngưỡng an toàn (8) dựa trên bản chất dữ liệu thật thay vì tin mù quáng vào điểm số trên tập calib nhỏ.

---

## 4. Cửa chặn và điều pipeline KHÔNG bắt được

### (a) Bằng chứng cửa chặn hoạt động chính xác
Để chứng minh cửa chặn thật sự ngăn chặn việc phát hành dữ liệu lỗi, ta chạy pipeline ở chế độ không có người duyệt:
```bash
python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb
```
- **Kết quả**: Do không có người duyệt gán nhãn, 6 ảnh thiếu file nhãn (`MISSING_LABEL_FILE`) không được xử lý, tồn đọng 6 lỗi bắt buộc (`ERROR`) sau vòng 3. Cửa chặn kết luận **REWORK** (`Còn 6 lỗi bắt buộc (ERROR) cần sửa lại trước khi phát hành`), trả về mã thoát **20**.
- **Không xuất dataset**: Thư mục `work/exp_nb` hoàn toàn không được tạo ra (`Bước 5/5 KHÔNG xuất: còn lỗi bắt buộc (Rework) — trả về bước 3`). Điều này chứng minh cửa chặn bảo vệ nghiêm ngặt tính toàn vẹn của dataset.

### (b) Các điểm mù mà pipeline không bắt được
1. **Box lỏng nhẹ hoặc lệch góc trong phạm vi dung sai**: Khi độ trùng khớp IoU giữa nhãn và dự đoán của model lớn nằm trong khoảng $[0.50, 0.60]$, pipeline không phát cờ `POSSIBLE_LOOSE_BOX` vì đã vượt qua ngưỡng kiểm tra `iou_loose = 0.5`. Các box hơi rộng hoặc lệch tâm vẫn lọt qua kiểm định.
2. **Sự đồng thuận mù giữa nhãn sai và model lớn**: Khi nhãn người gán nhầm lớp ở các đối tượng có hình thái tương đồng trong điều kiện xa/mờ (ví dụ: xe tải nhỏ bị nhãn ghi là ô tô con) và chính model YOLO26L cũng đưa ra cùng dự đoán sai đó, pipeline coi như hai bên đồng thuận và hoàn toàn không cảnh báo.
3. **Ảnh trùng lặp bị biến đổi hình học mạnh (>80%)**: Nếu ảnh bị cắt xén khung hình chỉ còn một góc nhỏ rồi co giãn tỉ lệ, thuật toán pHash không thể nhận ra khoảng cách Hamming $\le 8$, dẫn đến ảnh trùng góc máy một phần vẫn vượt qua bước intake.

---

## 5. Train: raw vs clean

Chưa chạy (thiết bị cá nhân chạy kiểm thử cục bộ không có GPU, phần huấn luyện Colab là tùy chọn được thực hiện theo [docs/COLAB.md](docs/COLAB.md)).

---

## 6. Quyết định và ghi chú AI

### (a) Quyết định cuối cùng
- **Quyết định**: Giữ lại dữ liệu (**Hold**).
- **Điều kiện để chuyển sang Release**:
  1. Tăng ngân sách duyệt người từ 80 lên 130 ảnh để duyệt nốt 50 ảnh còn lại trong hàng đợi `05_review_queue.csv`.
  2. Trường hợp thời gian gấp, quản lý dự án có thể rà soát lại các cảnh báo còn lại (chủ yếu là `BOX_TINY` hoặc `POSSIBLE_LOOSE_BOX` nhẹ) và chấp thuận điều chỉnh ngưỡng `warn_ratio_hold` lên 25% nếu các cảnh báo này không ảnh hưởng tiêu cực tới mục tiêu huấn luyện.

### (b) Ghi chú sử dụng AI
- **Prompt chính**: "Viết 4 module pipeline kiểm nhãn theo đúng tài liệu thiết kế và docstring TDD: label_format.py, gate.py, autofix.py, second_opinion.py; đảm bảo không sửa file đã ghim và vượt qua toàn bộ unit test."
- **Cách kiểm tra code do AI sinh**: Chạy độc lập toàn bộ bộ unit test (`pytest tests/test_*.py -q`), chạy script thẩm định `python scripts/check_submission.py --no-train`, kiểm tra mã hash qua `scripts/_protected.json` để đảm bảo tính toàn vẹn và nguyên tắc không đọc đáp án.
- **Một lần AI xử lý chưa tối ưu**: Trong môi trường Windows, việc chuyển đổi đối tượng Path sang chuỗi mặc định sinh ra dấu gạch chéo ngược `\` (ví dụ: `pipeline\calibrate.py`), dẫn đến việc kiểm tra không khớp với đường dẫn chuẩn POSIX `/` trong `_protected.json` và gây lỗi giả; sau đó đã được khắc phục chuẩn mực bằng phương thức `.as_posix()`.
