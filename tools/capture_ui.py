from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication

from hexsolver_cn.app import MainWindow
from hexsolver_cn.dialogs import LightConfirmDialog
from hexsolver_cn.models import CellVisualType
from hexsolver_cn.preferences import AppPreferences
from hexsolver_cn.reason_interaction import ReasonReferenceKind
from hexsolver_cn.settings_dialog import SettingsDialog
from hexsolver_cn.session_store import SessionStore
from hexsolver_cn.theme import app_stylesheet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--suggestion", action="store_true")
    parser.add_argument("--first-global-suggestion", action="store_true")
    parser.add_argument("--scroll-reason-bottom", action="store_true")
    parser.add_argument("--apply-steps", type=int, default=0)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--difficulty", choices=("easy", "hard"), default="hard")
    parser.add_argument("--generation-timeout", type=float, default=180.0)
    parser.add_argument("--settings", action="store_true")
    parser.add_argument("--confirmation-dialog", action="store_true")
    parser.add_argument("--open-startup-dropdown", action="store_true")
    parser.add_argument("--manual-state", choices=("hidden", "blue", "black"))
    parser.add_argument("--original-mouse-controls", action="store_true")
    parser.add_argument("--pin-reason-reference", choices=("row", "array"))
    parser.add_argument("--simulation", action="store_true")
    parser.add_argument("--simulation-conflict", action="store_true")
    args = parser.parse_args()
    if args.open_startup_dropdown and not args.settings:
        parser.error("--open-startup-dropdown requires --settings")
    if args.settings and args.confirmation_dialog:
        parser.error("--settings and --confirmation-dialog cannot be used together")
    if args.first_global_suggestion and args.seed is None:
        parser.error("--first-global-suggestion requires --seed")
    if (args.simulation or args.simulation_conflict) and args.seed is None:
        parser.error("--simulation and --simulation-conflict require --seed")

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())

    preferences = AppPreferences(persistent=False)
    if args.original_mouse_controls:
        preferences.set_original_mouse_controls_enabled(True)
    capture_session_directory = tempfile.TemporaryDirectory(
        prefix="HexInfiniteSolver-capture-"
    )
    capture_session_store = SessionStore(capture_session_directory.name)
    window = MainWindow(
        preferences=preferences,
        session_store=capture_session_store,
    )
    window.setFixedSize(args.width, args.height)
    window.show()
    app.processEvents()
    if args.seed is not None:
        window.seed_input.setText(str(args.seed))
        window.easy_button.setChecked(args.difficulty == "easy")
        window.hard_button.setChecked(args.difficulty == "hard")
        window.generate_seed_board()
        deadline = time.monotonic() + args.generation_timeout
        while window._generation_thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        if window._generation_thread is not None or window.current_seed is None:
            raise SystemExit("Seed generation did not complete successfully.")
    window.stage.board_view.fit_board()
    for _ in range(args.apply_steps):
        window.solve_next_step()
        deadline = time.monotonic() + 10.0
        while window._solve_thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        if window.current_move is None:
            raise SystemExit("Solver stopped before the requested capture step.")
        window.apply_current_move()
    if args.first_global_suggestion:
        for _ in range(200):
            window.solve_next_step()
            deadline = time.monotonic() + 10.0
            while window._solve_thread is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            if window.current_move is None:
                raise SystemExit("Solver stopped before finding a global suggestion.")
            if window.current_move.source == "全局求解":
                break
            window.apply_current_move()
        else:
            raise SystemExit("No global suggestion found in the first 200 steps.")
    if args.suggestion:
        window.solve_next_step()
        deadline = time.monotonic() + 10.0
        while window._solve_thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        window.stage.toast.hide()
    app.processEvents()
    if args.pin_reason_reference:
        if (
            args.pin_reason_reference == "row"
            and not any(item.row_key is not None for item in window.step_reason.references)
        ):
            row = next(row for row in window.session.board.row_clues if row.clue_text)
            linked_coords = tuple(
                coord
                for coord in row.coords
                if window.session.board.get_cell(coord) is not None
            )
            coords_text = "[" + "、".join(
                f"({q}, {r})" for q, r in linked_coords
            ) + "]"
            window._set_step_reason(
                "推理过程：\n"
                f"1. 条件：{row.display_name()} 的提示 {row.clue_text}。\n"
                f"2. 关联格：{coords_text}。\n"
                "3. 说明：固定行引用后，外侧线索与整行格子同步高亮。"
            )
            app.processEvents()
        reference = next(
            (
                item
                for item in window.step_reason.references
                if (
                    item.row_key is not None
                    if args.pin_reason_reference == "row"
                    else item.kind is ReasonReferenceKind.CELLS and len(item.coords) > 1
                )
            ),
            None,
        )
        if reference is None:
            raise SystemExit(
                f"Current reasoning has no {args.pin_reason_reference} reference to pin."
            )
        window.step_reason._toggle_reference(reference)
        app.processEvents()
    if args.scroll_reason_bottom:
        scroll_bar = window.step_reason.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        app.processEvents()
    if args.manual_state:
        state = {
            "hidden": CellVisualType.HIDDEN,
            "blue": CellVisualType.BLUE,
            "black": CellVisualType.BLACK,
        }[args.manual_state]
        window.state_buttons[state].click()
        app.processEvents()
    if args.simulation or args.simulation_conflict:
        window.start_simulation()
        deadline = time.monotonic() + 10.0
        while window._simulation_conflict_thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        if args.simulation_conflict:
            simulation = window.simulation_session
            if simulation is None or simulation.initial_board.remaining_blue is None:
                raise SystemExit("Current board cannot produce a simulation conflict capture.")
            count = simulation.initial_board.remaining_blue + 1
            for cell in simulation.board.hidden_cells()[:count]:
                simulation.set_cell_state(cell.coord, CellVisualType.BLUE)
            window._simulation_changed()
            deadline = time.monotonic() + 10.0
            while (
                window._simulation_conflict_thread is not None
                and time.monotonic() < deadline
            ):
                app.processEvents()
                time.sleep(0.01)
        window.stage.toast.hide()
        app.processEvents()

    target = window
    settings_dialog = None
    confirmation_dialog = None
    if args.settings:
        settings_dialog = SettingsDialog(
            window.seed_generators.cache,
            preferences,
            window,
            session_store=capture_session_store,
            has_active_session=window._has_active_board,
        )
        settings_dialog.show()
        app.processEvents()
        if args.open_startup_dropdown:
            settings_dialog.startup_mode_combo.showPopup()
            app.processEvents()
        target = settings_dialog
    elif args.confirmation_dialog:
        confirmation_dialog = LightConfirmDialog(
            window,
            title="发现未完成的局面",
            message="检测到上一次自动保存的局面，要从这里继续吗？",
            detail=(
                "继续后会恢复盘面、撤销/重做记录和当前推理位置。\n"
                "放弃则删除这份自动保存，并显示使用说明。"
            ),
            accept_text="继续局面",
            reject_text="放弃并查看说明",
        )
        confirmation_dialog.show()
        app.processEvents()
        target = confirmation_dialog

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.open_startup_dropdown:
        capture = target.grab()
        popup_window = settings_dialog.startup_mode_combo.view().window()
        popup_capture = popup_window.grab()
        popup_origin = target.mapFromGlobal(popup_window.mapToGlobal(QPoint(0, 0)))
        painter = QPainter(capture)
        painter.drawPixmap(popup_origin, popup_capture)
        painter.end()
    else:
        capture = target.grab()
    if not capture.save(str(args.output), "PNG"):
        raise SystemExit(f"Could not save screenshot: {args.output}")
    capture_session_directory.cleanup()
    print(args.output.resolve())


if __name__ == "__main__":
    main()
