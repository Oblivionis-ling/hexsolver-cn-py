from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from hexsolver_cn.app import MainWindow, STEP_REASON_BOTTOM_SAFE_MARGIN  # noqa: E402
from hexsolver_cn.board_view import HexBoardView  # noqa: E402
from hexsolver_cn.models import CellVisualType, MoveAction, SuggestedMove  # noqa: E402
from hexsolver_cn.original_bridge import (  # noqa: E402
    OriginalRuntimeHardBackend,
)
from hexsolver_cn.preferences import AppPreferences  # noqa: E402
from hexsolver_cn.reason_interaction import (  # noqa: E402
    ReasonReferenceKind,
    parse_reason_references,
)
from hexsolver_cn.seed_cache import SeedResultCache  # noqa: E402
from hexsolver_cn.seed_workflow import Difficulty, SeedGeneratorRegistry  # noqa: E402
from hexsolver_cn.settings_dialog import SettingsDialog  # noqa: E402


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

    def test_demo_board_can_suggest_and_apply_one_forced_move(self) -> None:
        self.window.solve_next_step()
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

            with patch(
                "hexsolver_cn.settings_dialog.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                dialog.confirm_clear_cache()

            self.assertEqual("0 项", dialog.cache_count_value.text())
            self.assertFalse(cache_file.exists())
            self.assertFalse(dialog.clear_cache_button.isEnabled())
            self.assertIn("已删除", dialog.feedback_label.text())
            dialog.close()

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
        self.window = MainWindow(seed_generators=registry, preferences=self.preferences)
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
