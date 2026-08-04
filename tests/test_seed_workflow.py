from __future__ import annotations

import unittest

from hexsolver_cn.models import Board, Cell, CellReveal, CellVisualType, ClueType
from hexsolver_cn.seed_workflow import (
    Difficulty,
    GeneratorFidelity,
    SeedGenerationUnavailable,
    SeedGeneratorRegistry,
    SeedRequest,
)
from hexsolver_cn.session import BoardStateError, InteractivePuzzleSession
from hexsolver_cn.solver import HexReasoningSolver


def build_count_one_board() -> Board:
    cells = {
        (0, 0): Cell(
            cell_id=1,
            coord=(0, 0),
            center=(60.0, 60.0),
            visual_type=CellVisualType.BLACK,
            clue_text="1",
            clue_type=ClueType.COUNT,
            clue_number=1,
        ),
        (1, 0): Cell(
            cell_id=2,
            coord=(1, 0),
            center=(100.0, 60.0),
            visual_type=CellVisualType.HIDDEN,
        ),
    }
    return Board(
        image_path="",
        image_size=(180, 120),
        cells=cells,
        row_clues=[],
        origin=(60.0, 60.0),
        basis_a=(40.0, 0.0),
        basis_b=(20.0, 34.0),
        ring_threshold=18.0,
    )


class SeedRequestTests(unittest.TestCase):
    def test_parses_seed_and_difficulty(self) -> None:
        request = SeedRequest.parse("13625604", "Hard")
        self.assertEqual(13_625_604, request.seed)
        self.assertIs(Difficulty.HARD, request.difficulty)

    def test_rejects_invalid_seed(self) -> None:
        with self.assertRaisesRegex(ValueError, "十进制整数"):
            SeedRequest.parse("abc", "Easy")

    def test_registry_refuses_unverified_generation(self) -> None:
        registry = SeedGeneratorRegistry()
        request = SeedRequest.parse("1", "Hard")
        self.assertIs(GeneratorFidelity.SCAFFOLD, registry.fidelity_for(Difficulty.HARD))
        with self.assertRaises(SeedGenerationUnavailable):
            registry.generate(request)


class InteractiveSessionTests(unittest.TestCase):
    def test_next_step_returns_single_forced_blue(self) -> None:
        board = build_count_one_board()
        move = HexReasoningSolver().next_step(board)
        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual((1, 0), move.coord)
        self.assertEqual("mark_blue", move.action.value)

    def test_manual_state_and_undo(self) -> None:
        session = InteractivePuzzleSession(build_count_one_board())
        session.set_cell_state((1, 0), CellVisualType.BLUE)
        self.assertIs(CellVisualType.BLUE, session.board.get_cell((1, 0)).visual_type)
        session.undo()
        self.assertIs(CellVisualType.HIDDEN, session.board.get_cell((1, 0)).visual_type)

    def test_clue_cell_is_not_editable(self) -> None:
        session = InteractivePuzzleSession(build_count_one_board())
        with self.assertRaises(BoardStateError):
            session.set_cell_state((0, 0), CellVisualType.BLUE)

    def test_remaining_blue_updates_and_undoes(self) -> None:
        board = build_count_one_board()
        board.remaining_blue = 1
        session = InteractivePuzzleSession(board)

        session.set_cell_state((1, 0), CellVisualType.BLUE)
        self.assertEqual(0, session.board.remaining_blue)
        session.undo()
        self.assertEqual(1, session.board.remaining_blue)

    def test_cannot_mark_more_blue_than_remaining(self) -> None:
        board = build_count_one_board()
        board.remaining_blue = 0
        session = InteractivePuzzleSession(board)

        with self.assertRaisesRegex(BoardStateError, "超过"):
            session.set_cell_state((1, 0), CellVisualType.BLUE)
        self.assertIs(CellVisualType.HIDDEN, session.board.get_cell((1, 0)).visual_type)
        self.assertEqual(0, session.board.remaining_blue)

    def test_revealed_clue_is_exposed_only_after_manual_open_and_undoes(self) -> None:
        board = build_count_one_board()
        session = InteractivePuzzleSession(
            board,
            private_reveals={
                (1, 0): CellReveal(
                    visual_type=CellVisualType.BLACK,
                    clue_text="-2-",
                    clue_type=ClueType.NONCONSECUTIVE,
                    clue_number=2,
                )
            },
        )
        hidden = session.board.get_cell((1, 0))
        self.assertEqual("", hidden.clue_text)

        session.set_cell_state((1, 0), CellVisualType.BLACK)
        revealed = session.board.get_cell((1, 0))
        self.assertEqual("-2-", revealed.clue_text)
        self.assertIs(ClueType.NONCONSECUTIVE, revealed.clue_type)

        session.undo()
        restored = session.board.get_cell((1, 0))
        self.assertIs(CellVisualType.HIDDEN, restored.visual_type)
        self.assertEqual("", restored.clue_text)
        self.assertIs(ClueType.NONE, restored.clue_type)


if __name__ == "__main__":
    unittest.main()
