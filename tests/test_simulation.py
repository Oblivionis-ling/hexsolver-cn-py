from __future__ import annotations

import unittest

from hexsolver_cn.models import Board, Cell, CellVisualType, ClueType
from hexsolver_cn.session import BoardStateError
from hexsolver_cn.simulation import SimulationSession
from hexsolver_cn.solver import HexReasoningSolver


def build_two_candidate_board(*, remaining_blue: int | None = None) -> Board:
    return Board(
        image_path="",
        image_size=(220, 180),
        cells={
            (0, 0): Cell(
                cell_id=1,
                coord=(0, 0),
                center=(80.0, 80.0),
                visual_type=CellVisualType.BLACK,
                clue_text="1",
                clue_type=ClueType.COUNT,
                clue_number=1,
            ),
            (1, 0): Cell(
                cell_id=2,
                coord=(1, 0),
                center=(124.0, 80.0),
                visual_type=CellVisualType.HIDDEN,
            ),
            (0, 1): Cell(
                cell_id=3,
                coord=(0, 1),
                center=(102.0, 118.0),
                visual_type=CellVisualType.HIDDEN,
            ),
        },
        row_clues=[],
        origin=(80.0, 80.0),
        basis_a=(44.0, 0.0),
        basis_b=(22.0, 38.0),
        ring_threshold=18.0,
        remaining_blue=remaining_blue,
    )


class SimulationSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.real_board = build_two_candidate_board()
        self.session = SimulationSession(self.real_board)
        self.solver = HexReasoningSolver()

    def test_simulated_marks_do_not_mutate_or_reveal_the_real_board(self) -> None:
        self.session.set_cell_state((1, 0), CellVisualType.BLUE)

        simulated = self.session.board.get_cell((1, 0))
        real = self.real_board.get_cell((1, 0))
        assert simulated is not None and real is not None
        self.assertIs(CellVisualType.BLUE, simulated.visual_type)
        self.assertEqual("", simulated.clue_text)
        self.assertIs(ClueType.NONE, simulated.clue_type)
        self.assertIs(CellVisualType.HIDDEN, real.visual_type)
        self.assertFalse(hasattr(self.session, "private_reveals"))

    def test_starting_state_cells_are_locked(self) -> None:
        with self.assertRaisesRegex(BoardStateError, "已被固定"):
            self.session.set_cell_state((0, 0), CellVisualType.HIDDEN)

    def test_undo_redo_and_reset_are_isolated(self) -> None:
        self.session.set_cell_state((1, 0), CellVisualType.BLACK)
        self.session.undo()
        self.assertIs(
            CellVisualType.HIDDEN,
            self.session.board.get_cell((1, 0)).visual_type,
        )
        self.session.redo()
        self.assertIs(
            CellVisualType.BLACK,
            self.session.board.get_cell((1, 0)).visual_type,
        )
        self.session.reset()
        self.assertEqual((), self.session.changed_coords)
        self.assertEqual([], self.session.history)
        self.assertEqual([], self.session.redo_history)

    def test_single_legal_assumption_has_no_conflict(self) -> None:
        self.session.set_cell_state((1, 0), CellVisualType.BLUE)
        report = self.solver.find_public_conflict(
            self.session.initial_board,
            self.session.assumed_states(),
        )
        self.assertIsNone(report)

    def test_jointly_impossible_blue_marks_return_both_assumptions(self) -> None:
        self.session.set_cell_state((1, 0), CellVisualType.BLUE)
        self.session.set_cell_state((0, 1), CellVisualType.BLUE)
        report = self.solver.find_public_conflict(
            self.session.initial_board,
            self.session.assumed_states(),
        )
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual({(1, 0), (0, 1)}, set(report.assumption_coords))
        self.assertTrue(any("提示 1" in label for label in report.constraint_labels))
        self.assertFalse(report.base_board_inconsistent)

    def test_jointly_impossible_black_marks_return_both_assumptions(self) -> None:
        self.session.set_cell_state((1, 0), CellVisualType.BLACK)
        self.session.set_cell_state((0, 1), CellVisualType.BLACK)
        report = self.solver.find_public_conflict(
            self.session.initial_board,
            self.session.assumed_states(),
        )
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual({(1, 0), (0, 1)}, set(report.assumption_coords))

    def test_global_remaining_conflict_can_be_marked_instead_of_rejected(self) -> None:
        board = build_two_candidate_board(remaining_blue=0)
        board.cells.pop((0, 0))
        session = SimulationSession(board)
        session.set_cell_state((1, 0), CellVisualType.BLUE)
        self.assertEqual(-1, session.board.remaining_blue)

        report = self.solver.find_public_conflict(
            session.initial_board,
            session.assumed_states(),
        )
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(((1, 0),), report.assumption_coords)
        self.assertIn("顶部“剩余蓝格数”", report.constraint_labels)


if __name__ == "__main__":
    unittest.main()
