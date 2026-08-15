from __future__ import annotations

import unittest

from ortools.sat.python import cp_model

from hexsolver_cn.models import (
    Board,
    Cell,
    CellVisualType,
    ClueType,
    LineFamily,
    MoveAction,
    RowClue,
)
from hexsolver_cn.solver import HexReasoningSolver


def make_board(
    states: dict[tuple[int, int], CellVisualType],
    row_specs: list[tuple[str, list[tuple[int, int]], ClueType, int]] | None = None,
    *,
    remaining_blue: int | None = None,
) -> Board:
    cells = {
        coord: Cell(
            cell_id=index,
            coord=coord,
            center=(float(coord[0] * 40), float(coord[1] * 34)),
            visual_type=state,
        )
        for index, (coord, state) in enumerate(states.items(), start=1)
    }
    rows = [
        RowClue(
            line_id=line_id,
            family=LineFamily.HORIZONTAL,
            line_key=index,
            coords=coords,
            anchor=(0.0, 0.0),
            clue_text=(
                f"{{{number}}}"
                if clue_type is ClueType.CONSECUTIVE
                else f"-{number}-"
                if clue_type is ClueType.NONCONSECUTIVE
                else str(number)
            ),
            clue_type=clue_type,
            clue_number=number,
        )
        for index, (line_id, coords, clue_type, number) in enumerate(row_specs or [])
    ]
    return Board(
        image_path="",
        image_size=(320, 240),
        cells=cells,
        row_clues=rows,
        origin=(0.0, 0.0),
        basis_a=(40.0, 0.0),
        basis_b=(20.0, 34.0),
        ring_threshold=18.0,
        remaining_blue=remaining_blue,
    )


class SolverExplanationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.solver = HexReasoningSolver()

    def test_simple_count_blue_explains_current_state_and_equation(self) -> None:
        board = make_board(
            {(0, 0): CellVisualType.HIDDEN},
            [("H0", [(0, 0)], ClueType.COUNT, 1)],
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertIs(move.action, MoveAction.MARK_BLUE)
        self.assertIn("推理过程：", move.reason)
        self.assertIn("未知格 1 个 [(0, 0)]", move.reason)
        self.assertIn("1 - 0 = 1", move.reason)
        self.assertIn("必须判蓝", move.reason)

    def test_simple_count_black_explains_why_an_extra_blue_is_impossible(self) -> None:
        board = make_board(
            {
                (0, 0): CellVisualType.BLUE,
                (1, 0): CellVisualType.HIDDEN,
            },
            [("H0", [(0, 0), (1, 0)], ClueType.COUNT, 1)],
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertIs(move.action, MoveAction.MARK_BLACK)
        self.assertIn("已知蓝格 1 个 [(0, 0)]", move.reason)
        self.assertIn("1 - 1 = 0", move.reason)
        self.assertIn("蓝格总数就会超过 1", move.reason)

    def test_simple_count_short_circuits_every_harder_tier(self) -> None:
        class SimpleOnlySolver(HexReasoningSolver):
            def _apply_pattern_rule(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("找到局部计数步骤后不应再计算排列推理")

            def _apply_subset_rule(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("找到局部计数步骤后不应再计算子集差分")

            def _apply_remaining_rule(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("找到局部计数步骤后不应再计算全场剩余")

            def _collect_global_forced_moves(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("找到局部计数步骤后不应进入全局唯一性")

        board = make_board(
            {(0, 0): CellVisualType.HIDDEN},
            [("H0", [(0, 0)], ClueType.COUNT, 1)],
        )

        move = SimpleOnlySolver().next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual("局部必然", move.source)

    def test_pattern_short_circuits_subset_remaining_and_global_tiers(self) -> None:
        class PatternOnlySolver(HexReasoningSolver):
            def _apply_subset_rule(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("找到排列步骤后不应再计算子集差分")

            def _apply_remaining_rule(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("找到排列步骤后不应再计算全场剩余")

            def _collect_global_forced_moves(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("找到排列步骤后不应进入全局唯一性")

        coords = [(0, 0), (1, 0), (2, 0)]
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in coords},
            [("H0", coords, ClueType.CONSECUTIVE, 2)],
        )

        move = PatternOnlySolver().next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual("排列推理", move.source)

    def test_consecutive_pattern_lists_legal_arrangements_and_fixed_value(self) -> None:
        coords = [(0, 0), (1, 0), (2, 0)]
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in coords},
            [("H0", coords, ClueType.CONSECUTIVE, 2)],
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual((1, 0), move.coord)
        self.assertEqual("排列推理", move.source)
        self.assertIn("共有 2 种合法排列", move.reason)
        self.assertIn("为蓝 2 次、为黑 0 次", move.reason)
        self.assertIn("[(0, 0)、(1, 0)]", move.reason)

    def test_nonconsecutive_pattern_explains_filtered_arrangement(self) -> None:
        coords = [(0, 0), (1, 0), (2, 0)]
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in coords},
            [("H0", coords, ClueType.NONCONSECUTIVE, 2)],
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual("排列推理", move.source)
        self.assertIn("不能全部连成一个连续段", move.reason)
        self.assertIn("共有 1 种合法排列", move.reason)
        self.assertIn("[(0, 0)、(2, 0)]", move.reason)

    def test_subset_difference_shows_both_equations_and_difference_set(self) -> None:
        a = [(0, 0), (1, 0)]
        b = [(0, 0), (1, 0), (2, 0)]
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in b},
            [
                ("A", a, ClueType.COUNT, 1),
                ("B", b, ClueType.COUNT, 1),
            ],
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual((2, 0), move.coord)
        self.assertEqual("子集差分", move.source)
        self.assertIn("条件 A", move.reason)
        self.assertIn("条件 B", move.reason)
        self.assertIn("差集 B - A = [(2, 0)]", move.reason)
        self.assertIn("1 - 1 = 0", move.reason)

    def test_subset_difference_explains_when_every_difference_cell_is_blue(self) -> None:
        a = [(0, 0), (1, 0)]
        b = [(0, 0), (1, 0), (2, 0)]
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in b},
            [
                ("A", a, ClueType.COUNT, 1),
                ("B", b, ClueType.COUNT, 2),
            ],
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual((2, 0), move.coord)
        self.assertIs(move.action, MoveAction.MARK_BLUE)
        self.assertIn("2 - 1 = 1", move.reason)
        self.assertIn("正好等于差集大小 1", move.reason)

    def test_global_remaining_compares_remaining_and_unknown_counts(self) -> None:
        board = make_board(
            {
                (0, 0): CellVisualType.HIDDEN,
                (1, 0): CellVisualType.HIDDEN,
            },
            remaining_blue=2,
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual("全局剩余", move.source)
        self.assertIn("全盘当前还有 2 个未知格", move.reason)
        self.assertIn("剩余蓝格数 2 = 未知格数 2", move.reason)

    def test_global_remaining_zero_explains_why_target_is_black(self) -> None:
        board = make_board(
            {
                (0, 0): CellVisualType.HIDDEN,
                (1, 0): CellVisualType.HIDDEN,
            },
            remaining_blue=0,
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertIs(move.action, MoveAction.MARK_BLACK)
        self.assertIn("剩余蓝格为 0", move.reason)
        self.assertIn("必须判黑", move.reason)

    def test_global_forced_move_includes_wrong_assumption_conflict_core(self) -> None:
        x, y, z, w = (0, 0), (1, 0), (0, 1), (1, 1)
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in (x, y, z, w)},
            [
                ("A", [x, y], ClueType.COUNT, 1),
                ("B", [y, z], ClueType.COUNT, 1),
                ("C", [x, z, w], ClueType.COUNT, 2),
            ],
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual(x, move.coord)
        self.assertIs(move.action, MoveAction.MARK_BLUE)
        self.assertEqual("全局求解", move.source)
        self.assertTrue(move.reason.startswith("结论先看"))
        self.assertIn("可以把它理解成“试填排除”", move.reason)
        self.assertIn("先假设 格子 (0, 0) 是黑色", move.reason)
        self.assertIn("合法填法 = 0", move.reason)
        self.assertIn("关键条件概览", move.reason)
        self.assertIn("A / 横向 / 长度 2", move.reason)
        self.assertIn("B / 横向 / 长度 2", move.reason)
        self.assertIn("C / 横向 / 长度 3", move.reason)
        self.assertIn("完整的当前约束系统至少有 1 种合法填法", move.reason)
        self.assertIn("详细核查（第一次阅读可以先跳过）", move.reason)
        self.assertIn("不宣称它是唯一或数学上最小的证明", move.reason)

    def test_global_search_reuses_one_model_and_checks_only_opposite_value(self) -> None:
        class InstrumentedSolver(HexReasoningSolver):
            def __init__(self) -> None:
                super().__init__()
                self.model_builds = 0
                self.feasibility_solves = 0

            def _prepare_global_model(self, board):  # type: ignore[no-untyped-def]
                self.model_builds += 1
                return super()._prepare_global_model(board)

            def _solve_prepared_model(self, solver, prepared):  # type: ignore[no-untyped-def]
                self.feasibility_solves += 1
                return super()._solve_prepared_model(solver, prepared)

        x, y, z, w = (0, 0), (1, 0), (0, 1), (1, 1)
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in (x, y, z, w)},
            [
                ("A", [x, y], ClueType.COUNT, 1),
                ("B", [y, z], ClueType.COUNT, 1),
                ("C", [x, z, w], ClueType.COUNT, 2),
            ],
        )
        solver = InstrumentedSolver()

        move = solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual(x, move.coord)
        self.assertIs(move.action, MoveAction.MARK_BLUE)
        self.assertEqual(1, solver.model_builds)
        self.assertEqual(
            3,
            solver.feasibility_solves,
            "基础可行解、短时差异解和目标格相反值检查已经足以证明第一步",
        )

    def test_global_batch_uses_one_witness_and_one_probe_per_hidden_cell(self) -> None:
        class InstrumentedSolver(HexReasoningSolver):
            def __init__(self) -> None:
                super().__init__()
                self.model_builds = 0
                self.feasibility_solves = 0

            def _prepare_global_model(self, board):  # type: ignore[no-untyped-def]
                self.model_builds += 1
                return super()._prepare_global_model(board)

            def _solve_prepared_model(self, solver, prepared):  # type: ignore[no-untyped-def]
                self.feasibility_solves += 1
                return super()._solve_prepared_model(solver, prepared)

        coords = ((0, 0), (1, 0), (0, 1), (1, 1))
        x, y, z, w = coords
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in coords},
            [
                ("A", [x, y], ClueType.COUNT, 1),
                ("B", [y, z], ClueType.COUNT, 1),
                ("C", [x, z, w], ClueType.COUNT, 2),
            ],
        )
        solver = InstrumentedSolver()

        moves = solver.solve(board)

        self.assertEqual(set(coords), {move.coord for move in moves})
        self.assertEqual(1, solver.model_builds)
        self.assertEqual(2 + len(coords), solver.feasibility_solves)

    def test_diverse_witness_safely_identifies_cells_with_both_values(self) -> None:
        x, y = (0, 0), (1, 0)
        board = make_board(
            {x: CellVisualType.HIDDEN, y: CellVisualType.HIDDEN},
            [("A", [x, y], ClueType.COUNT, 1)],
        )
        solver = HexReasoningSolver()
        prepared = solver._prepare_global_model(board)
        cp_solver = solver._new_feasibility_solver()
        status = solver._solve_prepared_model(cp_solver, prepared)
        self.assertIn(status, (cp_model.OPTIMAL, cp_model.FEASIBLE))
        witness = {
            coord: bool(cp_solver.Value(variable))
            for coord, variable in prepared.variables.items()
        }

        flexible = solver._find_witness_variations(prepared, witness)

        self.assertEqual({x, y}, flexible)
        self.assertFalse(prepared.model.has_objective())

    def test_diverse_witness_timeout_falls_back_to_exact_cell_probes(self) -> None:
        class DiversityTimeoutSolver(HexReasoningSolver):
            def _solve_prepared_model(self, cp_solver, prepared):  # type: ignore[no-untyped-def]
                if prepared.model.has_objective():
                    return cp_model.UNKNOWN
                return super()._solve_prepared_model(cp_solver, prepared)

        x, y = (0, 0), (1, 0)
        board = make_board(
            {x: CellVisualType.HIDDEN, y: CellVisualType.HIDDEN},
            [("A", [x, y], ClueType.COUNT, 1)],
        )

        moves = DiversityTimeoutSolver().solve(board)

        self.assertEqual([], moves)

    def test_global_worker_count_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要 1 个工作线程"):
            HexReasoningSolver(feasibility_workers=0)

    def test_global_uniqueness_runs_only_after_every_local_tier_is_empty(self) -> None:
        class GlobalTrackingSolver(HexReasoningSolver):
            def __init__(self) -> None:
                self.finished_local_tiers: list[str] = []
                self.global_calls = 0

            def _apply_simple_count_rule(self, board, spec, moves):  # type: ignore[no-untyped-def]
                super()._apply_simple_count_rule(board, spec, moves)
                self.finished_local_tiers.append("局部计数")

            def _apply_pattern_rule(self, board, spec, moves):  # type: ignore[no-untyped-def]
                super()._apply_pattern_rule(board, spec, moves)
                self.finished_local_tiers.append("排列")

            def _apply_subset_rule(self, board, constraints, moves):  # type: ignore[no-untyped-def]
                super()._apply_subset_rule(board, constraints, moves)
                self.finished_local_tiers.append("子集")

            def _apply_remaining_rule(self, board, moves):  # type: ignore[no-untyped-def]
                super()._apply_remaining_rule(board, moves)
                self.finished_local_tiers.append("剩余")

            def _collect_global_forced_moves(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                self.global_calls += 1
                return super()._collect_global_forced_moves(*args, **kwargs)

        x, y, z, w = (0, 0), (1, 0), (0, 1), (1, 1)
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in (x, y, z, w)},
            [
                ("A", [x, y], ClueType.COUNT, 1),
                ("B", [y, z], ClueType.COUNT, 1),
                ("C", [x, z, w], ClueType.COUNT, 2),
            ],
        )
        solver = GlobalTrackingSolver()

        move = solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual("全局求解", move.source)
        self.assertEqual(1, solver.global_calls)
        self.assertIn("局部计数", solver.finished_local_tiers)
        self.assertIn("排列", solver.finished_local_tiers)
        self.assertEqual(["子集", "剩余"], solver.finished_local_tiers[-2:])

    def test_global_forced_black_explains_blue_assumption_is_impossible(self) -> None:
        x, y, z, w = (0, 0), (1, 0), (0, 1), (1, 1)
        board = make_board(
            {coord: CellVisualType.HIDDEN for coord in (x, y, z, w)},
            [
                ("A", [x, y], ClueType.COUNT, 1),
                ("B", [y, z], ClueType.COUNT, 1),
                ("C", [x, z, w], ClueType.COUNT, 1),
            ],
        )

        move = self.solver.next_step(board)

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual(x, move.coord)
        self.assertIs(move.action, MoveAction.MARK_BLACK)
        self.assertIn("先假设 格子 (0, 0) 是蓝色", move.reason)
        self.assertIn("格子 (0, 0) 必须标记排除", move.reason)
        self.assertIn("目标格只能是黑色", move.reason)


if __name__ == "__main__":
    unittest.main()
