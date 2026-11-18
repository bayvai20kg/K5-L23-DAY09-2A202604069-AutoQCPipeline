"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán:
  (1) cands rỗng -> MISSING.
  (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên).
  (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    so_cfg = cfg.get("second_opinion", {})
    conf_thresh = so_cfg.get("conf", 0.5)
    min_area_px = so_cfg.get("min_area_px", 600)
    fp_conf = so_cfg.get("fp_conf", 0.25)
    iou_missing = so_cfg.get("iou_missing", 0.3)
    iou_match = so_cfg.get("iou_match", 0.5)
    iou_loose = so_cfg.get("iou_loose", 0.6)

    issues = []

    for img_path in ds.image_files():
        stem = img_path.stem
        # Bỏ qua nếu không có trong preds hoặc không có file nhãn
        if preds is None or stem not in preds:
            continue
        if not ds.label_path(stem).exists():
            continue

        img_size = ds.image_size(stem)
        img_w, img_h = img_size if img_size else (0, 0)
        all_preds = preds.get(stem, [])
        valid_labels = ds.valid_boxes(stem)

        # 1. P = dự đoán có conf >= conf VÀ diện tích px >= min_area_px
        P = []
        for r in all_preds:
            p_conf = float(r[1])
            w, h = float(r[4]), float(r[5])
            area_px = (w * img_w) * (h * img_h)
            if p_conf >= conf_thresh and area_px >= min_area_px:
                P.append(r)

        # Kiểm tra từng dự đoán trong P theo thứ tự
        for r in P:
            p_cls = int(r[0])
            p_conf = float(r[1])
            p_box = (float(r[2]), float(r[3]), float(r[4]), float(r[5]))

            # Lấy các nhãn có IoU >= iou_missing
            cands = []
            for l_cls, l_cx, l_cy, l_w, l_h in valid_labels:
                iou = iou_xywh(p_box, (l_cx, l_cy, l_w, l_h))
                if iou >= iou_missing:
                    cands.append((l_cls, iou))

            if not cands:
                # (1) cands rỗng -> MISSING
                cls_name = ds.classes[p_cls] if 0 <= p_cls < len(ds.classes) else str(p_cls)
                issues.append(
                    Issue(
                        check="second_opinion",
                        severity=WARN,
                        code="POSSIBLE_MISSING",
                        image=stem,
                        message=f"model dự đoán {cls_name} (conf {p_conf:.2f}) nhưng nhãn thiếu",
                        line=None,
                        extra={"conf": p_conf},
                    )
                )
            else:
                same_cands = [iou for l_cls, iou in cands if l_cls == p_cls]
                if same_cands:
                    # (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại không cờ
                    best_same = max(same_cands)
                    if best_same < iou_loose:
                        issues.append(
                            Issue(
                                check="second_opinion",
                                severity=WARN,
                                code="POSSIBLE_LOOSE_BOX",
                                image=stem,
                                message=f"box nhãn lỏng/lệch so với model (IoU {best_same:.2f} < {iou_loose})",
                                line=None,
                                extra={"conf": p_conf, "iou": round(best_same, 4)},
                            )
                        )
                else:
                    # (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS
                    diff_cands = [iou for l_cls, iou in cands if l_cls != p_cls]
                    if diff_cands:
                        best_diff = max(diff_cands)
                        if best_diff >= iou_match:
                            cls_name = ds.classes[p_cls] if 0 <= p_cls < len(ds.classes) else str(p_cls)
                            issues.append(
                                Issue(
                                    check="second_opinion",
                                    severity=WARN,
                                    code="POSSIBLE_WRONG_CLASS",
                                    image=stem,
                                    message=f"model đoán {cls_name} nhưng nhãn ghi lớp khác (IoU {best_diff:.2f})",
                                    line=None,
                                    extra={"conf": p_conf, "iou": round(best_diff, 4)},
                                )
                            )

        # 2. Kiểm tra POSSIBLE_FALSE_POS cho từng dòng nhãn hợp lệ
        fp_preds = [r for r in all_preds if float(r[1]) >= fp_conf]
        raw_lines = ds.read_label_lines(stem) or []
        for line_no, line_text in raw_lines:
            try:
                l_cls, l_cx, l_cy, l_w, l_h = parse_yolo_line(line_text)
            except ValueError:
                continue
            if not (0 <= l_cls < len(ds.classes)):
                continue

            l_box = (l_cx, l_cy, l_w, l_h)
            has_match = any(
                iou_xywh(l_box, (float(r[2]), float(r[3]), float(r[4]), float(r[5]))) >= iou_missing
                for r in fp_preds
            )
            if not has_match:
                issues.append(
                    Issue(
                        check="second_opinion",
                        severity=WARN,
                        code="POSSIBLE_FALSE_POS",
                        image=stem,
                        message="box nhãn không khớp vật nào model thấy",
                        line=line_no,
                        extra={},
                    )
                )

    return issues
