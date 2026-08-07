from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPalette, QTextCursor
from PySide6.QtWidgets import QApplication

from .app import (
    MainWindow,
    SCREENSHOT_IMPORT_ENABLED,
    STEP_REASON_BOTTOM_SAFE_MARGIN,
    show_window_for_startup,
)
from .models import CellVisualType, MoveAction, SuggestedMove
from .original_bridge import build_default_seed_registry
from .preferences import AppPreferences, StartupWindowMode
from .reason_interaction import ReasonReferenceKind
from .seed_workflow import Difficulty, SeedRequest
from .settings_dialog import SettingsDialog
from .session import InteractivePuzzleSession
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


def _verify_reason_bottom_safe_area(window: MainWindow, app: QApplication) -> None:
    reason = "推理过程：\n" + "\n".join(
        f"{index}. 这是第 {index} 条可核查条件与计算说明。" for index in range(1, 81)
    )
    window._update_step_card(
        SuggestedMove(
            coord=(0, 0),
            action=MoveAction.MARK_BLUE,
            reason=reason,
            source="成品显示验证",
        )
    )
    app.processEvents()
    scroll_bar = window.step_reason.verticalScrollBar()
    scroll_bar.setValue(scroll_bar.maximum())
    app.processEvents()
    cursor = QTextCursor(window.step_reason.document())
    cursor.movePosition(QTextCursor.MoveOperation.End)
    end_rect = window.step_reason.cursorRect(cursor)
    visible_bottom = window.step_reason.viewport().rect().bottom()
    if end_rect.bottom() > visible_bottom - 16:
        raise RuntimeError("打包界面的推理末行仍被底部操作栏截断。")
    if (
        window.step_reason.document().rootFrame().frameFormat().bottomMargin()
        < STEP_REASON_BOTTOM_SAFE_MARGIN
    ):
        raise RuntimeError("打包界面缺少推理正文末尾安全区。")


def _verify_manual_outline_colors(window: MainWindow, app: QApplication) -> None:
    expected = {
        CellVisualType.HIDDEN: "#3D3F42",
        CellVisualType.BLUE: "#FFA814",
        CellVisualType.BLACK: "#0DA9E5",
    }
    for state, expected_color in expected.items():
        button = window.state_buttons[state]
        button.click()
        app.processEvents()
        color = QColor(expected_color)
        if window.selected_state is not state or button.outline_color() != color:
            raise RuntimeError(f"手动标记 {state.value} 的选中轮廓颜色不正确。")
        image = button.grab().toImage()
        rendered_outline_pixels = sum(
            image.pixelColor(x, y).rgb() == color.rgb()
            for x in range(image.width())
            for y in range(image.height())
        )
        if rendered_outline_pixels <= 30:
            raise RuntimeError(f"手动标记 {state.value} 没有实际绘制选中轮廓。")
    window.state_buttons[CellVisualType.HIDDEN].click()
    app.processEvents()


def _verify_startup_mode_dropdown(settings: SettingsDialog, app: QApplication) -> None:
    combo = settings.startup_mode_combo
    popup = combo.view()
    if popup.isVisible() or combo.count() != len(StartupWindowMode):
        raise RuntimeError("启动窗口选择器没有保持折叠下拉状态。")
    if (
        popup.palette().color(QPalette.ColorRole.Base) != QColor("#FFFFFF")
        or popup.palette().color(QPalette.ColorRole.Text) != QColor("#3C3E40")
    ):
        raise RuntimeError("启动窗口下拉菜单没有使用白底深色文字。")

    combo.showPopup()
    app.processEvents()
    if not popup.isVisible():
        raise RuntimeError("启动窗口下拉菜单无法展开。")
    image = popup.viewport().grab().toImage()
    light_pixels = 0
    dark_surface_pixels = 0
    selected_pixels = 0
    for x in range(image.width()):
        for y in range(image.height()):
            color = image.pixelColor(x, y)
            if color.red() >= 220 and color.green() >= 220 and color.blue() >= 220:
                light_pixels += 1
            if color.red() <= 70 and color.green() <= 70 and color.blue() <= 70:
                dark_surface_pixels += 1
            if (
                abs(color.red() - 221) <= 3
                and abs(color.green() - 244) <= 3
                and abs(color.blue() - 252) <= 3
            ):
                selected_pixels += 1
    pixel_count = image.width() * image.height()
    if (
        light_pixels <= pixel_count * 0.65
        or dark_surface_pixels >= pixel_count * 0.12
        or selected_pixels <= pixel_count * 0.20
    ):
        raise RuntimeError("启动窗口下拉菜单未正确渲染白底、浅蓝选中态，或仍存在深色大块。")
    combo.hidePopup()
    app.processEvents()
    if popup.isVisible():
        raise RuntimeError("启动窗口下拉菜单选择后没有恢复折叠状态。")


