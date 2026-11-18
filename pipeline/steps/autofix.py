"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |
"""
from collections import defaultdict
from pathlib import Path

import yaml

from ..common import ERROR, parse_yolo_line

REMOVE_IMAGE_CODES = {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
DROP_LINE_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}


def fix(ds, issues, cfg) -> list[dict]:
    # Chỉ xử lý các lỗi có severity == ERROR
    error_issues = [i for i in issues if i.severity == ERROR]
    if not error_issues:
        return []

    fixes = []
    removed_images = set()

    # 1. Xử lý các lỗi xóa ảnh (remove_image)
    for i in error_issues:
        if i.code.startswith("DUP_IMAGE_") or i.code in REMOVE_IMAGE_CODES:
            if i.image not in removed_images:
                removed_images.add(i.image)
                # Xóa các file ảnh tương ứng
                if ds.images_dir.exists():
                    for p in ds.images_dir.glob(f"{i.image}.*"):
                        try:
                            p.unlink()
                        except OSError:
                            pass
                # Xóa file nhãn tương ứng nếu có
                lbl_path = ds.label_path(i.image)
                if lbl_path.exists():
                    try:
                        lbl_path.unlink()
                    except OSError:
                        pass
                ds._size_cache.pop(i.image, None)
                fixes.append({
                    "image": i.image,
                    "line": "",
                    "action": "remove_image",
                    "before": i.code,
                    "after": "deleted",
                })

    # 2. Xử lý BAD_CLASS_NAME (rename_classes)
    renamed_yaml = False
    for i in error_issues:
        if i.code == "BAD_CLASS_NAME" and not renamed_yaml:
            renamed_yaml = True
            old_names = ""
            if ds.yaml_path.exists():
                try:
                    data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
                    old_names = str(data.get("names", ""))
                    data["names"] = list(cfg["classes"])
                    ds.yaml_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
                except Exception:
                    pass
            fixes.append({
                "image": "data.yaml",
                "line": "",
                "action": "rename_classes",
                "before": old_names,
                "after": str(cfg["classes"]),
            })

    # 3. Xử lý MISSING_LABEL_FILE (needs_label)
    for i in error_issues:
        if i.code == "MISSING_LABEL_FILE":
            if i.image not in removed_images:
                fixes.append({
                    "image": i.image,
                    "line": "",
                    "action": "needs_label",
                    "before": "(không có file)",
                    "after": "chuyển người gán",
                })

    # 4. Xử lý các lỗi theo dòng trong file nhãn (drop_line, clip_box)
    # Gom các issue theo stem -> line_no
    stem_line_issues = defaultdict(lambda: defaultdict(list))
    for i in error_issues:
        if i.image in removed_images or i.image == "data.yaml" or i.image == "<dataset>":
            continue
        if i.line is not None and (i.code in DROP_LINE_CODES or i.code == "BOX_OUT_OF_IMAGE"):
            stem_line_issues[i.image][i.line].append(i)

    for stem in sorted(stem_line_issues.keys()):
        lbl_path = ds.label_path(stem)
        if not lbl_path.exists():
            continue

        raw_lines = lbl_path.read_text(encoding="utf-8", errors="replace").splitlines()
        line_fixes = []
        new_lines = []

        for idx, raw_line in enumerate(raw_lines):
            line_no = idx + 1
            issues_on_line = stem_line_issues[stem].get(line_no, [])

            if not issues_on_line:
                new_lines.append(raw_line)
                continue

            has_drop = any(iss.code in DROP_LINE_CODES for iss in issues_on_line)
            has_clip = any(iss.code == "BOX_OUT_OF_IMAGE" for iss in issues_on_line)

            if has_drop:
                # Xoá dòng thắng, chỉ ghi 1 fix drop_line, không ghi thêm clip_box
                line_fixes.append({
                    "image": stem,
                    "line": line_no,
                    "action": "drop_line",
                    "before": raw_line,
                    "after": "",
                })
            elif has_clip:
                # Cắt box về [0, 1]
                try:
                    cls_id, cx, cy, w, h = parse_yolo_line(raw_line)
                    x1 = cx - w / 2.0
                    y1 = cy - h / 2.0
                    x2 = cx + w / 2.0
                    y2 = cy + h / 2.0

                    nx1 = max(0.0, min(1.0, x1))
                    ny1 = max(0.0, min(1.0, y1))
                    nx2 = max(0.0, min(1.0, x2))
                    ny2 = max(0.0, min(1.0, y2))
                    nw = nx2 - nx1
                    nh = ny2 - ny1

                    if nw <= 1e-6 or nh <= 1e-6:
                        # Sau khi cắt không còn diện tích -> drop_line
                        line_fixes.append({
                            "image": stem,
                            "line": line_no,
                            "action": "drop_line",
                            "before": raw_line,
                            "after": "",
                        })
                    else:
                        ncx = nx1 + nw / 2.0
                        ncy = ny1 + nh / 2.0
                        # Giữ độ chính xác float hợp lý
                        clipped_line = f"{int(cls_id)} {ncx:.6g} {ncy:.6g} {nw:.6g} {nh:.6g}"
                        line_fixes.append({
                            "image": stem,
                            "line": line_no,
                            "action": "clip_box",
                            "before": raw_line,
                            "after": clipped_line,
                        })
                        new_lines.append(clipped_line)
                except ValueError:
                    line_fixes.append({
                        "image": stem,
                        "line": line_no,
                        "action": "drop_line",
                        "before": raw_line,
                        "after": "",
                    })
            else:
                new_lines.append(raw_line)

        # Ghi lại file nhãn
        content = "\n".join(new_lines) + ("\n" if new_lines else "")
        lbl_path.write_text(content, encoding="utf-8")
        fixes.extend(line_fixes)

    return fixes
