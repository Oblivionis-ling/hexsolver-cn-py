from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from hexsolver_cn.app import MainWindow, STEP_REASON_BOTTOM_SAFE_MARGIN  # noqa: E402
from hexsolver_cn.models import CellVisualType, MoveAction, SuggestedMove  # noqa: E402
from hexsolver_cn.original_bridge import (  # noqa: E402
    OriginalRuntimeHardBackend,
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
        self.window = MainWindow(seed_generators=SeedGeneratorRegistry())

    def tearDown(self) -> None:
        self.window.close()

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
            dialog = SettingsDialog(cache, self.window)
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
        self.window = MainWindow(seed_generators=registry)
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
