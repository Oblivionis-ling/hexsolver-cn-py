from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageGrab, ImageOps, ImageTk

from .detector import DetectionError, HexImageDetector
from .models import Board, Cell, CellVisualType, ClueType, Coord, MoveAction, OCRObservation, RowClue, SuggestedMove
from .solver import HexReasoningSolver, SolverError


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class MainWindow:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title("Hexcells 中文求解工作台")
        self.root.minsize(1760, 1020)
        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.geometry("1920x1160")

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        asset_dir = os.path.join(base_dir, "src", "hexsolver_cn", "assets")
        self.detector = HexImageDetector(asset_dir)
        self.solver = HexReasoningSolver()

        self.board: Optional[Board] = None
        self.current_image: Optional[Image.Image] = None
        self.current_image_path: Optional[str] = None
        self.photo: Optional[ImageTk.PhotoImage] = None
        self.preview_photo: Optional[ctk.CTkImage] = None
        self.moves: List[SuggestedMove] = []

        self.zoom_factor = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.fit_scale = 1.0
        self.render_scale = 1.0
        self.drag_origin: Optional[Tuple[int, int]] = None

        self.canvas_cell_centers: Dict[Coord, Tuple[float, float]] = {}
        self.canvas_row_anchors: Dict[str, Tuple[float, float]] = {}
        self.canvas_observation_boxes: Dict[int, Tuple[float, float, float, float]] = {}

        self.selected_row_id: Optional[str] = None
        self.selected_cell_coord: Optional[Coord] = None
        self.selected_observation_index: Optional[int] = None
        self.selected_move_index: Optional[int] = None

        self.remaining_var = tk.StringVar(value="")
        self.remaining_hint_var = tk.StringVar(value="REMAINING 尚未识别")
        self.status_var = tk.StringVar(value="准备就绪")
        self.header_title_var = tk.StringVar(value="还没有导入截图")
        self.header_subtitle_var = tk.StringVar(value="导入截图后，这里会显示 OCR 检测、线索校对和解题叠图。")
        self.selection_title_var = tk.StringVar(value="检查台待命中")
        self.selection_meta_var = tk.StringVar(value="点击棋盘、行线索、OCR 框或解题步骤，这里会显示上下文。")
        self.selection_hint_var = tk.StringVar(value="如果 OCR 和线索对不上，可以同时选中线索与 OCR 框，再一键绑定。")

        self.show_cell_overlay_var = tk.BooleanVar(value=True)
        self.show_line_var = tk.BooleanVar(value=True)
        self.show_ocr_box_var = tk.BooleanVar(value=True)
        self.show_solution_var = tk.BooleanVar(value=True)
        self.pending_only_var = tk.BooleanVar(value=False)

        self.summary_rows_var = tk.StringVar(value="行线索：0")
        self.summary_cells_var = tk.StringVar(value="格内线索：0")
        self.summary_ocr_var = tk.StringVar(value="OCR 框：0")
        self.summary_moves_var = tk.StringVar(value="解题建议：0")

        self._configure_ttk_styles()
        self._build_layout()
        self._set_log(
            "推荐流程：\n"
            "1. 导入截图。\n"
            "2. 点击“自动识别 + OCR”。\n"
            "3. 先在“行线索”与“格内线索”页查看高亮的低置信项目。\n"
            "4. 如有需要，在“原始 OCR”页查看整图 OCR 框，再回到对应条目进行修正。\n"
            "5. 点击“开始求解”，右侧大图会直接叠加步骤建议。"
        )
        self.refresh_selection_panel()

    def _configure_ttk_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 10), background="#f8f5ef", fieldbackground="#f8f5ef")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_layout(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self.root, corner_radius=0, fg_color="#f5efe5")
        top.grid(row=0, column=0, columnspan=2, sticky="nsew")
        top.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=18, pady=14)
        ctk.CTkLabel(brand, text="Hexcells 中文求解工作台", font=ctk.CTkFont("Microsoft YaHei UI", 24, "bold"), text_color="#2f241d").pack(anchor="w")
        ctk.CTkLabel(
            brand,
            text="更现代的界面、更细的 OCR 审阅流程，以及和截图联动的解题叠图。",
            font=ctk.CTkFont("Microsoft YaHei UI", 12),
            text_color="#6b584d",
        ).pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(
            brand,
            textvariable=self.status_var,
            font=ctk.CTkFont("Microsoft YaHei UI", 11, "bold"),
            text_color="#b45309",
        ).pack(anchor="w", pady=(6, 0))

        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e", padx=18, pady=14)
        self._toolbar_button(actions, "导入截图", self.import_image, True).grid(row=0, column=0, padx=6)
        self._toolbar_button(actions, "加载示例", self.load_example_image, False).grid(row=0, column=1, padx=6)
        self._toolbar_button(actions, "自动识别 + OCR", self.detect_board, True).grid(row=0, column=2, padx=6)
        self._toolbar_button(actions, "开始求解", self.solve_board, False).grid(row=0, column=3, padx=6)
        self._toolbar_button(actions, "重置视图", self.reset_view, False).grid(row=0, column=4, padx=6)
        self._toolbar_button(actions, "导出叠图", self.export_overlay_image, False).grid(row=0, column=5, padx=6)

        sidebar = ctk.CTkFrame(self.root, width=560, corner_radius=0, fg_color="#f1ece3")
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(3, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        viewer = ctk.CTkFrame(self.root, corner_radius=0, fg_color="#151a22")
        viewer.grid(row=1, column=1, sticky="nsew")
        viewer.grid_rowconfigure(1, weight=1)
        viewer.grid_columnconfigure(0, weight=1)

        self._build_sidebar(sidebar)
        self._build_viewer(viewer)

    def _toolbar_button(self, parent: ctk.CTkFrame, text: str, command, primary: bool) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=124,
            height=36,
            fg_color="#d97736" if primary else "#e5d9c8",
            hover_color="#bf662c" if primary else "#d7c5af",
            text_color="#ffffff" if primary else "#2d241f",
            font=ctk.CTkFont("Microsoft YaHei UI", 11, "bold"),
            corner_radius=10,
        )

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        summary = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=14)
        summary.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        summary.grid_columnconfigure((0, 1), weight=1)

        for index, (title, variable) in enumerate(
            [
                ("行线索", self.summary_rows_var),
                ("格内线索", self.summary_cells_var),
                ("OCR 框", self.summary_ocr_var),
                ("解题建议", self.summary_moves_var),
            ]
        ):
            card = ctk.CTkFrame(summary, fg_color="#efe4d3", corner_radius=12)
            card.grid(row=index // 2, column=index % 2, sticky="ew", padx=6, pady=6)
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont("Microsoft YaHei UI", 11, "bold"), text_color="#5c4a3f").pack(anchor="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(card, textvariable=variable, font=ctk.CTkFont("Consolas", 14, "bold"), text_color="#2c241f").pack(anchor="w", padx=12, pady=(2, 10))

        remain = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=14)
        remain.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        ctk.CTkLabel(remain, text="REMAINING / 全局剩余蓝格", font=ctk.CTkFont("Microsoft YaHei UI", 13, "bold"), text_color="#2d241f").pack(anchor="w", padx=12, pady=(10, 6))
        ctk.CTkEntry(remain, textvariable=self.remaining_var, font=ctk.CTkFont("Consolas", 14), height=36, corner_radius=10).pack(fill="x", padx=12)
        ctk.CTkLabel(remain, textvariable=self.remaining_hint_var, justify="left", wraplength=470, font=ctk.CTkFont("Microsoft YaHei UI", 11), text_color="#6a584a").pack(anchor="w", padx=12, pady=(8, 10))

        toggles = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=14)
        toggles.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
        ctk.CTkLabel(toggles, text="叠图内容", font=ctk.CTkFont("Microsoft YaHei UI", 13, "bold"), text_color="#2d241f").pack(anchor="w", padx=12, pady=(10, 4))
        self._switch(toggles, "棋盘格与格内线索", self.show_cell_overlay_var).pack(anchor="w", padx=12, pady=2)
        self._switch(toggles, "行编号与行 OCR", self.show_line_var).pack(anchor="w", padx=12, pady=2)
        self._switch(toggles, "原始 OCR 框", self.show_ocr_box_var).pack(anchor="w", padx=12, pady=2)
        self._switch(toggles, "求解建议叠图", self.show_solution_var).pack(anchor="w", padx=12, pady=(2, 10))

        tabs = ctk.CTkTabview(parent, corner_radius=14, segmented_button_fg_color="#e6ddcf", segmented_button_selected_color="#d97736", segmented_button_selected_hover_color="#bf662c")
        tabs.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 16))
        tabs.add("检查台")
        tabs.add("行线索")
        tabs.add("格内线索")
        tabs.add("原始 OCR")
        tabs.add("解题步骤")
        tabs.add("日志")

        self._build_inspector_tab(tabs.tab("检查台"))
        self._build_row_tab(tabs.tab("行线索"))
        self._build_cell_tab(tabs.tab("格内线索"))
        self._build_observation_tab(tabs.tab("原始 OCR"))
        self._build_result_tab(tabs.tab("解题步骤"))
        self._build_log_tab(tabs.tab("日志"))

    def _switch(self, parent: ctk.CTkFrame, text: str, variable: tk.BooleanVar) -> ctk.CTkSwitch:
        return ctk.CTkSwitch(
            parent,
            text=text,
            variable=variable,
            onvalue=True,
            offvalue=False,
            command=self.redraw,
            font=ctk.CTkFont("Microsoft YaHei UI", 11),
            text_color="#463830",
            progress_color="#d97736",
        )

    def _build_inspector_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        hero = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=12)
        hero.grid(row=0, column=0, sticky="ew", padx=6, pady=(10, 8))
        ctk.CTkLabel(hero, textvariable=self.selection_title_var, font=ctk.CTkFont("Microsoft YaHei UI", 15, "bold"), text_color="#2d241f").pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(hero, textvariable=self.selection_meta_var, justify="left", wraplength=500, font=ctk.CTkFont("Microsoft YaHei UI", 11), text_color="#5f5046").pack(anchor="w", padx=12)
        ctk.CTkLabel(hero, textvariable=self.selection_hint_var, justify="left", wraplength=500, font=ctk.CTkFont("Microsoft YaHei UI", 11), text_color="#b45309").pack(anchor="w", padx=12, pady=(8, 10))

        preview_frame = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=12)
        preview_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 8))
        ctk.CTkLabel(preview_frame, text="局部放大预览", font=ctk.CTkFont("Microsoft YaHei UI", 12, "bold"), text_color="#2d241f").pack(anchor="w", padx=12, pady=(10, 6))
        self.preview_label = ctk.CTkLabel(preview_frame, text="选中对象后，这里会显示截图局部。", width=500, height=180, fg_color="#efe4d3", corner_radius=10, text_color="#7a685c")
        self.preview_label.pack(fill="x", padx=12, pady=(0, 10))

        actions = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=12)
        actions.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 10))
        actions.grid_columnconfigure((0, 1), weight=1)
        actions.grid_rowconfigure(2, weight=1)
        self._mini_button(actions, "将所选 OCR 用于行", self.apply_selected_observation_to_row).grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 6))
        self._mini_button(actions, "将所选 OCR 用于格", self.apply_selected_observation_to_cell).grid(row=0, column=1, sticky="ew", padx=8, pady=(10, 6))
        self._mini_button(actions, "设为 REMAINING", self.apply_selected_observation_to_remaining).grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 6))
        self._mini_button(actions, "编辑当前对象", self.edit_current_selection).grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 6))
        self.selection_text = ctk.CTkTextbox(actions, corner_radius=10, fg_color="#efe4d3", font=ctk.CTkFont("Microsoft YaHei UI", 11))
        self.selection_text.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=(4, 10))

    def _build_row_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=6, pady=(10, 8))
        self.pending_switch = ctk.CTkSwitch(
            top,
            text="只看待确认行线索",
            variable=self.pending_only_var,
            command=self.refresh_row_tree,
            progress_color="#d97736",
            font=ctk.CTkFont("Microsoft YaHei UI", 11),
        )
        self.pending_switch.pack(side="left")
        self._mini_button(top, "采用高置信 OCR", self.apply_high_confidence_row_ocr).pack(side="right", padx=4)

        table_frame = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=12)
        table_frame.grid(row=1, column=0, sticky="nsew", padx=6)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        columns = ("id", "方向", "长度", "OCR", "当前", "置信", "来源", "状态")
        self.row_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)
        widths = {"id": 64, "方向": 72, "长度": 56, "OCR": 84, "当前": 84, "置信": 56, "来源": 84, "状态": 68}
        for column in columns:
            self.row_tree.heading(column, text=column)
            self.row_tree.column(column, width=widths[column], anchor=tk.CENTER)
        self.row_tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.row_tree.tag_configure("confirmed", background="#e7f5ea")
        self.row_tree.tag_configure("pending", background="#fff5df")
        self.row_tree.tag_configure("missing", background="#f8e8e4")
        self.row_tree.bind("<<TreeviewSelect>>", self.on_row_selected)
        self.row_tree.bind("<Double-1>", lambda _event: self.edit_selected_row())

        row_actions = ctk.CTkFrame(parent, fg_color="transparent")
        row_actions.grid(row=2, column=0, sticky="ew", padx=6, pady=(8, 10))
        self._mini_button(row_actions, "编辑选中行", self.edit_selected_row).pack(side="left", padx=4)
        self._mini_button(row_actions, "采用选中 OCR", self.apply_selected_row_ocr).pack(side="left", padx=4)
        self._mini_button(row_actions, "清空选中行", self.clear_selected_row).pack(side="left", padx=4)

    def _build_cell_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        frame = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=12)
        frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=(10, 8))
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        columns = ("坐标", "类型", "OCR", "当前", "置信", "来源")
        self.cell_tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        widths = {"坐标": 90, "类型": 62, "OCR": 72, "当前": 72, "置信": 56, "来源": 78}
        for column in columns:
            self.cell_tree.heading(column, text=column)
            self.cell_tree.column(column, width=widths[column], anchor=tk.CENTER)
        self.cell_tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.cell_tree.tag_configure("low", background="#fff4df")
        self.cell_tree.tag_configure("high", background="#eaf5ed")
        self.cell_tree.bind("<<TreeviewSelect>>", self.on_cell_selected)
        self.cell_tree.bind("<Double-1>", lambda _event: self.edit_selected_cell())

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 10))
        self._mini_button(actions, "编辑选中格", self.edit_selected_cell).pack(side="left", padx=4)
        self._mini_button(actions, "恢复到 OCR", self.restore_selected_cell_ocr).pack(side="left", padx=4)
        self._mini_button(actions, "清空当前线索", self.clear_selected_cell_clue).pack(side="left", padx=4)

    def _build_observation_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        frame = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=12)
        frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=(10, 8))
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        columns = ("文本", "置信", "框")
        self.obs_tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        widths = {"文本": 90, "置信": 56, "框": 220}
        for column in columns:
            self.obs_tree.heading(column, text=column)
            self.obs_tree.column(column, width=widths[column], anchor=tk.CENTER)
        self.obs_tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.obs_tree.tag_configure("low", background="#fff4df")
        self.obs_tree.bind("<<TreeviewSelect>>", self.on_observation_selected)
        self.obs_tree.bind("<Double-1>", lambda _event: self.apply_selected_observation())

    def _build_result_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        frame = ctk.CTkFrame(parent, fg_color="#fbf8f3", corner_radius=12)
        frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=(10, 8))
        frame.grid_columnconfigure(0, weight=1)
        columns = ("动作", "坐标", "来源")
        self.result_tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        widths = {"动作": 80, "坐标": 100, "来源": 96}
        for column in columns:
            self.result_tree.heading(column, text=column)
            self.result_tree.column(column, width=widths[column], anchor=tk.CENTER)
        self.result_tree.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.result_tree.bind("<<TreeviewSelect>>", self.on_result_selected)

        self.result_text = ctk.CTkTextbox(parent, corner_radius=12, fg_color="#fbf8f3", font=ctk.CTkFont("Microsoft YaHei UI", 12))
        self.result_text.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 10))

    def _build_log_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        self.log_text = ctk.CTkTextbox(parent, corner_radius=12, fg_color="#fbf8f3", font=ctk.CTkFont("Consolas", 11))
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=(10, 10))

    def _mini_button(self, parent: ctk.CTkFrame, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=32,
            fg_color="#e5d9c8",
            hover_color="#d7c5af",
            text_color="#2d241f",
            font=ctk.CTkFont("Microsoft YaHei UI", 11, "bold"),
            corner_radius=10,
        )

    def _build_viewer(self, parent: ctk.CTkFrame) -> None:
        header = ctk.CTkFrame(parent, fg_color="#181f29", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, textvariable=self.header_title_var, anchor="w", font=ctk.CTkFont("Microsoft YaHei UI", 18, "bold"), text_color="#f7f2ec").grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 2))
        ctk.CTkLabel(header, textvariable=self.header_subtitle_var, anchor="w", justify="left", wraplength=1080, font=ctk.CTkFont("Microsoft YaHei UI", 12), text_color="#c8d0da").grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

        canvas_holder = ctk.CTkFrame(parent, fg_color="#11161d", corner_radius=0)
        canvas_holder.grid(row=1, column=0, sticky="nsew")
        canvas_holder.grid_rowconfigure(0, weight=1)
        canvas_holder.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_holder, bg="#11161d", highlightthickness=0, cursor="tcross")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-3>", self.on_pan_start)
        self.canvas.bind("<B3-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonRelease-3>", self.on_pan_end)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)

    def import_image(self) -> None:
        path = filedialog.askopenfilename(
            title="请选择截图文件",
            filetypes=[("图片文件", "*.png;*.jpg;*.jpeg"), ("所有文件", "*.*")],
        )
        if path:
            self._load_image(path)

    def load_example_image(self) -> None:
        example = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "..",
                "HexSolver-master",
                "HexSolver",
                "example",
                "shot001.png",
            )
        )
        if not os.path.exists(example):
            messagebox.showerror("找不到示例", "没有找到工作区里的示例截图。")
            return
        self._load_image(example)

    def _load_image(self, path: str) -> None:
        self.current_image = Image.open(path).convert("RGB")
        self.current_image_path = path
        self.board = None
        self.moves = []
        self.selected_row_id = None
        self.selected_cell_coord = None
        self.selected_observation_index = None
        self.selected_move_index = None
        self.remaining_var.set("")
        self.remaining_hint_var.set("请先执行自动识别 + OCR")
        self.header_title_var.set(os.path.basename(path))
        self.header_subtitle_var.set("截图已载入。你可以直接开始识别，也可以缩放、平移检查原图。")
        self.zoom_factor = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.refresh_all_lists()
        self._clear_results()
        self.update_summary()
        self.refresh_selection_panel()
        self._append_log(f"已载入截图：{path}")
        self.status_var.set("截图已载入")
        self.redraw()

    def detect_board(self) -> None:
        if self.current_image is None or not self.current_image_path:
            messagebox.showwarning("还没有截图", "请先导入一张截图。")
            return
        try:
            board = self.detector.detect_board(self.current_image_path)
        except DetectionError as exc:
            messagebox.showerror("识别失败", str(exc))
            self.status_var.set("识别失败")
            return

        self.board = board
        self.moves = []
        self.selected_row_id = None
        self.selected_cell_coord = None
        self.selected_observation_index = None
        self.selected_move_index = None

        if board.remaining_ocr_text:
            self.remaining_var.set(board.remaining_ocr_text)
            if board.remaining_blue is not None:
                self.remaining_hint_var.set(f"OCR 已识别 REMAINING = {board.remaining_blue}，来源：{board.remaining_ocr_source}")
            else:
                self.remaining_hint_var.set(f"OCR 检测到疑似 REMAINING = {board.remaining_ocr_text}，请确认")
        else:
            self.remaining_var.set("")
            self.remaining_hint_var.set("OCR 没有识别到 REMAINING，请手动填写")

        self.header_subtitle_var.set(
            f"识别完成：{len(board.cells)} 个棋盘位置，{len(board.row_clues)} 条行线索，"
            f"{len(board.ocr_observations)} 个整图 OCR 框。"
        )
        self.refresh_all_lists()
        self._clear_results()
        self.update_summary()
        self.refresh_selection_panel()
        self._set_log("\n".join(board.logs))
        self.status_var.set("识别完成")
        self.reset_view()

    def solve_board(self) -> None:
        if self.board is None:
            messagebox.showwarning("没有棋盘", "请先执行自动识别 + OCR。")
            return

        remain_text = self.remaining_var.get().strip()
        if remain_text:
            if not remain_text.isdigit():
                messagebox.showerror("输入错误", "REMAINING 必须是整数。")
                return
            self.board.remaining_blue = int(remain_text)
        else:
            self.board.remaining_blue = None

        try:
            self.moves = self.solver.solve(self.board)
        except SolverError as exc:
            messagebox.showerror("求解失败", str(exc))
            self.status_var.set("求解失败")
            return

        self.selected_move_index = None
        self.refresh_result_tree()
        self.update_summary()
        if self.moves:
            self.status_var.set(f"求解完成：{len(self.moves)} 条建议已叠加到右侧截图")
            self._append_log(f"求解完成：共得到 {len(self.moves)} 条建议。")
        else:
            self.status_var.set("求解完成，但没有发现新的必然步")
            self._append_log("求解完成：当前没有新的必然步。")
        self.refresh_selection_panel()
        self.redraw()

    def export_overlay_image(self) -> None:
        if self.current_image is None:
            messagebox.showwarning("还没有截图", "请先导入截图，再导出叠图。")
            return
        path = filedialog.asksaveasfilename(
            title="导出当前叠图",
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png")],
        )
        if not path:
            return
        try:
            self.root.update_idletasks()
            x0 = self.canvas.winfo_rootx()
            y0 = self.canvas.winfo_rooty()
            x1 = x0 + self.canvas.winfo_width()
            y1 = y0 + self.canvas.winfo_height()
            ImageGrab.grab(bbox=(x0, y0, x1, y1)).save(path)
        except Exception as exc:
            messagebox.showerror("导出失败", f"无法导出当前叠图：{exc}")
            return
        self.status_var.set(f"已导出叠图：{path}")

    def apply_selected_observation(self) -> None:
        if self.selected_row_id is not None:
            self.apply_selected_observation_to_row()
            return
        if self.selected_cell_coord is not None:
            self.apply_selected_observation_to_cell()
            return
        self.apply_selected_observation_to_remaining()

    def apply_selected_observation_to_row(self) -> None:
        row = self._selected_row()
        observation = self._selected_observation()
        if row is None or observation is None:
            messagebox.showinfo("缺少选择", "请先同时选中一条行线索和一个 OCR 框。")
            return
        matched = self.detector.match_row_observation(row, observation.text)
        if not matched.text:
            messagebox.showinfo("无法匹配", "这个 OCR 框暂时无法映射成当前行线索的合法格式。")
            return
        parsed_text, parsed_type, parsed_number = self.detector.parse_clue_text(matched.text)
        row.ocr_text = matched.text
        row.ocr_score = float(matched.score)
        row.ocr_source = "手动指定 OCR 框"
        row.ocr_box = observation.box
        row.clue_text = parsed_text
        row.clue_type = parsed_type
        row.clue_number = parsed_number
        self.refresh_row_tree()
        self.update_summary()
        self.refresh_selection_panel()
        self.redraw()
        self.status_var.set(f"已将 OCR 框“{observation.text}”绑定到 {row.line_id}")

    def apply_selected_observation_to_cell(self) -> None:
        cell = self._selected_cell()
        observation = self._selected_observation()
        if cell is None or observation is None or self.board is None:
            messagebox.showinfo("缺少选择", "请先同时选中一个格内线索和一个 OCR 框。")
            return
        matched = self.detector.match_cell_observation(self.board, cell, observation.text)
        if not matched.text:
            messagebox.showinfo("无法匹配", "这个 OCR 框暂时无法映射成当前格内线索的合法格式。")
            return
        parsed_text, parsed_type, parsed_number = self.detector.parse_clue_text(matched.text)
        cell.ocr_text = matched.text
        cell.ocr_score = float(matched.score)
        cell.ocr_source = "手动指定 OCR 框"
        cell.ocr_box = observation.box
        cell.clue_text = parsed_text
        cell.clue_type = parsed_type
        cell.clue_number = parsed_number
        self.refresh_cell_tree()
        self.update_summary()
        self.refresh_selection_panel()
        self.redraw()
        self.status_var.set(f"已将 OCR 框“{observation.text}”绑定到格子 {cell.short_name()}")

    def apply_selected_observation_to_remaining(self) -> None:
        observation = self._selected_observation()
        if observation is None:
            messagebox.showinfo("缺少选择", "请先选中一个 OCR 框。")
            return
        value = self.detector.parse_remaining_text(observation.text)
        if value is None:
            messagebox.showinfo("无法提取", "当前 OCR 框里没有可用的剩余蓝格数字。")
            return
        self.remaining_var.set(str(value))
        self.remaining_hint_var.set(f"已从 OCR 框“{observation.text}”提取 REMAINING = {value}")
        self.refresh_selection_panel()
        self.status_var.set(f"已将 OCR 框“{observation.text}”设为 REMAINING")

    def edit_current_selection(self) -> None:
        if self.selected_row_id is not None:
            self.edit_selected_row()
            return
        if self.selected_cell_coord is not None:
            self.edit_selected_cell()
            return
        messagebox.showinfo("没有可编辑对象", "请先选中一条行线索或一个格内线索。")

    def apply_high_confidence_row_ocr(self) -> None:
        if self.board is None:
            return
        applied = 0
        for row in self.board.row_clues:
            if row.clue_text or not row.ocr_text:
                continue
            if row.ocr_score is None or row.ocr_score > 75.0:
                continue
            parsed_text, parsed_type, parsed_number = self.detector.parse_clue_text(row.ocr_text)
            if not parsed_text:
                continue
            row.clue_text = parsed_text
            row.clue_type = parsed_type
            row.clue_number = parsed_number
            applied += 1
        self.refresh_row_tree()
        self.update_summary()
        self.refresh_selection_panel()
        self.redraw()
        self.status_var.set(f"已采用 {applied} 条高置信行 OCR")

    def apply_selected_row_ocr(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        if not row.ocr_text:
            messagebox.showinfo("没有 OCR", "这条行线索当前没有可采用的 OCR 候选。")
            return
        parsed_text, parsed_type, parsed_number = self.detector.parse_clue_text(row.ocr_text)
        if not parsed_text:
            messagebox.showinfo("OCR 不可用", "当前 OCR 结果无法直接转换成合法行线索。")
            return
        row.clue_text = parsed_text
        row.clue_type = parsed_type
        row.clue_number = parsed_number
        row.ocr_source = row.ocr_source or "采用 OCR"
        self.refresh_row_tree()
        self.update_summary()
        self.refresh_selection_panel()
        self.redraw()
        self.status_var.set(f"已采用 {row.line_id} 的 OCR 候选")

    def clear_selected_row(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        row.clue_text = ""
        row.clue_type = ClueType.NONE
        row.clue_number = None
        self.refresh_row_tree()
        self.update_summary()
        self.refresh_selection_panel()
        self.redraw()
        self.status_var.set(f"已清空 {row.line_id}")

    def edit_selected_row(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        text = simpledialog.askstring(
            "编辑行线索",
            f"请输入 {row.display_name()} 的线索：\n可用格式：3、{{2}}、-4-",
            initialvalue=row.clue_text or row.ocr_text,
            parent=self.root,
        )
        if text is None:
            return
        parsed_text, parsed_type, parsed_number = self.detector.parse_clue_text(text.strip())
        row.clue_text = parsed_text
        row.clue_type = parsed_type
        row.clue_number = parsed_number
        row.ocr_source = "手动编辑"
        self.refresh_row_tree()
        self.update_summary()
        self.refresh_selection_panel()
        self.redraw()
        self.status_var.set(f"已更新 {row.line_id}")

    def restore_selected_cell_ocr(self) -> None:
        cell = self._selected_cell()
        if cell is None:
            return
        parsed_text, parsed_type, parsed_number = self.detector.parse_clue_text(cell.ocr_text)
        cell.clue_text = parsed_text
        cell.clue_type = parsed_type
        cell.clue_number = parsed_number
        self.refresh_cell_tree()
        self.refresh_selection_panel()
        self.redraw()
        self.status_var.set(f"已将格子 {cell.short_name()} 恢复到 OCR 结果")

    def clear_selected_cell_clue(self) -> None:
        cell = self._selected_cell()
        if cell is None:
            return
        cell.clue_text = ""
        cell.clue_type = ClueType.NONE
        cell.clue_number = None
        self.refresh_cell_tree()
        self.refresh_selection_panel()
        self.redraw()
        self.status_var.set(f"已清空格子 {cell.short_name()} 的当前线索")

    def edit_selected_cell(self) -> None:
        cell = self._selected_cell()
        if cell is None:
            return
        text = simpledialog.askstring(
            "编辑格内线索",
            f"请输入格子 {cell.short_name()} 的线索：\n可用格式：3、{{2}}、-4-、?；留空表示普通已知格。",
            initialvalue=cell.clue_text or cell.ocr_text,
            parent=self.root,
        )
        if text is None:
            return
        parsed_text, parsed_type, parsed_number = self.detector.parse_clue_text(text.strip())
        cell.clue_text = parsed_text
        cell.clue_type = parsed_type
        cell.clue_number = parsed_number
        cell.ocr_source = "手动编辑"
        self.refresh_cell_tree()
        self.refresh_selection_panel()
        self.redraw()
        self.status_var.set(f"已更新格子 {cell.short_name()} 的线索")

    def refresh_all_lists(self) -> None:
        self.refresh_row_tree()
        self.refresh_cell_tree()
        self.refresh_observation_tree()
        self.refresh_selection_panel()

    def refresh_row_tree(self) -> None:
        current = self.selected_row_id
        self.row_tree.delete(*self.row_tree.get_children())
        if self.board is None:
            return

        for row in self.board.row_clues:
            if self.pending_only_var.get() and row.clue_text:
                continue

            if row.clue_text:
                status = "已确认"
                tag = "confirmed"
            elif row.ocr_text:
                status = "待确认"
                tag = "pending"
            else:
                status = "未识别"
                tag = "missing"

            score_text = f"{row.ocr_score:.1f}" if row.ocr_score is not None else ""
            self.row_tree.insert(
                "",
                tk.END,
                iid=row.line_id,
                values=(row.line_id, row.family_label(), len(row.coords), row.ocr_text, row.clue_text, score_text, row.ocr_source or "-", status),
                tags=(tag,),
            )

        if current and self.row_tree.exists(current):
            self.row_tree.selection_set(current)
            self.row_tree.see(current)

    def refresh_cell_tree(self) -> None:
        current = self.selected_cell_coord
        self.cell_tree.delete(*self.cell_tree.get_children())
        if self.board is None:
            return

        for cell in self.board.clue_cells():
            if cell.visual_type not in {CellVisualType.BLUE, CellVisualType.BLACK}:
                continue
            if not cell.ocr_text and not cell.clue_text:
                continue
            tag = "high" if cell.ocr_score is not None and cell.ocr_score <= 35.0 else "low"
            score_text = f"{cell.ocr_score:.1f}" if cell.ocr_score is not None else ""
            self.cell_tree.insert(
                "",
                tk.END,
                iid=f"cell-{cell.coord[0]}-{cell.coord[1]}",
                values=(
                    cell.short_name(),
                    "蓝格" if cell.visual_type == CellVisualType.BLUE else "黑格",
                    cell.ocr_text,
                    cell.clue_text,
                    score_text,
                    cell.ocr_source,
                ),
                tags=(tag,),
            )

        if current is not None:
            cell_id = f"cell-{current[0]}-{current[1]}"
            if self.cell_tree.exists(cell_id):
                self.cell_tree.selection_set(cell_id)
                self.cell_tree.see(cell_id)

    def refresh_observation_tree(self) -> None:
        current = self.selected_observation_index
        self.obs_tree.delete(*self.obs_tree.get_children())
        if self.board is None:
            return

        for index, observation in enumerate(self.board.ocr_observations):
            x0, y0, x1, y1 = observation.box
            box_text = f"({int(x0)}, {int(y0)})-({int(x1)}, {int(y1)})"
            tag = "low" if observation.score < 0.80 else ""
            self.obs_tree.insert(
                "",
                tk.END,
                iid=f"obs-{index}",
                values=(observation.text, f"{observation.score:.2f}", box_text),
                tags=(tag,),
            )

        if current is not None:
            obs_id = f"obs-{current}"
            if self.obs_tree.exists(obs_id):
                self.obs_tree.selection_set(obs_id)
                self.obs_tree.see(obs_id)

    def refresh_result_tree(self) -> None:
        self._clear_results()
        if not self.moves:
            self.result_text.insert("1.0", "当前没有找到必然可开或必黑的格子。")
            return
        for index, move in enumerate(self.moves):
            self.result_tree.insert(
                "",
                tk.END,
                iid=f"move-{index}",
                values=(
                    "可开（蓝）" if move.action == MoveAction.MARK_BLUE else "应标黑",
                    f"({move.coord[0]}, {move.coord[1]})",
                    move.source,
                ),
            )

    def update_summary(self) -> None:
        if self.board is None:
            self.summary_rows_var.set("行线索：0")
            self.summary_cells_var.set("格内线索：0")
            self.summary_ocr_var.set("OCR 框：0")
            self.summary_moves_var.set(f"解题建议：{len(self.moves)}")
            return

        confirmed_rows = sum(1 for row in self.board.row_clues if row.clue_text)
        pending_rows = sum(1 for row in self.board.row_clues if row.ocr_text and not row.clue_text)
        low_cells = sum(1 for cell in self.board.clue_cells() if cell.ocr_score is not None and cell.ocr_score > 35.0)
        self.summary_rows_var.set(f"已确认 {confirmed_rows} / 待确认 {pending_rows}")
        self.summary_cells_var.set(f"低置信 {low_cells} / 总数 {len(self.board.clue_cells())}")
        self.summary_ocr_var.set(f"{len(self.board.ocr_observations)} 个文本框")
        self.summary_moves_var.set(f"{len(self.moves)} 条建议")

    def refresh_selection_panel(self) -> None:
        title = "检查台待命中"
        meta = "点击棋盘、行线索、OCR 框或解题步骤，这里会显示上下文。"
        hint = "如果 OCR 和线索对不上，可以同时选中线索与 OCR 框，再一键绑定。"
        detail = (
            "建议操作：\n"
            "1. 先选中一条行线索或一个格内线索。\n"
            "2. 再选中右侧识别到的 OCR 框。\n"
            "3. 在上方按钮里一键应用到当前对象。"
        )
        preview_box: Optional[Tuple[int, int, int, int]] = None
        highlight_box: Optional[Tuple[float, float, float, float]] = None

        row = self._selected_row()
        cell = self._selected_cell()
        observation = self._selected_observation()
        move = self.moves[self.selected_move_index] if self.selected_move_index is not None and 0 <= self.selected_move_index < len(self.moves) else None

        if move is not None and self.board is not None:
            target = self.board.get_cell(move.coord)
            title = f"解题建议 #{self.selected_move_index + 1}"
            meta = f"{'可开（蓝）' if move.action == MoveAction.MARK_BLUE else '应标黑'} / 坐标 ({move.coord[0]}, {move.coord[1]}) / 来源 {move.source}"
            hint = "这条理由已经叠加到右侧截图中，点击列表可以在棋盘上跳转查看。"
            detail = move.reason
            if target is not None:
                preview_box = self._box_around_point(target.center, 170, 170)

        elif row is not None:
            title = f"行线索 {row.line_id}"
            meta = f"{row.family_label()} / 长度 {len(row.coords)} / 当前 {row.clue_text or '未确认'} / OCR {row.ocr_text or '未命中'}"
            hint = "如果同时选中了 OCR 框，点击“将所选 OCR 用于行”会直接完成绑定并写入当前线索。"
            if observation is not None:
                hint = f"已同时选中 OCR 框：{observation.text}。{hint}"
            detail = (
                f"来源：{row.ocr_source or '暂无'}\n"
                f"置信：{f'{row.ocr_score:.1f}' if row.ocr_score is not None else '未评分'}\n"
                f"坐标数：{len(row.coords)}\n"
                f"首尾格：{row.coords[0]} -> {row.coords[-1]}"
            )
            preview_box = tuple(int(v) for v in row.ocr_box) if row.ocr_box else self._box_around_point(row.anchor, 200, 120)
            highlight_box = row.ocr_box

        elif cell is not None:
            title = f"格内线索 {cell.short_name()}"
            meta = f"{'蓝格' if cell.visual_type == CellVisualType.BLUE else '黑格'} / 当前 {cell.clue_text or '未确认'} / OCR {cell.ocr_text or '未命中'}"
            hint = "如果同时选中了 OCR 框，点击“将所选 OCR 用于格”会直接覆盖当前格内线索。"
            if observation is not None:
                hint = f"已同时选中 OCR 框：{observation.text}。{hint}"
            detail = (
                f"来源：{cell.ocr_source or '暂无'}\n"
                f"置信：{f'{cell.ocr_score:.1f}' if cell.ocr_score is not None else '未评分'}\n"
                f"中心：({cell.center[0]:.1f}, {cell.center[1]:.1f})"
            )
            preview_box = tuple(int(v) for v in cell.ocr_box) if cell.ocr_box else self._box_around_point(cell.center, 120, 120)
            highlight_box = cell.ocr_box

        elif observation is not None:
            title = "原始 OCR 框"
            meta = f"文本：{observation.text} / 置信 {observation.score:.2f}"
            hint = "先去选中一条行线索或一个格内线索，再回来把这个 OCR 框一键绑定过去。"
            detail = f"框坐标：({int(observation.box[0])}, {int(observation.box[1])}) -> ({int(observation.box[2])}, {int(observation.box[3])})"
            preview_box = tuple(int(v) for v in observation.box)
            highlight_box = observation.box

        self.selection_title_var.set(title)
        self.selection_meta_var.set(meta)
        self.selection_hint_var.set(hint)
        self.selection_text.delete("1.0", tk.END)
        self.selection_text.insert("1.0", detail)
        self._update_preview_image(preview_box, highlight_box)

    def _update_preview_image(
        self,
        crop_box: Optional[Tuple[int, int, int, int]],
        highlight_box: Optional[Tuple[float, float, float, float]] = None,
    ) -> None:
        if self.current_image is None or crop_box is None:
            self.preview_photo = None
            self.preview_label.configure(image=None, text="选中对象后，这里会显示截图局部。")
            return

        left = max(0, crop_box[0])
        top = max(0, crop_box[1])
        right = min(self.current_image.width, crop_box[2])
        bottom = min(self.current_image.height, crop_box[3])
        if right <= left or bottom <= top:
            self.preview_photo = None
            self.preview_label.configure(image=None, text="当前对象的局部区域不可预览。")
            return

        preview = self.current_image.crop((left, top, right, bottom)).copy()
        if highlight_box is not None:
            draw = ImageDraw.Draw(preview)
            draw.rectangle(
                (
                    highlight_box[0] - left,
                    highlight_box[1] - top,
                    highlight_box[2] - left,
                    highlight_box[3] - top,
                ),
                outline="#ff4b85",
                width=4,
            )
        preview = ImageOps.contain(preview, (500, 180))
        self.preview_photo = ctk.CTkImage(light_image=preview, dark_image=preview, size=preview.size)
        self.preview_label.configure(image=self.preview_photo, text="")

    def _box_around_point(self, point: Tuple[float, float], width: int, height: int) -> Tuple[int, int, int, int]:
        cx = int(round(point[0]))
        cy = int(round(point[1]))
        return (cx - width // 2, cy - height // 2, cx + width // 2, cy + height // 2)

    def on_row_selected(self, _event: object) -> None:
        selection = self.row_tree.selection()
        if not selection:
            return
        self.selected_row_id = selection[0]
        row = self._selected_row()
        if row is not None:
            self.selected_cell_coord = None
            self.selected_move_index = None
            self.focus_on_image_point(row.anchor)
        self.refresh_selection_panel()
        self.redraw()

    def on_cell_selected(self, _event: object) -> None:
        selection = self.cell_tree.selection()
        if not selection:
            return
        parts = selection[0].split("-")
        self.selected_cell_coord = (int(parts[1]), int(parts[2]))
        self.selected_row_id = None
        self.selected_move_index = None
        cell = self._selected_cell()
        if cell is not None:
            self.focus_on_image_point(cell.center)
        self.refresh_selection_panel()
        self.redraw()

    def on_observation_selected(self, _event: object) -> None:
        selection = self.obs_tree.selection()
        if not selection:
            return
        self.selected_observation_index = int(selection[0].split("-")[1])
        observation = self._selected_observation()
        if observation is not None:
            self.focus_on_image_point(observation.center)
        self.refresh_selection_panel()
        self.redraw()

    def on_result_selected(self, _event: object) -> None:
        selection = self.result_tree.selection()
        if not selection:
            return
        self.selected_move_index = int(selection[0].split("-")[1])
        move = self.moves[self.selected_move_index]
        self.selected_row_id = None
        self.selected_cell_coord = move.coord
        self.selected_observation_index = None
        self.focus_on_image_point(self.board.get_cell(move.coord).center if self.board else (0.0, 0.0))
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert(
            "1.0",
            f"目标格子：({move.coord[0]}, {move.coord[1]})\n"
            f"建议动作：{'可开（蓝）' if move.action == MoveAction.MARK_BLUE else '应标黑'}\n"
            f"来源：{move.source}\n\n"
            f"理由：\n{move.reason}",
        )
        self.refresh_selection_panel()
        self.redraw()

    def on_canvas_click(self, event: tk.Event) -> None:
        cell = self._hit_cell(event.x, event.y)
        if cell is not None:
            self.select_cell(cell.coord)
            return

        row = self._hit_row(event.x, event.y)
        if row is not None:
            self.select_row(row.line_id)
            return

        observation = self._hit_observation(event.x, event.y)
        if observation is not None:
            self.select_observation(observation)

    def on_canvas_double_click(self, _event: tk.Event) -> None:
        if self.selected_cell_coord is not None:
            self.edit_selected_cell()
        elif self.selected_row_id is not None:
            self.edit_selected_row()

    def on_mousewheel(self, event: tk.Event) -> None:
        if self.current_image is None:
            return
        factor = 1.1 if event.delta > 0 else 0.9
        old_scale = self.fit_scale * self.zoom_factor
        new_zoom = min(max(self.zoom_factor * factor, 0.35), 5.0)
        self.zoom_factor = new_zoom
        new_scale = self.fit_scale * self.zoom_factor

        canvas_x = event.x
        canvas_y = event.y
        image_x = (canvas_x - self.pan_x) / max(old_scale, 1e-6)
        image_y = (canvas_y - self.pan_y) / max(old_scale, 1e-6)
        self.pan_x = canvas_x - image_x * new_scale
        self.pan_y = canvas_y - image_y * new_scale
        self.redraw()

    def on_pan_start(self, event: tk.Event) -> None:
        self.drag_origin = (event.x, event.y)

    def on_pan_move(self, event: tk.Event) -> None:
        if self.drag_origin is None:
            return
        dx = event.x - self.drag_origin[0]
        dy = event.y - self.drag_origin[1]
        self.pan_x += dx
        self.pan_y += dy
        self.drag_origin = (event.x, event.y)
        self.redraw()

    def on_pan_end(self, _event: tk.Event) -> None:
        self.drag_origin = None

    def reset_view(self) -> None:
        self.zoom_factor = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.redraw()

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.current_image is None:
            self._draw_placeholder("请先导入一张截图")
            return

        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        self.fit_scale = min((canvas_width - 40) / self.current_image.width, (canvas_height - 40) / self.current_image.height, 1.2)
        self.fit_scale = max(self.fit_scale, 0.1)
        self.render_scale = self.fit_scale * self.zoom_factor

        display_width = max(1, int(round(self.current_image.width * self.render_scale)))
        display_height = max(1, int(round(self.current_image.height * self.render_scale)))
        image = self.current_image.resize((display_width, display_height))

        base_x = (canvas_width - display_width) / 2 + self.pan_x
        base_y = (canvas_height - display_height) / 2 + self.pan_y
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.create_image(base_x, base_y, image=self.photo, anchor=tk.NW)

        self.canvas_cell_centers.clear()
        self.canvas_row_anchors.clear()
        self.canvas_observation_boxes.clear()

        if self.board is None:
            return

        radius = max(7, int(round(abs(self.board.basis_b[1]) * 0.72 * self.render_scale)))
        for cell in self.board.visible_cells():
            cx, cy = self._image_to_canvas(cell.center, base_x, base_y)
            self.canvas_cell_centers[cell.coord] = (cx, cy)
            if not self.show_cell_overlay_var.get():
                continue
            if cell.visual_type == CellVisualType.OUTSIDE:
                continue
            outline = {
                CellVisualType.HIDDEN: "#ffb54a",
                CellVisualType.BLUE: "#39b3ff",
                CellVisualType.BLACK: "#3d3942",
                CellVisualType.GREY: "#d1cbc1",
            }[cell.visual_type]
            width = 2 if cell.visual_type != CellVisualType.HIDDEN else 3
            self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=outline, width=width)
            if cell.clue_text:
                text_color = "#ffffff" if cell.visual_type == CellVisualType.BLACK else "#191919"
                self.canvas.create_text(cx, cy, text=cell.clue_text, fill=text_color, font=("Consolas", max(9, int(radius * 0.85)), "bold"))

        if self.show_line_var.get():
            for row in self.board.row_clues:
                ax, ay = self._image_to_canvas(row.anchor, base_x, base_y)
                self.canvas_row_anchors[row.line_id] = (ax, ay)
                self.canvas.create_text(ax, ay, text=row.line_id, fill="#ff8660", font=("Consolas", 10, "bold"))
                if row.ocr_text:
                    self.canvas.create_text(ax, ay + 16, text=row.ocr_text, fill="#ffd795" if not row.clue_text else "#7dd091", font=("Consolas", 10))
        else:
            for row in self.board.row_clues:
                self.canvas_row_anchors[row.line_id] = self._image_to_canvas(row.anchor, base_x, base_y)

        if self.show_ocr_box_var.get():
            for index, observation in enumerate(self.board.ocr_observations):
                x0, y0 = self._image_to_canvas((observation.box[0], observation.box[1]), base_x, base_y)
                x1, y1 = self._image_to_canvas((observation.box[2], observation.box[3]), base_x, base_y)
                self.canvas_observation_boxes[index] = (x0, y0, x1, y1)
                color = "#50d6ae" if observation.score >= 0.90 else "#ffce62"
                self.canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=2)
                self.canvas.create_text(x0 + 4, y0 - 10, text=observation.text, anchor=tk.W, fill=color, font=("Consolas", 9, "bold"))
        else:
            for index, observation in enumerate(self.board.ocr_observations):
                x0, y0 = self._image_to_canvas((observation.box[0], observation.box[1]), base_x, base_y)
                x1, y1 = self._image_to_canvas((observation.box[2], observation.box[3]), base_x, base_y)
                self.canvas_observation_boxes[index] = (x0, y0, x1, y1)

        if self.selected_row_id:
            self._draw_selected_row(radius)
        if self.selected_cell_coord is not None:
            self._draw_selected_cell(radius)
        if self.selected_observation_index is not None:
            self._draw_selected_observation()
        if self.show_solution_var.get():
            self._draw_solution_overlay(radius)

    def _draw_selected_row(self, radius: int) -> None:
        if self.board is None or self.selected_row_id is None:
            return
        row = next((item for item in self.board.row_clues if item.line_id == self.selected_row_id), None)
        if row is None:
            return
        points: List[float] = []
        for coord in row.coords:
            center = self.canvas_cell_centers.get(coord)
            if center is None:
                continue
            x, y = center
            points.extend([x, y])
            self.canvas.create_oval(x - radius - 5, y - radius - 5, x + radius + 5, y + radius + 5, outline="#ffd35c", width=2)
        if len(points) >= 4:
            self.canvas.create_line(*points, fill="#ffd35c", width=3, smooth=True)

    def _draw_selected_cell(self, radius: int) -> None:
        center = self.canvas_cell_centers.get(self.selected_cell_coord)
        if center is None:
            return
        x, y = center
        self.canvas.create_oval(x - radius - 10, y - radius - 10, x + radius + 10, y + radius + 10, outline="#ff4b85", width=3)

    def _draw_selected_observation(self) -> None:
        box = self.canvas_observation_boxes.get(self.selected_observation_index)
        if box is None:
            return
        x0, y0, x1, y1 = box
        self.canvas.create_rectangle(x0 - 4, y0 - 4, x1 + 4, y1 + 4, outline="#ff4b85", width=3)

    def _draw_solution_overlay(self, radius: int) -> None:
        if not self.moves:
            return
        blue_count = 0
        black_count = 0
        for index, move in enumerate(self.moves, start=1):
            center = self.canvas_cell_centers.get(move.coord)
            if center is None:
                continue
            x, y = center
            if move.action == MoveAction.MARK_BLUE:
                color = "#2fe6c1"
                label = "开"
                blue_count += 1
            else:
                color = "#ff726b"
                label = "黑"
                black_count += 1
            self.canvas.create_oval(x - radius - 9, y - radius - 9, x + radius + 9, y + radius + 9, outline=color, width=3)
            self.canvas.create_text(x, y, text=label, fill=color, font=("Microsoft YaHei UI", max(10, int(radius * 0.8)), "bold"))
            self.canvas.create_text(x, y - radius - 18, text=str(index), fill=color, font=("Consolas", 10, "bold"))

        legend = f"解题叠图：可开（蓝） {blue_count} / 应标黑 {black_count}"
        self.canvas.create_rectangle(20, 18, 350, 50, fill="#0f141a", outline="")
        self.canvas.create_text(34, 34, anchor=tk.W, text=legend, fill="#f5f1ea", font=("Microsoft YaHei UI", 10, "bold"))

    def _draw_placeholder(self, text: str) -> None:
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        self.canvas.create_text(width / 2, height / 2, text=text, fill="#8b97a6", font=("Microsoft YaHei UI", 18, "bold"))

    def _image_to_canvas(self, point: Tuple[float, float], base_x: float, base_y: float) -> Tuple[float, float]:
        return point[0] * self.render_scale + base_x, point[1] * self.render_scale + base_y

    def focus_on_image_point(self, point: Tuple[float, float]) -> None:
        if self.current_image is None:
            return
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        self.pan_x = canvas_width / 2 - point[0] * self.render_scale - (canvas_width - self.current_image.width * self.render_scale) / 2
        self.pan_y = canvas_height / 2 - point[1] * self.render_scale - (canvas_height - self.current_image.height * self.render_scale) / 2
        self.redraw()

    def _hit_cell(self, x: int, y: int) -> Optional[Cell]:
        if self.board is None:
            return None
        best: Optional[Cell] = None
        best_dist = float("inf")
        for coord, (cx, cy) in self.canvas_cell_centers.items():
            dist = (cx - x) ** 2 + (cy - y) ** 2
            if dist < best_dist:
                best = self.board.get_cell(coord)
                best_dist = dist
        if best is None or best_dist > 28 * 28:
            return None
        return best

    def _hit_row(self, x: int, y: int) -> Optional[RowClue]:
        if self.board is None:
            return None
        best_id = None
        best_dist = float("inf")
        for row_id, (ax, ay) in self.canvas_row_anchors.items():
            dist = (ax - x) ** 2 + (ay - y) ** 2
            if dist < best_dist:
                best_dist = dist
                best_id = row_id
        if best_id is None or best_dist > 18 * 18:
            return None
        return next((row for row in self.board.row_clues if row.line_id == best_id), None)

    def _hit_observation(self, x: int, y: int) -> Optional[int]:
        for index, (x0, y0, x1, y1) in self.canvas_observation_boxes.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                return index
        return None

    def select_row(self, row_id: str) -> None:
        self.selected_row_id = row_id
        self.selected_cell_coord = None
        self.selected_move_index = None
        if self.row_tree.exists(row_id):
            self.row_tree.selection_set(row_id)
            self.row_tree.see(row_id)
        row = self._selected_row()
        if row is not None:
            self.focus_on_image_point(row.anchor)
        self.refresh_selection_panel()
        self.redraw()

    def select_cell(self, coord: Coord) -> None:
        self.selected_cell_coord = coord
        self.selected_row_id = None
        self.selected_move_index = None
        item_id = f"cell-{coord[0]}-{coord[1]}"
        if self.cell_tree.exists(item_id):
            self.cell_tree.selection_set(item_id)
            self.cell_tree.see(item_id)
        cell = self._selected_cell()
        if cell is not None:
            self.focus_on_image_point(cell.center)
        self.refresh_selection_panel()
        self.redraw()

    def select_observation(self, index: int) -> None:
        self.selected_observation_index = index
        item_id = f"obs-{index}"
        if self.obs_tree.exists(item_id):
            self.obs_tree.selection_set(item_id)
            self.obs_tree.see(item_id)
        observation = self._selected_observation()
        if observation is not None:
            self.focus_on_image_point(observation.center)
        self.refresh_selection_panel()
        self.redraw()

    def _selected_row(self) -> Optional[RowClue]:
        if self.board is None or not self.selected_row_id:
            return None
        return next((row for row in self.board.row_clues if row.line_id == self.selected_row_id), None)

    def _selected_cell(self) -> Optional[Cell]:
        if self.board is None or self.selected_cell_coord is None:
            return None
        return self.board.get_cell(self.selected_cell_coord)

    def _selected_observation(self) -> Optional[OCRObservation]:
        if self.board is None or self.selected_observation_index is None:
            return None
        if 0 <= self.selected_observation_index < len(self.board.ocr_observations):
            return self.board.ocr_observations[self.selected_observation_index]
        return None

    def _set_log(self, text: str) -> None:
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert("1.0", text)

    def _append_log(self, text: str) -> None:
        existing = self.log_text.get("1.0", tk.END).strip()
        self._set_log(text if not existing else f"{existing}\n\n{text}")

    def _clear_results(self) -> None:
        self.result_tree.delete(*self.result_tree.get_children())
        self.result_text.delete("1.0", tk.END)

    def mainloop(self) -> None:
        self.root.mainloop()


def run_app() -> None:
    root = ctk.CTk()
    app = MainWindow(root)
    app.mainloop()
