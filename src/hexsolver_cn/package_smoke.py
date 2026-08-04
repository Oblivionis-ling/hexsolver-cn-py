from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from .app import MainWindow, SCREENSHOT_IMPORT_ENABLED
from .models import CellVisualType, MoveAction
from .original_bridge import build_default_seed_registry
from .seed_workflow import Difficulty, SeedRequest
from .theme import app_stylesheet


def _write_progress(message: str) -> None:
    log_path = os.environ.get("HEXSOLVER_PACKAGE_SMOKE_LOG")
    if not log_path:
        return
    with Path(log_path).open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def _verify_packaged_resources() -> None:
    if not getattr(sys, "frozen", False):
        return
    bundle_root = Path(sys._MEIPASS)
    required = (
        bundle_root / "managed_core" / "bin" / "HexcellsHeadless.exe",
        bundle_root / "managed_core" / "bin" / "UnityEngine.dll",
        bundle_root / "managed_core" / "bin" / "TextMeshPro-5.6-Runtime.dll",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("打包资源缺失：" + "；".join(missing))


def _verify_first_move(puzzle, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    move = window.solver.next_step(puzzle.public_board)
    if move is None:
        raise RuntimeError(f"{puzzle.request.difficulty.label} seed 1 没有返回第一步。")
    expected = CellVisualType.BLUE if move.action is MoveAction.MARK_BLUE else CellVisualType.BLACK
    if puzzle.private_answer[move.coord] is not expected:
        raise RuntimeError(
            f"{puzzle.request.difficulty.label} seed 1 第一条建议与私有答案不一致。"
        )


def run_package_smoke_test() -> int:
    """Create the real UI and exercise both packaged generators, then exit."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _write_progress("start")
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("HexInfinite 种子求解器")
    app.setOrganizationName("HexInfinite Solver")
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())
    window: MainWindow | None = None
    try:
        _verify_packaged_resources()
        _write_progress("resources-ok")
        registry = build_default_seed_registry()
        _write_progress("registry-ok")
        window = MainWindow(seed_generators=registry)
        _write_progress("window-created")
        window.show()
        app.processEvents()
        _write_progress("window-shown")

        if window.windowTitle() != "HexInfinite 种子求解器":
            raise RuntimeError("打包窗口标题与源码版不一致。")
        if window.minimumSize() != QSize(1120, 760) or window.size() != QSize(1440, 1024):
            raise RuntimeError("打包窗口尺寸与源码版不一致。")
        if window.sidebar.width() != 300:
            raise RuntimeError("打包侧栏宽度与源码版不一致。")
        if SCREENSHOT_IMPORT_ENABLED or window.stage.import_button.isEnabled():
            raise RuntimeError("打包版意外启用了尚未开放的截图入口。")

        for difficulty in (Difficulty.EASY, Difficulty.HARD):
            _write_progress(f"{difficulty.value}-generate-start")
            puzzle = registry.generate(SeedRequest(seed=1, difficulty=difficulty))
            _write_progress(f"{difficulty.value}-generate-ok")
            _verify_first_move(puzzle, window)
            _write_progress(f"{difficulty.value}-first-move-ok")

        _write_progress("success")
        print("[OK] PACKAGE_SMOKE_TEST UI + Easy/Hard seed 1")
        return 0
    except Exception:
        _write_progress("failure")
        log_path = os.environ.get("HEXSOLVER_PACKAGE_SMOKE_LOG")
        if log_path:
            with Path(log_path).open("a", encoding="utf-8") as stream:
                traceback.print_exc(file=stream)
        traceback.print_exc()
        return 1
    finally:
        if window is not None:
            window.close()
        app.processEvents()
