from __future__ import annotations

import argparse
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from hexsolver_cn.app import MainWindow
from hexsolver_cn.settings_dialog import SettingsDialog
from hexsolver_cn.theme import app_stylesheet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--suggestion", action="store_true")
    parser.add_argument("--scroll-reason-bottom", action="store_true")
    parser.add_argument("--apply-steps", type=int, default=0)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--difficulty", choices=("easy", "hard"), default="hard")
    parser.add_argument("--generation-timeout", type=float, default=180.0)
    parser.add_argument("--settings", action="store_true")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())

    window = MainWindow()
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
        if window.current_move is None:
            raise SystemExit("Solver stopped before the requested capture step.")
        window.apply_current_move()
    if args.suggestion:
        window.solve_next_step()
        window.stage.toast.hide()
    app.processEvents()
    if args.scroll_reason_bottom:
        scroll_bar = window.step_reason.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        app.processEvents()

    target = window
    settings_dialog = None
    if args.settings:
        settings_dialog = SettingsDialog(window.seed_generators.cache, window)
        settings_dialog.show()
        app.processEvents()
        target = settings_dialog

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not target.grab().save(str(args.output), "PNG"):
        raise SystemExit(f"Could not save screenshot: {args.output}")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
