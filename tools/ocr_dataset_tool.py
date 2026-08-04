from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
VALID_CLUE_PATTERN = re.compile(r"^(\?|\d+|\{\d+\}|-\d+-)$")
DEFAULT_DATASET_DIR = "tests"

TARGET_LABELS = {
    "remaining": "REMAINING",
    "row": "行线索",
    "cell": "格内线索",
    "other": "其它文本",
}
LABEL_TO_TARGET = {label: key for key, label in TARGET_LABELS.items()}

FAMILY_LABELS = {
    "unknown": "未知方向",
    "vertical": "竖直",
    "down_right": "右下斜",
    "down_left": "左下斜",
}
LABEL_TO_FAMILY = {label: key for key, label in FAMILY_LABELS.items()}
FAMILY_ALIASES = {
    "horizontal": "vertical",
}

TARGET_COLORS = {
    "remaining": "#2f80ed",
    "row": "#27ae60",
    "cell": "#f2994a",
    "other": "#9b51e0",
}


@dataclass
class ImageView:
    image: Image.Image
    photo: ImageTk.PhotoImage
    scale: float
    offset_x: float
    offset_y: float


def dataset_dirs(dataset_dir: Path) -> Dict[str, Path]:
    return {
        "root": dataset_dir,
        "images": dataset_dir / "images",
        "labels": dataset_dir / "labels",
        "reports": dataset_dir / "reports",
        "crops": dataset_dir / "crops",
    }


def resolve_dataset_dir(dataset_dir: Path) -> Path:
    """Use the selected dataset root, with a soft fallback for the old layout."""
    dataset_dir = dataset_dir.resolve()
    if (dataset_dir / "images").exists() or (dataset_dir / "labels").exists():
        return dataset_dir

    legacy_dir = dataset_dir / "ocr_cases"
    if (legacy_dir / "images").exists() or (legacy_dir / "labels").exists():
        return legacy_dir.resolve()
    return dataset_dir


def ensure_dataset(dataset_dir: Path) -> None:
    for path in dataset_dirs(dataset_dir).values():
        path.mkdir(parents=True, exist_ok=True)


def image_files(images_dir: Path) -> List[Path]:
    if not images_dir.exists():
        return []
    return sorted(path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS)


def unique_target_path(images_dir: Path, source: Path) -> Path:
    target = images_dir / source.name
    try:
        if target.exists() and target.resolve() == source.resolve():
            return target
    except OSError:
        pass

    if not target.exists():
        return target

    stem = source.stem
    suffix = source.suffix
    index = 2
    while True:
        candidate = images_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def import_image(source: Path, dataset_dir: Path) -> Path:
    ensure_dataset(dataset_dir)
    source = source.resolve()
    if source.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"不支持的图片格式：{source}")
    target = unique_target_path(dataset_dirs(dataset_dir)["images"], source)
    if target.resolve() != source:
        shutil.copy2(source, target)
    return target


def import_directory(source_dir: Path, dataset_dir: Path) -> int:
    ensure_dataset(dataset_dir)
    count = 0
    for source in sorted(source_dir.iterdir()):
        if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        import_image(source, dataset_dir)
        count += 1
    return count


def label_path_for(image_path: Path, dataset_dir: Path) -> Path:
    return dataset_dirs(dataset_dir)["labels"] / f"{image_path.stem}.json"


def normalize_family(value: str) -> str:
    return FAMILY_ALIASES.get(value, value if value in FAMILY_LABELS else "unknown")


def empty_label_doc(image_path: Path, image: Image.Image) -> Dict[str, Any]:
    return {
        "version": 1,
        "image": {
            "file": image_path.name,
            "width": image.width,
            "height": image.height,
        },
        "items": [],
        "notes": "",
    }


