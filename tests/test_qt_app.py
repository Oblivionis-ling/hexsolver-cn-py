from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPalette, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hexsolver_cn.app import (  # noqa: E402
    MainWindow,
    STEP_REASON_BOTTOM_SAFE_MARGIN,
    show_window_for_startup,
)
from hexsolver_cn.board_view import HexBoardView  # noqa: E402
from hexsolver_cn.demo_board import build_demo_board  # noqa: E402
from hexsolver_cn.dialogs import LightConfirmDialog  # noqa: E402
from hexsolver_cn.models import (  # noqa: E402
    CellReveal,
    CellVisualType,
    ClueType,
    MoveAction,
    SuggestedMove,
)
from hexsolver_cn.original_bridge import (  # noqa: E402
    OriginalRuntimeHardBackend,
)
from hexsolver_cn.preferences import AppPreferences, StartupWindowMode  # noqa: E402
from hexsolver_cn.reason_interaction import (  # noqa: E402
    ReasonReferenceKind,
    parse_reason_references,
)
from hexsolver_cn.seed_cache import SeedResultCache  # noqa: E402
from hexsolver_cn.seed_workflow import Difficulty, SeedGeneratorRegistry, SeedRequest  # noqa: E402
from hexsolver_cn.settings_dialog import SettingsDialog  # noqa: E402
from hexsolver_cn.session import InteractivePuzzleSession  # noqa: E402
from hexsolver_cn.session_store import SessionStore  # noqa: E402


class FixtureRunner:
    def __init__(self, text: str) -> None:
        self.text = text

    def generate_tsv(self, seed: int, difficulty: Difficulty = Difficulty.HARD) -> str:
        return self.text


class QtAppWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.preferences_directory = tempfile.TemporaryDirectory()
        self.preferences_path = Path(self.preferences_directory.name) / "settings.ini"
        self.preferences = AppPreferences(
            QSettings(str(self.preferences_path), QSettings.Format.IniFormat)
        )
        self.window = MainWindow(
            seed_generators=SeedGeneratorRegistry(),
            preferences=self.preferences,
            session_store=SessionStore(self.preferences_directory.name),
        )
        self.window.session = InteractivePuzzleSession(
            build_demo_board(),
            self.window.solver,
        )
        self.window._load_board(
            self.window.session.board,
            mode_text="测试盘面",
            verified=True,
        )

    def tearDown(self) -> None:
        self.window.close()
        self.preferences_directory.cleanup()

    def _activate_reason_reference(self, reference) -> None:  # type: ignore[no-untyped-def]
        # Keyboard activation and mouse release share the same toggle path. The
        # keyboard route is deterministic with Qt's offscreen font renderer and
        # also verifies the required non-hover accessibility fallback.
        cursor = QTextCursor(self.window.step_reason.document())
        cursor.setPosition(reference.start + 1)
        self.window.step_reason.setTextCursor(cursor)
        QTest.keyClick(self.window.step_reason, Qt.Key.Key_Return)
        self.app.processEvents()

    def _click_reason_reference(self, reference) -> None:  # type: ignore[no-untyped-def]
        # Qt's offscreen plugin does not always shape Chinese glyph positions
        # before the first paint. Stub only hit-testing while keeping the real
        # viewport press/release dispatch and browser mouse handlers intact.
        with patch.object(
            self.window.step_reason,
            "_reference_at",
            return_value=reference,
        ):
            QTest.mouseClick(
                self.window.step_reason.viewport(),
                Qt.MouseButton.LeftButton,
            )
        self.app.processEvents()

    def _wait_for_simulation_check(self, timeout: float = 6.0) -> None:
        deadline = time.monotonic() + timeout
        stable_idle_cycles = 0
        while time.monotonic() < deadline:
            self.app.processEvents()
            if (
                self.window._simulation_conflict_thread is None
                and not self.window._simulation_check_pending
            ):
                stable_idle_cycles += 1
                if stable_idle_cycles >= 2:
                    break
            else:
                stable_idle_cycles = 0
            time.sleep(0.01)
        self.app.processEvents()
        self.assertIsNone(self.window._simulation_conflict_thread)

    def test_demo_board_can_suggest_and_apply_one_forced_move(self) -> None:
        self.assertEqual("", self.window.apply_button.toolTip())
        self.assertEqual("应用当前建议", self.window.apply_button.accessibleName())
        self.window.solve_next_step()
        deadline = time.monotonic() + 3.0
        while self.window._solve_thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        move = self.window.current_move
        self.assertIsNotNone(move)
        assert move is not None
        before = self.window.session.board.get_cell(move.coord).visual_type
        self.assertIs(before, CellVisualType.HIDDEN)

        self.window.apply_current_move()

        after = self.window.session.board.get_cell(move.coord).visual_type
        self.assertIn(after, {CellVisualType.BLUE, CellVisualType.BLACK})
        self.assertIsNone(self.window.current_move)
        self.assertEqual(move.coord, self.window.session.history[-1].coord)

    def test_solve_runs_off_ui_thread_and_ignores_stale_result(self) -> None:
        started = threading.Event()
        release = threading.Event()
        stale_move = SuggestedMove(
            (1, 0),
            MoveAction.MARK_BLUE,
            "过期结果",
            "局部必然",
        )

        def delayed_next_step(_solver, _board):  # type: ignore[no-untyped-def]
            started.set()
            release.wait(2.0)
            return stale_move

        with patch(
            "hexsolver_cn.app.HexReasoningSolver.next_step",
            autospec=True,
            side_effect=delayed_next_step,
        ):
            self.window.solve_next_step()
            deadline = time.monotonic() + 2.0
            while not started.is_set() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertTrue(started.is_set())
            self.assertTrue(self.window._solve_busy)
            self.assertEqual("正在推理…", self.window.next_button.text())

            self.window._select_state(CellVisualType.BLACK)
            self.window._on_cell_activated((1, 0))
            release.set()
            deadline = time.monotonic() + 3.0
            while self.window._solve_thread is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)

        self.assertIsNone(self.window._solve_thread)
        self.assertIsNone(self.window.current_move)
        self.assertFalse(self.window._solve_busy)

    def test_redo_button_and_shortcut_restore_undone_mark(self) -> None:
        coord = next(cell.coord for cell in self.window.session.board.hidden_cells())
        self.window._select_state(CellVisualType.BLACK)
        self.window._on_cell_activated(coord)
        changed = self.window.session.board.get_cell(coord).visual_type
        self.window.undo()
        self.assertIs(CellVisualType.HIDDEN, self.window.session.board.get_cell(coord).visual_type)

        self.window.redo_action.trigger()
        self.assertIs(changed, self.window.session.board.get_cell(coord).visual_type)
        self.assertEqual("重做", self.window.stage.redo_button.accessibleName())

    def test_autosave_restores_session_when_user_accepts(self) -> None:
        self.window.current_seed = SeedRequest(17, Difficulty.HARD)
        self.window._select_state(CellVisualType.BLACK)
        self.window._on_cell_activated((1, 0))
        self.window._save_autosave_now()

        restored = None
        try:
            with patch(
                "hexsolver_cn.app.ask_confirmation",
                return_value=True,
            ) as confirmation:
                restored = MainWindow(
                    seed_generators=SeedGeneratorRegistry(),
                    preferences=self.preferences,
                    session_store=SessionStore(self.preferences_directory.name),
                    restore_on_startup=True,
                )
                confirmation.assert_not_called()
                restored.show()
                self.app.processEvents()
                confirmation.assert_called_once()
                self.assertTrue(confirmation.call_args.args[0].isVisible())
            self.assertEqual(SeedRequest(17, Difficulty.HARD), restored.current_seed)
            self.assertIs(
                CellVisualType.BLACK,
                restored.session.board.get_cell((1, 0)).visual_type,
            )
            self.assertFalse(restored._guide_visible)
            self.assertIn("自动恢复", restored.stage.mode_chip.text())
        finally:
            if restored is not None:
                restored.close()

    def test_autosave_decline_discards_progress_and_keeps_guide(self) -> None:
        self.window._save_autosave_now()
        fresh = None
        try:
            with patch(
                "hexsolver_cn.app.ask_confirmation",
                return_value=False,
            ) as confirmation:
                fresh = MainWindow(
                    seed_generators=SeedGeneratorRegistry(),
                    preferences=self.preferences,
                    session_store=SessionStore(self.preferences_directory.name),
                    restore_on_startup=True,
                )
                confirmation.assert_not_called()
                fresh.show()
                self.app.processEvents()
                confirmation.assert_called_once()
                self.assertTrue(confirmation.call_args.args[0].isVisible())
            self.assertFalse(fresh._has_active_board)
            self.assertTrue(fresh._guide_visible)
            self.assertFalse(fresh.session_store.has_autosave())
        finally:
            if fresh is not None:
                fresh.close()

    def test_fresh_window_uses_guide_instead_of_demo_board(self) -> None:
        fresh = MainWindow(
            seed_generators=SeedGeneratorRegistry(),
            preferences=self.preferences,
            session_store=SessionStore(self.preferences_directory.name),
        )
        fresh.show()
        self.app.processEvents()
        try:
            self.assertEqual({}, fresh.session.board.cells)
            self.assertEqual((), fresh.stage.board_view.row_clue_items)
            self.assertTrue(fresh._guide_visible)
            self.assertTrue(fresh.onboarding_overlay.isVisible())
            self.assertTrue(fresh.guide_close_button.isVisible())
            self.assertIn("尚未生成地图", fresh.stage.mode_chip.text())
            self.assertFalse(fresh.next_button.isEnabled())
            self.assertFalse(fresh.stage.board_view.isEnabled())
            self.assertFalse(fresh.stage.counter_badge.isVisible())
            self.assertEqual(4, len(fresh.onboarding_overlay.notes))
            self.assertTrue(
                all(note.accessibleName() for note in fresh.onboarding_overlay.notes)
            )

            fresh._load_board(build_demo_board(), mode_text="真实盘面", verified=True)
            self.app.processEvents()
            self.assertFalse(fresh._guide_visible)
            self.assertFalse(fresh.onboarding_overlay.isVisible())
            self.assertTrue(fresh.next_button.isEnabled())
            self.assertTrue(fresh.stage.board_view.isEnabled())

            fresh.show_onboarding()
            self.assertTrue(fresh._guide_visible)
            self.assertFalse(fresh.next_button.isEnabled())
            fresh.hide_onboarding()
            self.assertTrue(fresh.next_button.isEnabled())
        finally:
            fresh.close()

    def test_startup_window_mode_defaults_to_maximized_and_dispatches_all_modes(self) -> None:
        self.assertIs(
            StartupWindowMode.MAXIMIZED,
            self.preferences.startup_window_mode,
        )

        class WindowRecorder:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def showMaximized(self) -> None:
                self.calls.append("maximized")

            def showFullScreen(self) -> None:
                self.calls.append("fullscreen")

            def showNormal(self) -> None:
                self.calls.append("normal")

        expected = {
            StartupWindowMode.MAXIMIZED: "maximized",
            StartupWindowMode.FULLSCREEN: "fullscreen",
            StartupWindowMode.NORMAL: "normal",
        }
        for mode, call in expected.items():
            recorder = WindowRecorder()
            show_window_for_startup(recorder, mode)  # type: ignore[arg-type]
            self.assertEqual([call], recorder.calls)

    def test_sidebar_removes_secondary_panels_and_prioritizes_reason_panel(self) -> None:
        self.window.show()
        self.app.processEvents()

        self.assertFalse(hasattr(self.window, "history"))
        self.assertFalse(hasattr(self.window, "history_list"))
        self.assertFalse(hasattr(self.window, "remaining_value"))
        self.assertFalse(hasattr(self.window, "error_value"))
        self.assertGreaterEqual(self.window.step_reason.height(), 560)
        self.assertTrue(all(button.size().width() == 60 for button in self.window.state_buttons.values()))
        self.assertTrue(all(button.size().height() == 56 for button in self.window.state_buttons.values()))
        self.assertTrue(all(button.accessibleName() for button in self.window.state_buttons.values()))
        self.assertFalse(self.window.stage.counter_badge.grab().isNull())

        self.window.resize(1120, 760)
        self.app.processEvents()
        self.assertGreaterEqual(self.window.step_reason.height(), 300)

    def test_step_actions_use_compact_simulation_and_next_buttons(self) -> None:
        self.window.show()
        self.app.processEvents()

        simulation_content_width = (
            self.window.simulation_button.fontMetrics().horizontalAdvance("模拟")
            + self.window.simulation_button.iconSize().width()
            + 20
        )
        self.assertEqual("模拟", self.window.simulation_button.text())
        self.assertEqual(72, self.window.simulation_button.width())
        self.assertEqual("开始模拟推演", self.window.simulation_button.accessibleName())
        self.assertEqual("开始模拟推演", self.window.simulation_button.toolTip())
        self.assertLessEqual(simulation_content_width, self.window.simulation_button.width())
        self.assertGreaterEqual(self.window.simulation_button.height(), 38)
        self.assertGreaterEqual(self.window.next_button.width(), 100)
        self.assertLess(self.window.next_button.width(), 170)

    def test_manual_state_buttons_render_distinct_active_outlines(self) -> None:
        self.window.show()
        self.app.processEvents()
        expected = {
            CellVisualType.HIDDEN: "#3D3F42",
            CellVisualType.BLUE: "#FFA814",
            CellVisualType.BLACK: "#0DA9E5",
        }

        for state, expected_color in expected.items():
            button = self.window.state_buttons[state]
            button.click()
            self.app.processEvents()

            color = QColor(expected_color)
            self.assertIs(self.window.selected_state, state)
            self.assertTrue(button.isChecked())
            self.assertEqual(color, button.outline_color())
            self.assertTrue(
                all(
                    other.isChecked() is (other_state is state)
                    for other_state, other in self.window.state_buttons.items()
                )
            )

            image = button.grab().toImage()
            rendered_outline_pixels = sum(
                image.pixelColor(x, y).rgb() == color.rgb()
                for x in range(image.width())
                for y in range(image.height())
            )
            self.assertGreater(rendered_outline_pixels, 30)

        self.window.state_buttons[CellVisualType.HIDDEN].click()

    def test_all_row_clues_remain_visible_above_board_items(self) -> None:
        view = self.window.stage.board_view
        expected = [row for row in self.window.session.board.row_clues if row.clue_text]

        self.assertEqual(len(expected), len(view.row_clue_items))
        self.assertTrue(all(item.isVisible() for item in view.row_clue_items))
        self.assertTrue(all(item.zValue() > 4 for item in view.row_clue_items))
        for row in expected:
            nearest_cell_distance_squared = min(
                (row.anchor[0] - cell.center[0]) ** 2 + (row.anchor[1] - cell.center[1]) ** 2
                for cell in self.window.session.board.cells.values()
            )
            self.assertGreaterEqual(nearest_cell_distance_squared, 50.0**2)
        margins = view.viewportMargins()
        self.assertGreaterEqual(margins.top(), 64)
        self.assertGreaterEqual(margins.right(), 132)

        view.row_clue_items[0].setVisible(False)
        view.sync_state()
        self.assertTrue(view.row_clue_items[0].isVisible())

    def test_step_card_preserves_long_multiline_reason_in_scrollable_view(self) -> None:
        reason = "推理过程：\n" + "\n".join(
            f"{index}. 这是第 {index} 条可核查条件与计算说明。" for index in range(1, 81)
        )
        move = SuggestedMove(
            coord=(0, 0),
            action=MoveAction.MARK_BLUE,
            reason=reason,
            source="全局求解",
        )

        self.window._update_step_card(move)
        self.window.show()
        self.app.processEvents()

        self.assertEqual(reason, self.window.step_reason.toPlainText())
        self.assertGreater(self.window.step_reason.verticalScrollBar().maximum(), 0)
        self.assertEqual(0, self.window.step_reason.verticalScrollBar().value())
        self.assertTrue(self.window.apply_button.isEnabled())
        self.assertLess(
            self.window.step_reason.geometry().bottom(),
            self.window.step_action_bar.geometry().top(),
        )
        scroll_bar = self.window.step_reason.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        self.assertEqual(scroll_bar.maximum(), scroll_bar.value())
        end_cursor = QTextCursor(self.window.step_reason.document())
        end_cursor.movePosition(QTextCursor.MoveOperation.End)
        end_rect = self.window.step_reason.cursorRect(end_cursor)
        visible_bottom = self.window.step_reason.viewport().rect().bottom()
        self.assertLessEqual(end_rect.bottom(), visible_bottom - 16)
        self.assertGreaterEqual(
            self.window.step_reason.document().rootFrame().frameFormat().bottomMargin(),
            STEP_REASON_BOTTOM_SAFE_MARGIN,
        )

    def test_reason_array_hover_highlights_every_related_cell_then_clears(self) -> None:
        coords = tuple(list(self.window.session.board.cells)[:6])
        coords_text = "[" + "、".join(f"({q}, {r})" for q, r in coords) + "]"
        reason = f"推理过程：\n1. 未知集合 A = {coords_text}。"
        self.window._set_step_reason(reason)
        self.window.show()
        self.app.processEvents()
        reference = next(
            item
            for item in self.window.step_reason.references
            if item.kind is ReasonReferenceKind.CELLS and len(item.coords) == len(coords)
        )

        position = self.window.step_reason.reference_cursor_rect(reference).center()
        QTest.mouseMove(self.window.step_reason.viewport(), position)
        self.app.processEvents()

        self.assertEqual(set(coords), set(self.window.stage.board_view.reason_highlighted_coords))
        self.assertFalse(self.window.stage.board_view.reason_highlight_is_pinned)
        board_view = self.window.stage.board_view
        for coord in coords:
            halo = board_view._reason_halo_items[coord]
            accent = board_view._reason_overlay_items[coord]
            self.assertTrue(halo.isVisible())
            self.assertTrue(accent.isVisible())
            self.assertIs(accent.pen().style(), Qt.PenStyle.CustomDashLine)
            self.assertGreater(halo.pen().widthF(), accent.pen().widthF())
            self.assertGreater(
                halo.polygon().boundingRect().width(),
                accent.polygon().boundingRect().width(),
            )
        if self.window.stage.board_view._reason_animation_enabled:
            self.assertTrue(self.window.stage.board_view.reason_animation_active)
            QTest.qWait(320)
            self.app.processEvents()
            self.assertFalse(self.window.stage.board_view.reason_animation_active)

        leave = QEvent(QEvent.Type.Leave)
        QApplication.sendEvent(self.window.step_reason, leave)
        self.app.processEvents()
        self.assertEqual((), self.window.stage.board_view.reason_highlighted_coords)

    def test_reduced_motion_disables_reason_fade_but_keeps_layered_outline(self) -> None:
        board = self.window.session.board
        coord = next(iter(board.cells))
        reference = parse_reason_references(f"格子 ({coord[0]}, {coord[1]})", board)[0]

        with patch.dict(os.environ, {"HEXSOLVER_REDUCED_MOTION": "1"}):
            view = HexBoardView()
        view.set_board(board)
        view.set_reason_reference(reference)

        self.assertEqual((coord,), view.reason_highlighted_coords)
        self.assertFalse(view.reason_animation_active)
        self.assertTrue(view._reason_halo_items[coord].isVisible())
        self.assertAlmostEqual(0.30, view._reason_halo_items[coord].opacity(), places=2)
        self.assertIs(
            view._reason_overlay_items[coord].pen().style(),
            Qt.PenStyle.CustomDashLine,
        )
        view.deleteLater()

    def test_reason_references_never_request_a_hover_tooltip(self) -> None:
        coord = next(iter(self.window.session.board.cells))
        self.window._set_step_reason(f"格子 ({coord[0]}, {coord[1]}) 必须判蓝。")
        reference = self.window.step_reason.references[0]
        cursor = QTextCursor(self.window.step_reason.document())
        cursor.setPosition(reference.start + 1)

        self.assertEqual("", cursor.charFormat().toolTip())
        self.assertEqual("", self.window.step_reason.toolTip())
        self.assertEqual("", self.window.step_reason.viewport().toolTip())
        self.assertTrue(
            self.window.step_reason.viewportEvent(QEvent(QEvent.Type.ToolTip))
        )

    def test_row_reference_hover_highlights_row_clue_and_covered_cells(self) -> None:
        row = self.window.session.board.row_clues[0]
        reason = f"推理过程：\n1. 条件：{row.display_name()} 的提示 {row.clue_text}。"
        self.window._set_step_reason(reason)
        self.window.show()
        self.app.processEvents()
        reference = next(
            item for item in self.window.step_reason.references if item.row_key is not None
        )

        QTest.mouseMove(
            self.window.step_reason.viewport(),
            self.window.step_reason.reference_cursor_rect(reference).center(),
        )
        self.app.processEvents()

        self.assertEqual(reference.row_key, self.window.stage.board_view.reason_highlighted_row)
        self.assertEqual(set(row.coords), set(self.window.stage.board_view.reason_highlighted_coords))

    def test_click_pins_bold_reference_and_second_click_unpins_it(self) -> None:
        coord = next(iter(self.window.session.board.cells))
        reason = f"结论：格子 ({coord[0]}, {coord[1]}) 必须判蓝。"
        self.window._set_step_reason(reason)
        self.window.show()
        self.app.processEvents()
        reference = self.window.step_reason.references[0]
        self._click_reason_reference(reference)
        QApplication.sendEvent(self.window.step_reason, QEvent(QEvent.Type.Leave))
        self.app.processEvents()

        cursor = QTextCursor(self.window.step_reason.document())
        cursor.setPosition(reference.start + 1)
        self.assertEqual(reference, self.window.step_reason.pinned_reference)
        self.assertGreaterEqual(cursor.charFormat().fontWeight(), QFont.Weight.Bold)
        self.assertEqual((coord,), self.window.stage.board_view.reason_highlighted_coords)
        self.assertTrue(self.window.stage.board_view.reason_highlight_is_pinned)
        board_view = self.window.stage.board_view
        self.assertTrue(board_view._reason_halo_items[coord].isVisible())
        self.assertIs(
            board_view._reason_overlay_items[coord].pen().style(),
            Qt.PenStyle.SolidLine,
        )
        self.assertGreaterEqual(board_view._reason_halo_items[coord].opacity(), 0.38)

        self._click_reason_reference(reference)
        QApplication.sendEvent(self.window.step_reason, QEvent(QEvent.Type.Leave))
        self.app.processEvents()

        self.assertIsNone(self.window.step_reason.pinned_reference)
        self.assertEqual((), self.window.stage.board_view.reason_highlighted_coords)

    def test_new_reason_clears_pinned_reference_without_changing_plain_text(self) -> None:
        coord = next(iter(self.window.session.board.cells))
        reason = f"格子 ({coord[0]}, {coord[1]}) 必须判蓝。"
        self.window._set_step_reason(reason)
        self.window.show()
        self.app.processEvents()
        reference = self.window.step_reason.references[0]
        self._activate_reason_reference(reference)
        self.assertIsNotNone(self.window.step_reason.pinned_reference)

        replacement = "手动同步到卡住的位置后，获取一个必然成立的步骤。"
        self.window._set_step_reason(replacement)
        self.app.processEvents()

        self.assertEqual(replacement, self.window.step_reason.toPlainText())
        self.assertIsNone(self.window.step_reason.pinned_reference)
        self.assertEqual((), self.window.stage.board_view.reason_highlighted_coords)

    def test_screenshot_import_is_disabled_in_ui_and_guarded_in_handler(self) -> None:
        board_before = self.window.session.board

        self.assertFalse(self.window.stage.import_button.isEnabled())
        self.assertIn("暂时关闭", self.window.stage.import_button.toolTip())
        with patch("hexsolver_cn.app.QFileDialog.getOpenFileName") as file_picker:
            self.window.import_screenshot()

        file_picker.assert_not_called()
        self.assertIs(self.window.session.board, board_before)
        self.assertIn("截图识别功能暂时关闭", self.window.stage.toast.text())

    def test_settings_entry_is_accessible_and_cache_page_can_clear_results(self) -> None:
        self.assertTrue(self.window.stage.settings_button.isEnabled())
        self.assertEqual("设置", self.window.stage.settings_button.toolTip())
        self.assertEqual("设置", self.window.stage.settings_button.accessibleName())

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = SeedResultCache(temporary_directory)
            cache_file = Path(temporary_directory) / "seed-fixture.json"
            cache_file.write_text("{}", encoding="utf-8")
            dialog = SettingsDialog(cache, self.preferences, self.window)
            dialog.show()
            self.app.processEvents()

            self.assertEqual("1 项", dialog.cache_count_value.text())
            self.assertNotEqual("0 B", dialog.cache_size_value.text())
            self.assertEqual(
                str(Path(temporary_directory).resolve()),
                dialog.cache_path_value.text(),
            )
            self.assertTrue(dialog.clear_cache_button.isEnabled())
            self.assertEqual(
                "删除全部种子结果缓存",
                dialog.clear_cache_button.accessibleName(),
            )
            self.assertEqual(
                StartupWindowMode.MAXIMIZED.value,
                dialog.startup_mode_combo.currentData(),
            )
            self.assertEqual("重新查看使用说明", dialog.show_guide_button.accessibleName())

            with patch(
                "hexsolver_cn.settings_dialog.ask_confirmation",
                return_value=True,
            ):
                dialog.confirm_clear_cache()

            self.assertEqual("0 项", dialog.cache_count_value.text())
            self.assertFalse(cache_file.exists())
            self.assertFalse(dialog.clear_cache_button.isEnabled())
            self.assertIn("已删除", dialog.feedback_label.text())
            dialog.close()

    def test_confirmation_dialog_forces_light_surface_and_clear_actions(self) -> None:
        dialog = LightConfirmDialog(
            self.window,
            title="发现未完成的局面",
            message="检测到上一次自动保存的局面，要从这里继续吗？",
            detail="继续会恢复盘面；放弃会删除自动保存。",
            accept_text="继续局面",
            reject_text="放弃并查看说明",
        )
        try:
            with (
                patch.object(dialog, "raise_") as raise_dialog,
                patch.object(dialog, "activateWindow") as activate_dialog,
            ):
                self.window.show()
                dialog.show()
                self.app.processEvents()
                raise_dialog.assert_called_once()
                activate_dialog.assert_called_once()
            self.assertIn("background-color: #FFFFFF", dialog.styleSheet())
            self.assertEqual("发现未完成的局面", dialog.title_label.text())
            self.assertEqual("继续局面", dialog.accept_button.text())
            self.assertEqual("放弃并查看说明", dialog.reject_button.text())
            self.assertTrue(dialog.accept_button.isDefault())
            self.assertGreaterEqual(dialog.accept_button.height(), 42)
            self.assertEqual("关闭", dialog.close_button.accessibleName())
            self.assertTrue(self.window.isVisible())
            self.assertFalse(
                bool(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            )
        finally:
            dialog.close()

    def test_startup_mode_and_guide_request_are_persisted_and_exposed(self) -> None:
        dialog = SettingsDialog(None, self.preferences, self.window)
        dialog.show()
        self.app.processEvents()

        fullscreen_index = dialog.startup_mode_combo.findData(
            StartupWindowMode.FULLSCREEN.value
        )
        dialog.startup_mode_combo.setCurrentIndex(fullscreen_index)
        self.app.processEvents()

        self.assertIs(
            StartupWindowMode.FULLSCREEN,
            self.preferences.startup_window_mode,
        )
        reloaded = AppPreferences(
            QSettings(str(self.preferences_path), QSettings.Format.IniFormat)
        )
        self.assertIs(StartupWindowMode.FULLSCREEN, reloaded.startup_window_mode)
        self.assertIn("下次启动", dialog.feedback_label.text())

        dialog.show_guide_button.click()
        self.app.processEvents()
        self.assertTrue(dialog.guide_requested)

    def test_startup_mode_uses_white_collapsed_combo_and_white_popup(self) -> None:
        dialog = SettingsDialog(None, self.preferences, self.window)
        dialog.show()
        self.app.processEvents()

        combo = dialog.startup_mode_combo
        popup = combo.view()
        self.assertFalse(popup.isVisible())
        self.assertEqual(3, combo.count())
        self.assertEqual(
            QColor("#FFFFFF"),
            popup.palette().color(QPalette.ColorRole.Base),
        )
        self.assertEqual(
            QColor("#3C3E40"),
            popup.palette().color(QPalette.ColorRole.Text),
        )

        collapsed = combo.grab().toImage()
        collapsed_light_pixels = sum(
            collapsed.pixelColor(x, y).red() >= 245
            and collapsed.pixelColor(x, y).green() >= 245
            and collapsed.pixelColor(x, y).blue() >= 245
            for x in range(collapsed.width())
            for y in range(collapsed.height())
        )
        self.assertGreater(
            collapsed_light_pixels,
            collapsed.width() * collapsed.height() * 0.55,
        )
        chevron_center_x = collapsed.width() - 20
        chevron_center_y = collapsed.height() // 2
        chevron_dark_pixels = sum(
            collapsed.pixelColor(x, y).red() < 180
            and collapsed.pixelColor(x, y).green() < 180
            and collapsed.pixelColor(x, y).blue() < 180
            for x in range(chevron_center_x - 6, chevron_center_x + 7)
            for y in range(chevron_center_y - 6, chevron_center_y + 7)
        )
        self.assertGreater(chevron_dark_pixels, 8)

        combo.showPopup()
        self.app.processEvents()
        self.assertTrue(popup.isVisible())
        popup_image = popup.viewport().grab().toImage()
        light_pixels = 0
        dark_surface_pixels = 0
        selected_pixels = 0
        for x in range(popup_image.width()):
            for y in range(popup_image.height()):
                color = popup_image.pixelColor(x, y)
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
        pixel_count = popup_image.width() * popup_image.height()
        self.assertGreater(light_pixels, pixel_count * 0.65)
        self.assertLess(dark_surface_pixels, pixel_count * 0.12)
        self.assertGreater(selected_pixels, pixel_count * 0.20)

        combo.hidePopup()
        self.app.processEvents()
        self.assertFalse(popup.isVisible())
        dialog.close()

    def test_settings_guide_request_reopens_onboarding_in_main_window(self) -> None:
        self.window.show()
        self.app.processEvents()
        self.assertFalse(self.window._guide_visible)
        with patch("hexsolver_cn.app.SettingsDialog") as dialog_type:
            dialog = dialog_type.return_value
            dialog.guide_requested = True
            self.window.open_settings()

        dialog.exec.assert_called_once_with()
        self.assertTrue(self.window._guide_visible)
        self.assertTrue(self.window.onboarding_overlay.isVisible())
        self.assertFalse(self.window.next_button.isEnabled())

    def test_original_mouse_controls_setting_persists_and_updates_state(self) -> None:
        dialog = SettingsDialog(None, self.preferences, self.window)
        dialog.show()
        self.app.processEvents()

        self.assertFalse(self.preferences.original_mouse_controls_enabled)
        self.assertFalse(dialog.original_mouse_controls_toggle.isChecked())
        self.assertEqual("已关闭", dialog.mouse_controls_state_label.text())

        dialog.original_mouse_controls_toggle.click()
        self.app.processEvents()

        self.assertTrue(self.preferences.original_mouse_controls_enabled)
        self.assertEqual("已开启", dialog.mouse_controls_state_label.text())
        self.assertIn("已保存", dialog.feedback_label.text())
        reloaded = AppPreferences(
            QSettings(str(self.preferences_path), QSettings.Format.IniFormat)
        )
        self.assertTrue(reloaded.original_mouse_controls_enabled)
        dialog.close()

    def test_original_mouse_controls_map_real_left_and_right_clicks(self) -> None:
        view = self.window.stage.board_view
        self.window.show()
        self.app.processEvents()
        view.fit_board()
        self.app.processEvents()
        coords = [cell.coord for cell in self.window.session.board.hidden_cells()][:3]

        def click_cell(coord, button) -> None:  # type: ignore[no-untyped-def]
            cell = self.window.session.board.get_cell(coord)
            assert cell is not None
            position = view.mapFromScene(QPointF(*cell.center))
            QTest.mouseClick(view.viewport(), button, Qt.KeyboardModifier.NoModifier, position)
            self.app.processEvents()

        self.window._select_state(CellVisualType.BLACK)
        click_cell(coords[0], Qt.MouseButton.LeftButton)
        self.assertIs(
            self.window.session.board.get_cell(coords[0]).visual_type,
            CellVisualType.BLACK,
        )
        click_cell(coords[1], Qt.MouseButton.RightButton)
        self.assertIs(
            self.window.session.board.get_cell(coords[1]).visual_type,
            CellVisualType.HIDDEN,
        )

        self.preferences.set_original_mouse_controls_enabled(True)
        self.window._apply_mouse_control_preference()
        self.assertTrue(all(not button.isEnabled() for button in self.window.state_buttons.values()))
        self.assertTrue(
            all("左键排除，右键蓝色" in button.toolTip() for button in self.window.state_buttons.values())
        )
        self.assertIn("左键排除，右键蓝色", self.window.manual_help_button.toolTip())

        click_cell(coords[1], Qt.MouseButton.LeftButton)
        self.assertIs(
            self.window.session.board.get_cell(coords[1]).visual_type,
            CellVisualType.BLACK,
        )
        click_cell(coords[2], Qt.MouseButton.RightButton)
        self.assertIs(
            self.window.session.board.get_cell(coords[2]).visual_type,
            CellVisualType.BLUE,
        )
        click_cell(coords[2], Qt.MouseButton.RightButton)
        self.assertIs(
            self.window.session.board.get_cell(coords[2]).visual_type,
            CellVisualType.HIDDEN,
        )

    def test_manual_mark_and_undo_round_trip(self) -> None:
        coord = next(
            cell.coord
            for cell in self.window.session.board.hidden_cells()
            if cell.coord != (0, 0)
        )
        self.window._select_state(CellVisualType.BLACK)
        self.window._on_cell_activated(coord)
        self.assertIs(self.window.session.board.get_cell(coord).visual_type, CellVisualType.BLACK)

        self.window.undo()

        self.assertIs(self.window.session.board.get_cell(coord).visual_type, CellVisualType.HIDDEN)

    def test_simulation_disables_next_step_and_restores_real_board(self) -> None:
        coord = self.window.session.board.hidden_cells()[0].coord
        self.window._save_autosave_now()
        autosave_before = self.window.session_store.autosave_path.read_bytes()

        self.window.start_simulation()
        self.assertIsNotNone(self.window.simulation_session)
        self.assertFalse(self.window.step_action_bar.isHidden())
        self.assertTrue(self.window.next_button.isHidden())
        self.assertTrue(self.window.apply_button.isHidden())
        self.assertFalse(self.window.next_button.isEnabled())
        self.assertFalse(self.window.apply_button.isEnabled())
        self.assertIn("正在模拟推演", self.window.stage.mode_chip.text())
        self.assertEqual("结束模拟推演", self.window.simulation_button.text())

        with patch("hexsolver_cn.app.HexReasoningSolver.next_step") as next_step:
            self.window.solve_next_step()
            next_step.assert_not_called()
            self.assertIsNone(self.window._solve_thread)

        self.window._select_state(CellVisualType.BLACK)
        self.window._on_cell_activated(coord)
        self._wait_for_simulation_check()
        assert self.window.simulation_session is not None
        self.assertIs(
            CellVisualType.BLACK,
            self.window.simulation_session.board.get_cell(coord).visual_type,
        )
        self.assertIs(
            CellVisualType.HIDDEN,
            self.window.session.board.get_cell(coord).visual_type,
        )
        self.window._save_autosave_now()
        self.assertEqual(
            autosave_before,
            self.window.session_store.autosave_path.read_bytes(),
        )

        self.window.end_simulation()
        self._wait_for_simulation_check()
        self.assertIsNone(self.window.simulation_session)
        self.assertIs(
            CellVisualType.HIDDEN,
            self.window.session.board.get_cell(coord).visual_type,
        )
        self.assertFalse(self.window.next_button.isHidden())
        self.assertFalse(self.window.apply_button.isHidden())
        self.assertTrue(self.window.next_button.isEnabled())
        self.assertEqual("模拟", self.window.simulation_button.text())
        self.assertEqual(72, self.window.simulation_button.width())

    def test_simulation_marks_never_release_private_clues(self) -> None:
        coord = self.window.session.board.hidden_cells()[0].coord
        self.window.session.private_reveals[coord] = CellReveal(
            visual_type=CellVisualType.BLACK,
            clue_text="-2-",
            clue_type=ClueType.NONCONSECUTIVE,
            clue_number=2,
        )
        self.window.start_simulation()
        self.window._select_state(CellVisualType.BLACK)
        self.window._on_cell_activated(coord)
        self._wait_for_simulation_check()

        assert self.window.simulation_session is not None
        simulated = self.window.simulation_session.board.get_cell(coord)
        real = self.window.session.board.get_cell(coord)
        assert simulated is not None and real is not None
        self.assertEqual("", simulated.clue_text)
        self.assertIs(ClueType.NONE, simulated.clue_type)
        self.assertIs(CellVisualType.HIDDEN, real.visual_type)
        self.assertEqual("", real.clue_text)

        self.window.end_simulation()
        self._wait_for_simulation_check()

    def test_simulation_conflict_highlights_sufficient_assumption_set(self) -> None:
        self.window.start_simulation()
        assert self.window.simulation_session is not None
        simulation = self.window.simulation_session
        remaining = simulation.initial_board.remaining_blue
        assert remaining is not None
        coords = [cell.coord for cell in simulation.board.hidden_cells()]
        for coord in coords[: remaining + 1]:
            simulation.set_cell_state(coord, CellVisualType.BLUE)
        self.window._simulation_changed()
        self._wait_for_simulation_check()

        highlighted = self.window.stage.board_view.simulation_conflict_coords
        self.assertTrue(highlighted)
        self.assertTrue(set(highlighted).issubset(set(simulation.changed_coords)))
        self.assertEqual("发现模拟矛盾", self.window.step_title.text())
        self.assertIn("共同导致公开条件无解", self.window.step_reason.toPlainText())
        self.assertIn("不代表", self.window.step_reason.toPlainText())

        self.window.reset_board()
        self._wait_for_simulation_check()
        self.assertEqual((), simulation.changed_coords)
        self.assertEqual((), self.window.stage.board_view.simulation_conflict_coords)
        self.window.end_simulation()
        self._wait_for_simulation_check()

    def test_unverified_seed_does_not_replace_current_board(self) -> None:
        before = self.window.session.board
        self.window.seed_input.setText("13625604")
        self.window.easy_button.setChecked(False)
        self.window.hard_button.setChecked(True)

        self.window.generate_seed_board()

        self.assertIs(self.window.session.board, before)
        self.assertIn("未验证", self.window.stage.mode_chip.text())

    def test_verified_backend_generates_without_blocking_ui(self) -> None:
        fixture = (
            os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "hard_00000001_v4.tsv",
            )
        )
        with open(fixture, "r", encoding="utf-8-sig") as stream:
            text = stream.read()
        registry = SeedGeneratorRegistry()
        registry.register(OriginalRuntimeHardBackend(FixtureRunner(text)))
        self.window.close()
        self.window = MainWindow(
            seed_generators=registry,
            preferences=self.preferences,
            session_store=SessionStore(self.preferences_directory.name),
        )
        self.window.easy_button.setChecked(False)
        self.window.hard_button.setChecked(True)
        self.window.seed_input.setText("1")

        self.window.generate_seed_board()
        self.assertFalse(self.window.generate_button.isEnabled())
        deadline = time.monotonic() + 3.0
        while self.window._generation_thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertIsNone(self.window._generation_thread)
        self.assertEqual(83, len(self.window.session.board.cells))
        self.assertEqual(9, len(self.window.session.board.row_clues))
        self.assertEqual(9, len(self.window.stage.board_view.row_clue_items))
        self.assertTrue(all(item.isVisible() for item in self.window.stage.board_view.row_clue_items))
        self.assertIn("离线精确生成", self.window.stage.mode_chip.text())
        self.assertTrue(self.window.generate_button.isEnabled())

        reveal_coord = next(
            coord
            for coord, reveal in self.window.session.private_reveals.items()
            if reveal.visual_type is CellVisualType.BLACK
            and reveal.clue_number is not None
            and self.window.session.board.get_cell(coord).visual_type is CellVisualType.HIDDEN
        )
        expected_text = self.window.session.private_reveals[reveal_coord].clue_text
        self.window._select_state(CellVisualType.BLACK)
        self.window._on_cell_activated(reveal_coord)
        self.assertEqual(expected_text, self.window.session.board.get_cell(reveal_coord).clue_text)
        self.assertEqual(expected_text, self.window.stage.board_view._cell_text_items[reveal_coord].text())

        self.window.undo()
        self.assertEqual("", self.window.session.board.get_cell(reveal_coord).clue_text)
        self.assertEqual("", self.window.stage.board_view._cell_text_items[reveal_coord].text())


if __name__ == "__main__":
    unittest.main()
