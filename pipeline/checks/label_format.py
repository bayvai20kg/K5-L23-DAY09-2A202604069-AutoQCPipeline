"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line


def run(ds, cfg):
    issues = []
    lf_cfg = cfg.get("label_format", {})
    overflow_tol = lf_cfg.get("overflow_tol", 0.001)
    dup_box_iou = lf_cfg.get("dup_box_iou", 0.9)
    min_box_px = lf_cfg.get("min_box_px", 12)
    max_box_frac = lf_cfg.get("max_box_frac", 0.95)

    stems = sorted(p.stem for p in ds.label_files())
    for stem in stems:
        lines = ds.read_label_lines(stem)
        if lines is None:
            continue

        valid_prev_boxes = []
        img_size = ds.image_size(stem)

        for line_no, line_text in lines:
            # 1. Parse YOLO line format
            try:
                cls_id, cx, cy, w, h = parse_yolo_line(line_text)
            except ValueError:
                issues.append(
                    Issue("label_format", ERROR, "BAD_FORMAT", stem, "sai định dạng dòng YOLO", line_no)
                )
                continue

            # 2. Check class ID
            if not (0 <= cls_id < len(ds.classes)):
                issues.append(
                    Issue(
                        "label_format",
                        ERROR,
                        "BAD_CLASS_ID",
                        stem,
                        f"id lớp {cls_id} ngoài khoảng 0..{len(ds.classes) - 1}",
                        line_no,
                    )
                )
                continue

            # 3. Check zero / negative size
            if w <= 0 or h <= 0:
                issues.append(
                    Issue("label_format", ERROR, "BOX_ZERO", stem, "box có kích thước <= 0", line_no)
                )
                continue

            # Geometry checks
            x1 = cx - w / 2.0
            y1 = cy - h / 2.0
            x2 = cx + w / 2.0
            y2 = cy + h / 2.0
            overflow = max(0.0, -x1, -y1, x2 - 1.0, y2 - 1.0)
            if overflow > overflow_tol:
                issues.append(
                    Issue(
                        "label_format",
                        ERROR,
                        "BOX_OUT_OF_IMAGE",
                        stem,
                        f"box tràn ảnh (mức tràn {overflow:.4f})",
                        line_no,
                        extra={"overflow": overflow},
                    )
                )

            box_tuple = (cx, cy, w, h)
            for prev_cls, prev_box in valid_prev_boxes:
                if prev_cls == cls_id and iou_xywh(box_tuple, prev_box) > dup_box_iou:
                    issues.append(
                        Issue("label_format", ERROR, "DUP_BOX", stem, "box trùng với dòng trước đó", line_no)
                    )
                    break
            valid_prev_boxes.append((cls_id, box_tuple))

            if img_size is not None:
                img_w, img_h = img_size
                short_side_px = min(w * img_w, h * img_h)
                if short_side_px < min_box_px:
                    issues.append(
                        Issue(
                            "label_format",
                            WARN,
                            "BOX_TINY",
                            stem,
                            f"cạnh ngắn của box ({short_side_px:.1f}px) < {min_box_px}px",
                            line_no,
                        )
                    )

            if w * h > max_box_frac:
                issues.append(
                    Issue(
                        "label_format",
                        WARN,
                        "BOX_HUGE",
                        stem,
                        f"diện tích box ({w * h:.3f}) > {max_box_frac}",
                        line_no,
                    )
                )

    return issues