def _verify_reason_interactions(window: MainWindow, app: QApplication) -> None:
    row = window.session.board.row_clues[0]
    coords = tuple(row.coords[: min(6, len(row.coords))])
    coords_text = "[" + "、".join(f"({q}, {r})" for q, r in coords) + "]"
    reason = (
        "推理过程：\n"
        f"1. 条件：{row.display_name()} 的提示 {row.clue_text}。\n"
        f"2. 未知集合 A = {coords_text}。"
    )
    window._set_step_reason(reason)
    app.processEvents()
    if window.step_reason.toPlainText() != reason:
        raise RuntimeError("交互推理文本改变了原始解释内容。")
    row_reference = next(
        (reference for reference in window.step_reason.references if reference.row_key),
        None,
    )
    group_reference = next(
        (
            reference
            for reference in window.step_reason.references
            if reference.kind is ReasonReferenceKind.CELLS and len(reference.coords) > 1
        ),
        None,
    )
    if row_reference is None or group_reference is None:
        raise RuntimeError("打包界面没有生成行线索和坐标组富文本引用。")

    cursor = QTextCursor(window.step_reason.document())
    cursor.setPosition(group_reference.start + 1)
    if not cursor.charFormat().isAnchor():
        raise RuntimeError("打包界面的坐标组没有渲染为可交互引用。")
    if cursor.charFormat().toolTip():
        raise RuntimeError("推理引用仍会请求悬停提示框。")

    window.step_reason.reference_focus_changed.emit(row_reference, False)
    app.processEvents()
    board_view = window.stage.board_view
    if (
        board_view.reason_highlighted_row != row_reference.row_key
        or set(board_view.reason_highlighted_coords) != set(row_reference.coords)
        or any(
            not board_view._reason_halo_items[coord].isVisible()
            or board_view._reason_overlay_items[coord].pen().style()
            is not Qt.PenStyle.CustomDashLine
            for coord in row_reference.coords
        )
    ):
        raise RuntimeError("行线索引用没有同步显示分层预览高亮。")

    window.step_reason._toggle_reference(group_reference)
    window.step_reason.reference_focus_changed.emit(group_reference, True)
    app.processEvents()
    cursor.setPosition(group_reference.start + 1)
    if (
        not board_view.reason_highlight_is_pinned
        or set(board_view.reason_highlighted_coords) != set(group_reference.coords)
        or cursor.charFormat().fontWeight() < QFont.Weight.Bold
        or any(
            not board_view._reason_halo_items[coord].isVisible()
            or board_view._reason_overlay_items[coord].pen().style()
            is not Qt.PenStyle.SolidLine
            for coord in group_reference.coords
        )
    ):
        raise RuntimeError("坐标组引用没有固定分层高亮并加粗文字。")

    window._update_step_card(None)
    app.processEvents()
    if window.step_reason.pinned_reference is not None or board_view.reason_highlighted_coords:
        raise RuntimeError("切换推理原因后没有清理固定高亮。")


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
        preferences = AppPreferences(persistent=False)
        window = MainWindow(seed_generators=registry, preferences=preferences)
        _write_progress("window-created")
        if window.minimumSize() != QSize(1120, 760) or window.size() != QSize(1440, 1024):
            raise RuntimeError("打包窗口初始尺寸与源码版不一致。")
        if preferences.startup_window_mode is not StartupWindowMode.MAXIMIZED:
            raise RuntimeError("打包版没有默认使用有窗口最大化启动模式。")
        show_window_for_startup(window, preferences.startup_window_mode)
        app.processEvents()
        _write_progress("window-shown")

        if window.windowTitle() != "HexInfinite 种子求解器":
            raise RuntimeError("打包窗口标题与源码版不一致。")
        if not window.isMaximized():
            raise RuntimeError("打包版没有按默认设置最大化窗口。")
        if window.session.board.cells or not window._guide_visible:
            raise RuntimeError("打包版启动时仍显示模拟盘面，或没有显示使用说明。")
        if (
            not window.onboarding_overlay.isVisible()
            or len(window.onboarding_overlay.notes) != 4
            or not window.guide_close_button.isVisible()
        ):
            raise RuntimeError("打包版缺少四步手绘使用说明或关闭入口。")
        if window.apply_button.toolTip() or not window.apply_button.accessibleName():
            raise RuntimeError("应用建议按钮仍显示悬停弹窗，或缺少无障碍名称。")
        window.showNormal()
        window.resize(1440, 1024)
        app.processEvents()
        if window.sidebar.width() != 300:
            raise RuntimeError("打包侧栏宽度与源码版不一致。")
        if any(
            hasattr(window, name)
            for name in ("history", "history_list", "remaining_value", "error_value")
        ):
            raise RuntimeError("打包界面仍然包含已移除的次要面板。")
        if window.step_reason.height() < 560:
            raise RuntimeError("打包界面的推理原因区域没有获得预期高度。")
        if window.step_reason.geometry().bottom() >= window.step_action_bar.geometry().top():
            raise RuntimeError("打包界面的推理正文进入了底部按钮区域。")
        _verify_reason_bottom_safe_area(window, app)
        if any(button.size() != QSize(60, 56) for button in window.state_buttons.values()):
            raise RuntimeError("打包界面的手动标记图例没有缩小。")
        if SCREENSHOT_IMPORT_ENABLED or window.stage.import_button.isEnabled():
            raise RuntimeError("打包版意外启用了尚未开放的截图入口。")
        if (
            not window.stage.settings_button.isEnabled()
            or not window.stage.settings_button.accessibleName()
        ):
            raise RuntimeError("打包界面缺少可访问的设置入口。")
        settings = SettingsDialog(registry.cache, preferences, window)
        settings.show()
        app.processEvents()
        if registry.cache is None or settings.cache_path_value.text() != str(
            registry.cache.directory
        ):
            raise RuntimeError("设置页没有显示实际种子缓存位置。")
        if (
            settings.startup_mode_combo.currentData()
            != StartupWindowMode.MAXIMIZED.value
        ):
            raise RuntimeError("设置页没有显示默认的有窗口最大化启动模式。")
        _verify_startup_mode_dropdown(settings, app)
        fullscreen_index = settings.startup_mode_combo.findData(
            StartupWindowMode.FULLSCREEN.value
        )
        settings.startup_mode_combo.setCurrentIndex(fullscreen_index)
        app.processEvents()
        if preferences.startup_window_mode is not StartupWindowMode.FULLSCREEN:
            raise RuntimeError("设置页没有保存无边框全屏启动模式。")
        maximized_index = settings.startup_mode_combo.findData(
            StartupWindowMode.MAXIMIZED.value
        )
        settings.startup_mode_combo.setCurrentIndex(maximized_index)
        if not settings.show_guide_button.accessibleName():
            raise RuntimeError("设置页缺少重新查看使用说明的可访问入口。")
        settings.show_guide_button.click()
        if not settings.guide_requested:
            raise RuntimeError("设置页没有发出重新查看使用说明的请求。")
        window.show_onboarding()
        app.processEvents()
        if not window._guide_visible or window.next_button.isEnabled():
            raise RuntimeError("重新打开使用说明时没有暂停棋盘操作。")
        settings.close()

        preview = registry.generate(SeedRequest(seed=1, difficulty=Difficulty.HARD))
        window.current_seed = preview.request
        window.session = InteractivePuzzleSession(
            preview.public_board,
            window.solver,
            private_reveals=preview.private_reveals,
        )
        window._load_board(
            window.session.board,
            mode_text="种子 00000001 · 困难 · 成品验证",
            verified=True,
        )
        app.processEvents()
        if window._guide_visible or not window.next_button.isEnabled():
            raise RuntimeError("生成真实种子盘面后使用说明没有自动收起。")
        _verify_manual_outline_colors(window, app)
        row_items = window.stage.board_view.row_clue_items
        if len(row_items) != len(window.session.board.row_clues) or not all(
            item.isVisible() and item.zValue() > 4 for item in row_items
        ):
            raise RuntimeError("打包界面没有保持所有行线索可见。")
        _verify_reason_interactions(window, app)

        settings = SettingsDialog(registry.cache, preferences, window)
        if settings.original_mouse_controls_toggle.isChecked():
            raise RuntimeError("原版鼠标操作没有保持兼容性的默认关闭状态。")
        settings.original_mouse_controls_toggle.click()
        app.processEvents()
        window._apply_mouse_control_preference()
        if not preferences.original_mouse_controls_enabled or any(
            button.isEnabled() for button in window.state_buttons.values()
        ):
            raise RuntimeError("设置页没有启用原版左右键棋盘操作。")
        mouse_coords = [cell.coord for cell in window.session.board.hidden_cells()][:2]
        window._on_cell_activated(mouse_coords[0], Qt.MouseButton.LeftButton)
        window._on_cell_activated(mouse_coords[1], Qt.MouseButton.RightButton)
        if (
            window.session.board.get_cell(mouse_coords[0]).visual_type is not CellVisualType.BLACK
            or window.session.board.get_cell(mouse_coords[1]).visual_type is not CellVisualType.BLUE
        ):
            raise RuntimeError("原版鼠标操作没有正确映射左键排除和右键蓝色。")
        window._on_cell_activated(mouse_coords[1], Qt.MouseButton.RightButton)
        if window.session.board.get_cell(mouse_coords[1]).visual_type is not CellVisualType.HIDDEN:
            raise RuntimeError("原版鼠标操作无法通过同键再次点击恢复未知。")
        settings.original_mouse_controls_toggle.click()
        window._apply_mouse_control_preference()
        if not all(button.isEnabled() for button in window.state_buttons.values()):
            raise RuntimeError("关闭原版鼠标操作后没有恢复手动工具。")
        settings.close()

        for difficulty in (Difficulty.EASY, Difficulty.HARD):
            _write_progress(f"{difficulty.value}-generate-start")
            puzzle = registry.generate(SeedRequest(seed=1, difficulty=difficulty))
            _write_progress(f"{difficulty.value}-generate-ok")
            _verify_first_move(puzzle, window)
            _write_progress(f"{difficulty.value}-first-move-ok")
            cached = registry.generate(SeedRequest(seed=1, difficulty=difficulty))
            if not cached.cache_hit:
                raise RuntimeError(f"{difficulty.label} seed 1 第二次生成没有命中本地缓存。")
            _write_progress(f"{difficulty.value}-cache-hit-ok")

        if registry.cache is None or registry.cache.stats().entry_count < 2:
            raise RuntimeError("成品没有保存 Easy/Hard 种子结果缓存。")

        _write_progress("success")
        print("[OK] PACKAGE_SMOKE_TEST UI + mouse settings + Easy/Hard seed 1 cache")
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
