from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from hexsolver_cn.models import CellVisualType, ClueType, LineFamily, MoveAction
from hexsolver_cn.original_bridge import (
    ExportCoordinateSystem,
    OriginalGameBridgeRunner,
    OriginalBoardExport,
    OriginalRuntimeEasyBackend,
    OriginalRuntimeHardBackend,
    ExportedCell,
    board_from_original_export,
    parse_original_export,
)
from hexsolver_cn.seed_workflow import Difficulty, GeneratorFidelity, SeedRequest
from hexsolver_cn.session import InteractivePuzzleSession
from hexsolver_cn.solver import HexReasoningSolver
from hexsolver_cn.unity_random import UnityRandom, float32_bits


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = WORKSPACE_ROOT / "reverse_harness" / "exports" / "hard_00000001_v4.tsv"
EASY_FIXTURE_PATH = WORKSPACE_ROOT / "reverse_harness" / "exports" / "easy_00000001_v1.tsv"
GAME_DIR = WORKSPACE_ROOT / "reverse_harness" / "game"


class FixtureRunner:
    def __init__(self, text: str) -> None:
        self.text = text
        self.seeds: list[int] = []
        self.difficulties: list[Difficulty] = []

    def generate_tsv(self, seed: int, difficulty: Difficulty = Difficulty.HARD) -> str:
        self.seeds.append(seed)
        self.difficulties.append(difficulty)
        return self.text


class OriginalExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = FIXTURE_PATH.read_text(encoding="utf-8-sig")
        cls.easy_text = EASY_FIXTURE_PATH.read_text(encoding="utf-8-sig")

    def test_seed_one_fixture_parses_to_public_board(self) -> None:
        export = parse_original_export(self.text)
        board, answer = board_from_original_export(export)

        self.assertEqual(1, export.seed)
        self.assertEqual(83, len(board.cells))
        self.assertEqual(9, len(board.row_clues))
        self.assertEqual(78, len(board.hidden_cells()))
        self.assertEqual(39, board.remaining_blue)
        self.assertEqual(5, len(board.all_clue_cells()))
        self.assertEqual(83, len(answer))
        self.assertTrue(any(row.clue_type is ClueType.NONCONSECUTIVE for row in board.row_clues))

    def test_even_doubled_coordinate_phase_is_detected(self) -> None:
        export = OriginalBoardExport(
            seed=4,
            cells=(
                ExportedCell(
                    raw_coord=(16, 22),
                    name="Black Hex",
                    tag="Clue Hex Blank",
                    layer=0,
                    clue_text="?",
                ),
            ),
            columns=(),
        )

        board, answer = board_from_original_export(export, Difficulty.HARD)

        self.assertIn((0, 4), board.cells)
        self.assertIs(CellVisualType.BLACK, answer[(0, 4)])

    def test_first_solver_step_matches_original_private_answer(self) -> None:
        board, answer = board_from_original_export(parse_original_export(self.text))
        move = HexReasoningSolver().next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        expected = CellVisualType.BLUE if move.action is MoveAction.MARK_BLUE else CellVisualType.BLACK
        self.assertIs(expected, answer[move.coord])

    def test_easy_seed_one_fixture_and_first_step(self) -> None:
        export = parse_original_export(self.easy_text)
        board, answer = board_from_original_export(export, Difficulty.EASY)
        move = HexReasoningSolver().next_step(board)

        self.assertEqual(1, export.seed)
        self.assertEqual(226, len(board.cells))
        self.assertEqual(20, len(board.row_clues))
        self.assertEqual(89, board.remaining_blue)
        self.assertTrue(
            any(cell.clue_type is ClueType.UNKNOWN for cell in board.cells.values())
        )
        self.assertIsNotNone(move)
        assert move is not None
        expected = CellVisualType.BLUE if move.action is MoveAction.MARK_BLUE else CellVisualType.BLACK
        self.assertIs(expected, answer[move.coord])

    def test_official_unity_y_axis_is_not_vertically_mirrored(self) -> None:
        export = parse_original_export(self.text)
        board, _ = board_from_original_export(export)
        coordinate_system = ExportCoordinateSystem.from_cells(export.cells)
        upper = max(export.cells, key=lambda cell: cell.raw_coord[1])
        lower = min(export.cells, key=lambda cell: cell.raw_coord[1])

        upper_center = board.get_cell(coordinate_system.to_axial(upper.raw_coord)).center
        lower_center = board.get_cell(coordinate_system.to_axial(lower.raw_coord)).center

        self.assertLess(upper_center[1], lower_center[1])

    def test_diagonal_column_labels_are_mirrored_with_the_board(self) -> None:
        export = parse_original_export(self.text)
        board, _ = board_from_original_export(export)

        for column, row in zip(export.columns, board.row_clues):
            if column.name == "Column Number Diagonal Right":
                self.assertIs(LineFamily.DOWN_LEFT, row.family)
                self.assertEqual("左下斜", row.family_label())
            elif column.name == "Column Number Diagonal Left":
                self.assertIs(LineFamily.DOWN_RIGHT, row.family)
                self.assertEqual("右下斜", row.family_label())

    def test_backend_checks_returned_seed(self) -> None:
        runner = FixtureRunner(self.text)
        backend = OriginalRuntimeHardBackend(runner)
        request = SeedRequest(seed=1, difficulty=Difficulty.HARD)

        puzzle = backend.generate(request)

        self.assertEqual([1], runner.seeds)
        self.assertEqual([Difficulty.HARD], runner.difficulties)
        self.assertIs(GeneratorFidelity.ORIGINAL_RUNTIME, puzzle.fidelity)
        puzzle.verify_public_board_has_no_hidden_answer()

    def test_easy_backend_uses_easy_runtime_mode(self) -> None:
        runner = FixtureRunner(self.easy_text)
        backend = OriginalRuntimeEasyBackend(runner)
        request = SeedRequest(seed=1, difficulty=Difficulty.EASY)

        puzzle = backend.generate(request)

        self.assertEqual([Difficulty.EASY], runner.difficulties)
        self.assertEqual(226, len(puzzle.public_board.cells))
        self.assertIs(GeneratorFidelity.ORIGINAL_RUNTIME, puzzle.fidelity)

    def test_process_runner_receives_isolated_export_contract(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_process(args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append({"args": args, **kwargs})
            export_path = Path(kwargs["env"]["HEXINFINITE_EXPORT_PATH"])
            export_path.write_text(self.text, encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")

        runner = OriginalGameBridgeRunner(GAME_DIR, process_runner=fake_process)
        returned = runner.generate_tsv(1)

        self.assertIn("SEED\t00000001", returned)
        self.assertEqual("1", calls[0]["env"]["HEXINFINITE_SEED"])
        self.assertEqual("hard", calls[0]["env"]["HEXINFINITE_DIFFICULTY"])
        self.assertIn("-batchmode", calls[0]["args"])

    def _assert_full_replay(self, text: str, difficulty: Difficulty) -> None:
        runner = FixtureRunner(text)
        backend = (
            OriginalRuntimeEasyBackend(runner)
            if difficulty is Difficulty.EASY
            else OriginalRuntimeHardBackend(runner)
        )
        puzzle = backend.generate(SeedRequest(seed=1, difficulty=difficulty))
        session = InteractivePuzzleSession(
            puzzle.public_board,
            HexReasoningSolver(),
            private_reveals=puzzle.private_reveals,
        )
        initial_hidden = len(session.board.hidden_cells())
        for step in range(1, initial_hidden + 1):
            move = session.next_step()
            self.assertIsNotNone(
                move,
                f"{difficulty.label} 在第 {step} 步、剩余 {len(session.board.hidden_cells())} 格时停住",
            )
            assert move is not None
            expected = (
                CellVisualType.BLUE
                if move.action is MoveAction.MARK_BLUE
                else CellVisualType.BLACK
            )
            self.assertIs(
                expected,
                puzzle.private_answer[move.coord],
                f"{difficulty.label} 第 {step} 步 {move.coord} 与原版私有答案冲突",
            )
            self.assertTrue(move.reason)
            session.apply_suggested_move(move)

        self.assertEqual([], session.board.hidden_cells())
        self.assertEqual(0, session.board.remaining_blue)

    def test_easy_seed_one_full_replay(self) -> None:
        self._assert_full_replay(self.easy_text, Difficulty.EASY)

    def test_hard_seed_one_full_replay(self) -> None:
        self._assert_full_replay(self.text, Difficulty.HARD)


class UnityRandomTests(unittest.TestCase):
    def test_seed_one_runtime_trace_bits(self) -> None:
        random = UnityRandom(1)
        self.assertEqual((1, 1812433254, 1900727103, 3690981084), tuple(random.state.__dict__.values()))
        self.assertEqual(3690984874, random.next_uint32())

        random = UnityRandom(1)
        self.assertEqual(1065347926, float32_bits(random.value()))

        random = UnityRandom(1)
        self.assertEqual(1543501227, random.range_int(0, 2_147_483_647))

    def test_hard_generator_prefix_matches_runtime_trace(self) -> None:
        random = UnityRandom(1)
        black = random.range_float(0.85, 0.96)
        blue = random.range_float(black * 0.07, black * 0.1)
        target = random.range_int(65, int(180.0 * black))
        self.assertAlmostEqual(0.8500347, black, places=7)
        self.assertAlmostEqual(0.065258965, blue, places=8)
        self.assertEqual(83, target)


if __name__ == "__main__":
    unittest.main()