def normalize_box(box: Tuple[float, float, float, float], width: int, height: int) -> List[int]:
    x0, y0, x1, y1 = box
    left = max(0, min(width, int(round(min(x0, x1)))))
    right = max(0, min(width, int(round(max(x0, x1)))))
    top = max(0, min(height, int(round(min(y0, y1)))))
    bottom = max(0, min(height, int(round(max(y0, y1)))))
    return [left, top, right, bottom]


def validate_item(item: Dict[str, Any]) -> Optional[str]:
    target = item.get("target", "")
    text = str(item.get("text", "")).strip()
    box = item.get("box", [])

    if target not in TARGET_LABELS:
        return "target 不合法"
    if len(box) != 4:
        return "box 缺失"
    if box[2] <= box[0] or box[3] <= box[1]:
        return "box 尺寸不合法"
    if target == "remaining" and not text.isdigit():
        return "REMAINING 必须是纯数字"
    if target in {"row", "cell"} and not VALID_CLUE_PATTERN.match(text):
        return "线索文本格式不合法"
    return None


def summarize_dataset(dataset_dir: Path) -> str:
    dataset_dir = resolve_dataset_dir(dataset_dir)
    dirs = dataset_dirs(dataset_dir)
    ensure_dataset(dataset_dir)
    images = image_files(dirs["images"])
    labels = sorted(dirs["labels"].glob("*.json"))
    label_stems = {path.stem for path in labels}

    target_counts = {key: 0 for key in TARGET_LABELS}
    invalid: List[str] = []
    total_items = 0

    for label_file in labels:
        try:
            data = json.loads(label_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            invalid.append(f"{label_file.name}: JSON 解析失败：{exc}")
            continue
        image_name = str(data.get("image", {}).get("file", "")).strip()
        image_path = dirs["images"] / image_name if image_name else dirs["images"] / f"{label_file.stem}.png"
        image_size: Optional[Tuple[int, int]] = None
        if not image_path.exists():
            invalid.append(f"{label_file.name}: 找不到对应图片 {image_name or label_file.stem}")
        else:
            try:
                with Image.open(image_path) as image:
                    image_size = image.size
            except Exception as exc:
                invalid.append(f"{label_file.name}: 图片无法打开：{exc}")
        declared_width = data.get("image", {}).get("width")
        declared_height = data.get("image", {}).get("height")
        if image_size is not None and (declared_width, declared_height) != image_size:
            invalid.append(
                f"{label_file.name}: 标注尺寸 {declared_width}x{declared_height} 与图片尺寸 "
                f"{image_size[0]}x{image_size[1]} 不一致"
            )
        for index, item in enumerate(data.get("items", []), start=1):
            total_items += 1
            item["family"] = normalize_family(str(item.get("family", "unknown")))
            target = item.get("target", "")
            if target in target_counts:
                target_counts[target] += 1
            error = validate_item(item)
            if error:
                invalid.append(f"{label_file.name} / 第 {index} 项：{error}")
                continue
            if image_size is not None:
                x0, y0, x1, y1 = item.get("box", [0, 0, 0, 0])
                if x0 < 0 or y0 < 0 or x1 > image_size[0] or y1 > image_size[1]:
                    invalid.append(f"{label_file.name} / 第 {index} 项：box 超出图片范围")

    missing_labels = [image.name for image in images if image.stem not in label_stems]
    lines = [
        f"数据集目录：{dataset_dir}",
        f"图片数量：{len(images)}",
        f"标注文件：{len(labels)}",
        f"标注总数：{total_items}",
        f"REMAINING：{target_counts['remaining']}",
        f"行线索：{target_counts['row']}",
        f"格内线索：{target_counts['cell']}",
        f"其它文本：{target_counts['other']}",
        f"缺少标注的图片：{len(missing_labels)}",
        f"格式问题：{len(invalid)}",
    ]
    if missing_labels:
        lines.append("")
        lines.append("缺少标注的图片：")
        lines.extend(f"- {name}" for name in missing_labels[:30])
    if invalid:
        lines.append("")
        lines.append("格式问题：")
        lines.extend(f"- {item}" for item in invalid[:50])
    return "\n".join(lines)


class OCRDatasetTool:
    def __init__(self, root: tk.Tk, dataset_dir: Path) -> None:
        self.root = root
        self.dataset_dir = resolve_dataset_dir(dataset_dir)
        self.dirs = dataset_dirs(self.dataset_dir)
        ensure_dataset(self.dataset_dir)

        self.root.title("Hexsolver OCR 测试集标注工具")
        self.root.geometry("1320x840")
        self.root.minsize(1060, 700)

        self.images: List[Path] = []
        self.current_index = -1
        self.current_image_path: Optional[Path] = None
        self.current_pil: Optional[Image.Image] = None
        self.view: Optional[ImageView] = None
        self.label_doc: Dict[str, Any] = {}
        self.selected_index: Optional[int] = None
        self.drag_start: Optional[Tuple[float, float]] = None
        self.pending_box: Optional[List[int]] = None
        self.dirty = False

        self.target_var = tk.StringVar(value=TARGET_LABELS["row"])
        self.family_var = tk.StringVar(value=FAMILY_LABELS["unknown"])
        self.text_var = tk.StringVar()
        self.coord_var = tk.StringVar()
        self.note_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请先导入或打开一张截图。")

        self._build_ui()
        self._refresh_image_list()
        if self.images:
            self.load_image(0)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=0)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=8)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(left, bg="#20242b", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())

        status = ttk.Label(left, textvariable=self.status_var, anchor="w")
        status.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        right = ttk.Frame(self.root, padding=10, width=330)
        right.grid(row=0, column=1, sticky="ns")
        right.grid_propagate(False)
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="数据集").grid(row=0, column=0, sticky="w")
        ttk.Label(right, text=str(self.dataset_dir), foreground="#555").grid(row=1, column=0, sticky="ew", pady=(0, 8))

        buttons = ttk.Frame(right)
        buttons.grid(row=2, column=0, sticky="ew")
        buttons.columnconfigure((0, 1), weight=1)
        ttk.Button(buttons, text="导入图片", command=self.import_images_dialog).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="保存", command=self.save_label).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        nav = ttk.Frame(right)
        nav.grid(row=3, column=0, sticky="ew", pady=(8, 8))
        nav.columnconfigure((0, 1), weight=1)
        ttk.Button(nav, text="上一张", command=self.previous_image).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(nav, text="下一张", command=self.next_image).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Separator(right).grid(row=4, column=0, sticky="ew", pady=8)

        form = ttk.Frame(right)
        form.grid(row=5, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="类型").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(
            form,
            textvariable=self.target_var,
            values=list(TARGET_LABELS.values()),
            state="readonly",
            width=16,
        ).grid(row=0, column=1, sticky="ew", pady=3)

        ttk.Label(form, text="文本").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.text_var).grid(row=1, column=1, sticky="ew", pady=3)

        ttk.Label(form, text="方向").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(
            form,
            textvariable=self.family_var,
            values=list(FAMILY_LABELS.values()),
            state="readonly",
            width=16,
        ).grid(row=2, column=1, sticky="ew", pady=3)

        ttk.Label(form, text="坐标/行号").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.coord_var).grid(row=3, column=1, sticky="ew", pady=3)

        ttk.Label(form, text="备注").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.note_var).grid(row=4, column=1, sticky="ew", pady=3)

        edit_buttons = ttk.Frame(right)
        edit_buttons.grid(row=6, column=0, sticky="ew", pady=(8, 8))
        edit_buttons.columnconfigure((0, 1), weight=1)
        ttk.Button(edit_buttons, text="添加标注", command=self.add_annotation).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(edit_buttons, text="删除选中", command=self.delete_selected).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Button(right, text="数据集统计/检查", command=self.show_summary).grid(row=7, column=0, sticky="ew")

        ttk.Separator(right).grid(row=8, column=0, sticky="ew", pady=8)

        ttk.Label(right, text="当前标注").grid(row=9, column=0, sticky="w")
        list_frame = ttk.Frame(right)
        list_frame.grid(row=10, column=0, sticky="nsew")
        right.rowconfigure(10, weight=1)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.annotation_list = tk.Listbox(list_frame, height=18, activestyle="none")
        self.annotation_list.grid(row=0, column=0, sticky="nsew")
        self.annotation_list.bind("<<ListboxSelect>>", self._on_select_annotation)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.annotation_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.annotation_list.configure(yscrollcommand=scrollbar.set)

        help_text = (
            "操作：左键拖框，输入文本，再点添加。\n"
            "格式：普通数字 3，连续 {3}，非连续 -3-，未知 ?。\n"
            "快捷键：Ctrl+S 保存，Delete 删除选中。"
        )
        ttk.Label(right, text=help_text, foreground="#555", justify="left").grid(row=11, column=0, sticky="ew", pady=(8, 0))

        self.root.bind("<Control-s>", lambda _event: self.save_label())
        self.root.bind("<Delete>", lambda _event: self.delete_selected())

    def _refresh_image_list(self) -> None:
        self.images = image_files(self.dirs["images"])

    def import_images_dialog(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择 Hexcells 截图",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp *.webp"),
                ("所有文件", "*.*"),
            ],
        )
        if not paths:
            return

        imported: List[Path] = []
        for raw_path in paths:
            try:
                imported.append(import_image(Path(raw_path), self.dataset_dir))
            except Exception as exc:
                messagebox.showerror("导入失败", str(exc))

        self._refresh_image_list()
        if imported:
            first = imported[0]
            for index, path in enumerate(self.images):
                if path == first:
                    self.load_image(index)
                    break

    def previous_image(self) -> None:
        if not self.images:
            return
        self._autosave_if_needed()
        self.load_image(max(0, self.current_index - 1))

    def next_image(self) -> None:
        if not self.images:
            return
        self._autosave_if_needed()
        self.load_image(min(len(self.images) - 1, self.current_index + 1))

    def load_image(self, index: int) -> None:
        if index < 0 or index >= len(self.images):
            return
        self.current_index = index
        self.current_image_path = self.images[index]
        self.current_pil = Image.open(self.current_image_path).convert("RGB")
        label_file = label_path_for(self.current_image_path, self.dataset_dir)
        if label_file.exists():
            self.label_doc = json.loads(label_file.read_text(encoding="utf-8"))
        else:
            self.label_doc = empty_label_doc(self.current_image_path, self.current_pil)
        for item in self.label_doc.get("items", []):
            item["family"] = normalize_family(str(item.get("family", "unknown")))
        self.selected_index = None
        self.pending_box = None
        self.dirty = False
        self._refresh_annotation_list()
        self.status_var.set(f"{self.current_image_path.name} ({self.current_index + 1}/{len(self.images)})")
        self.redraw()

    def save_label(self) -> None:
        if self.current_image_path is None or self.current_pil is None:
            return
        label_file = label_path_for(self.current_image_path, self.dataset_dir)
        self.label_doc["image"] = {
            "file": self.current_image_path.name,
            "width": self.current_pil.width,
            "height": self.current_pil.height,
        }
        label_file.write_text(json.dumps(self.label_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        self.dirty = False
        self.status_var.set(f"已保存：{label_file.name}")

    def _autosave_if_needed(self) -> None:
        if self.dirty:
            self.save_label()

    def _image_to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        if self.view is None:
            return x, y
        return x * self.view.scale + self.view.offset_x, y * self.view.scale + self.view.offset_y

    def _canvas_to_image(self, x: float, y: float) -> Tuple[float, float]:
        if self.view is None or self.current_pil is None:
            return x, y
        ix = (x - self.view.offset_x) / self.view.scale
        iy = (y - self.view.offset_y) / self.view.scale
        ix = max(0.0, min(float(self.current_pil.width), ix))
        iy = max(0.0, min(float(self.current_pil.height), iy))
        return ix, iy

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.current_pil is None:
            self.canvas.create_text(
                40,
                40,
                text="请点击右侧“导入图片”开始制作 OCR 测试集。",
                fill="#f2f2f2",
                anchor="nw",
                font=("Microsoft YaHei", 16),
            )
            return

        canvas_w = max(200, self.canvas.winfo_width())
        canvas_h = max(200, self.canvas.winfo_height())
        scale = min(canvas_w / self.current_pil.width, canvas_h / self.current_pil.height)
        display_w = max(1, int(round(self.current_pil.width * scale)))
        display_h = max(1, int(round(self.current_pil.height * scale)))
        offset_x = (canvas_w - display_w) / 2.0
        offset_y = (canvas_h - display_h) / 2.0

        resized = self.current_pil.resize((display_w, display_h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(resized)
        self.view = ImageView(self.current_pil, photo, scale, offset_x, offset_y)
        self.canvas.create_image(offset_x, offset_y, image=photo, anchor="nw")

        for index, item in enumerate(self.label_doc.get("items", [])):
            box = item.get("box", [0, 0, 0, 0])
            x0, y0 = self._image_to_canvas(box[0], box[1])
            x1, y1 = self._image_to_canvas(box[2], box[3])
            target = item.get("target", "other")
            color = TARGET_COLORS.get(target, "#ffffff")
            width = 4 if index == self.selected_index else 2
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=width)
            label = f"{index + 1}. {TARGET_LABELS.get(target, target)} {item.get('text', '')}"
            self.canvas.create_text(x0 + 4, y0 + 4, text=label, fill=color, anchor="nw", font=("Microsoft YaHei", 10, "bold"))

        if self.pending_box is not None:
            x0, y0 = self._image_to_canvas(self.pending_box[0], self.pending_box[1])
            x1, y1 = self._image_to_canvas(self.pending_box[2], self.pending_box[3])
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#ffffff", width=2, dash=(5, 3))

    def _on_mouse_down(self, event: tk.Event) -> None:
        if self.current_pil is None:
            return
        self.drag_start = self._canvas_to_image(event.x, event.y)
        self.pending_box = None

    def _on_mouse_move(self, event: tk.Event) -> None:
        if self.current_pil is None or self.drag_start is None:
            return
        x0, y0 = self.drag_start
        x1, y1 = self._canvas_to_image(event.x, event.y)
        self.pending_box = normalize_box((x0, y0, x1, y1), self.current_pil.width, self.current_pil.height)
        self.redraw()

    def _on_mouse_up(self, event: tk.Event) -> None:
        if self.current_pil is None or self.drag_start is None:
            return
        x0, y0 = self.drag_start
        x1, y1 = self._canvas_to_image(event.x, event.y)
        box = normalize_box((x0, y0, x1, y1), self.current_pil.width, self.current_pil.height)
        self.drag_start = None
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            self.pending_box = None
            self.redraw()
            return
        self.pending_box = box
        self.status_var.set(f"已选择区域：{box}。请输入文本并添加标注。")
        self.redraw()

    def add_annotation(self) -> None:
        if self.current_pil is None:
            messagebox.showwarning("没有图片", "请先导入图片。")
            return
        if self.pending_box is None:
            messagebox.showwarning("没有框选区域", "请先在图片上拖出一个 OCR 文本框。")
            return

        target = LABEL_TO_TARGET.get(self.target_var.get(), "row")
        family = LABEL_TO_FAMILY.get(self.family_var.get(), "unknown")
        text = self.text_var.get().strip().replace(" ", "")
        coord = self.coord_var.get().strip()
        note = self.note_var.get().strip()

        item = {
            "id": f"A{len(self.label_doc.get('items', [])) + 1:04d}",
            "target": target,
            "text": text,
            "box": self.pending_box,
            "family": family,
            "coord": coord,
            "note": note,
        }
        error = validate_item(item)
        if error:
            messagebox.showwarning("标注格式需要检查", error)
            return

        self.label_doc.setdefault("items", []).append(item)
        self.pending_box = None
        self.text_var.set("")
        self.coord_var.set("")
        self.note_var.set("")
        self.selected_index = len(self.label_doc["items"]) - 1
        self.dirty = True
        self._refresh_annotation_list()
        self.redraw()
        self.status_var.set("已添加标注。")

    def delete_selected(self) -> None:
        if self.selected_index is None:
            return
        items = self.label_doc.get("items", [])
        if self.selected_index < 0 or self.selected_index >= len(items):
            return
        del items[self.selected_index]
        for index, item in enumerate(items, start=1):
            item["id"] = f"A{index:04d}"
        self.selected_index = None
        self.dirty = True
        self._refresh_annotation_list()
        self.redraw()

    def _refresh_annotation_list(self) -> None:
        self.annotation_list.delete(0, tk.END)
        for index, item in enumerate(self.label_doc.get("items", []), start=1):
            target = TARGET_LABELS.get(item.get("target", ""), item.get("target", ""))
            text = item.get("text", "")
            family = FAMILY_LABELS.get(normalize_family(str(item.get("family", "unknown"))), "")
            coord = item.get("coord", "")
            suffix = f" / {family}" if item.get("target") == "row" else ""
            if coord:
                suffix += f" / {coord}"
            self.annotation_list.insert(tk.END, f"{index:02d}. {target} = {text}{suffix}")

        if self.selected_index is not None and self.selected_index < self.annotation_list.size():
            self.annotation_list.selection_set(self.selected_index)
            self.annotation_list.see(self.selected_index)

    def _on_select_annotation(self, _event: tk.Event) -> None:
        selection = self.annotation_list.curselection()
        if not selection:
            return
        self.selected_index = int(selection[0])
        item = self.label_doc.get("items", [])[self.selected_index]
        self.target_var.set(TARGET_LABELS.get(item.get("target", "row"), TARGET_LABELS["row"]))
        self.family_var.set(FAMILY_LABELS.get(normalize_family(str(item.get("family", "unknown"))), FAMILY_LABELS["unknown"]))
        self.text_var.set(str(item.get("text", "")))
        self.coord_var.set(str(item.get("coord", "")))
        self.note_var.set(str(item.get("note", "")))
        self.redraw()

    def show_summary(self) -> None:
        self._autosave_if_needed()
        messagebox.showinfo("数据集统计", summarize_dataset(self.dataset_dir))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hexsolver OCR 测试集制作工具")
    parser.add_argument("--dataset", default=DEFAULT_DATASET_DIR, help=f"测试集目录，默认 {DEFAULT_DATASET_DIR}")
    parser.add_argument("--init", action="store_true", help="创建测试集目录")
    parser.add_argument("--import-dir", help="导入一个目录中的图片")
    parser.add_argument("--summary", action="store_true", help="输出测试集统计和格式检查")
    parser.add_argument("--gui", action="store_true", help="执行命令后继续打开图形界面")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_dir = resolve_dataset_dir(Path(args.dataset))
    performed_command = False

    if args.init:
        ensure_dataset(dataset_dir)
        print(f"已创建测试集目录：{dataset_dir}")
        performed_command = True

    if args.import_dir:
        count = import_directory(Path(args.import_dir).resolve(), dataset_dir)
        print(f"已导入图片：{count} 张")
        performed_command = True

    if args.summary:
        print(summarize_dataset(dataset_dir))
        performed_command = True

    if performed_command and not args.gui:
        return

    root = tk.Tk()
    OCRDatasetTool(root, dataset_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
