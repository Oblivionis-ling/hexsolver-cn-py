from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from .models import (
    Board,
    Cell,
    CellVisualType,
    ClueType,
    Coord,
    LineFamily,
    MoveAction,
    RowClue,
    SuggestedMove,
)


NEIGHBOR_DIRS: Sequence[Coord] = (
    (0, -1),
    (1, -1),
    (1, 0),
    (0, 1),
    (-1, 1),
    (-1, 0),
)


@dataclass
class ConstraintSpec:
    label: str
    clue_type: ClueType
    number: int
    coords: List[Coord]
    cyclic: bool = False


class SolverError(RuntimeError):
    pass


class HexReasoningSolver:
    def solve(self, board: Board) -> List[SuggestedMove]:
        local_moves = self._collect_local_moves(board)
        if local_moves:
            return sorted(local_moves.values(), key=lambda move: (move.coord[1], move.coord[0], move.action.value))
        return self._collect_global_forced_moves(board)

    def _collect_local_moves(self, board: Board) -> Dict[Coord, SuggestedMove]:
        moves: Dict[Coord, SuggestedMove] = {}
        constraints = self._constraint_specs(board)

        for spec in constraints:
            self._apply_simple_count_rule(board, spec, moves)
            self._apply_pattern_rule(board, spec, moves)

        self._apply_subset_rule(board, constraints, moves)
        self._apply_remaining_rule(board, moves)
        return moves

    def _constraint_specs(self, board: Board) -> List[ConstraintSpec]:
        specs: List[ConstraintSpec] = []

        for cell in board.cells.values():
            if cell.clue_type in {ClueType.NONE, ClueType.UNKNOWN} or cell.clue_number is None:
                continue
            if cell.visual_type == CellVisualType.BLACK:
                coords = self._neighbor_coords(board, cell.coord)
                specs.append(
                    ConstraintSpec(
                        label=f"黑格 {cell.short_name()} 的提示 {cell.clue_text or cell.clue_number}",
                        clue_type=cell.clue_type,
                        number=cell.clue_number,
                        coords=coords,
                        cyclic=True,
                    )
                )
            elif cell.visual_type == CellVisualType.BLUE:
                coords = self._area_coords(board, cell.coord)
                specs.append(
                    ConstraintSpec(
                        label=f"蓝格 {cell.short_name()} 的范围提示 {cell.clue_text or cell.clue_number}",
                        clue_type=ClueType.COUNT,
                        number=cell.clue_number,
                        coords=coords,
                        cyclic=False,
                    )
                )

        for row in board.row_clues:
            if row.clue_type in {ClueType.NONE, ClueType.UNKNOWN} or row.clue_number is None:
                continue
            specs.append(
                ConstraintSpec(
                    label=f"{row.display_name()} 的提示 {row.clue_text}",
                    clue_type=row.clue_type,
                    number=row.clue_number,
                    coords=list(row.coords),
                    cyclic=False,
                )
            )

        return specs

    def _apply_simple_count_rule(
        self,
        board: Board,
        spec: ConstraintSpec,
        moves: Dict[Coord, SuggestedMove],
    ) -> None:
        hidden, known_blue = self._hidden_and_known_blue(board, spec.coords)
        need = spec.number - known_blue
        if not hidden:
            return
        if need == 0:
            for coord in hidden:
                self._add_move(
                    moves,
                    coord,
                    MoveAction.MARK_BLACK,
                    f"依据 {spec.label}：这条线索需要的蓝格已经凑满，剩余未知格都必须判黑。",
                    "局部必然",
                )
        elif need == len(hidden):
            for coord in hidden:
                self._add_move(
                    moves,
                    coord,
                    MoveAction.MARK_BLUE,
                    f"依据 {spec.label}：剩余未知格数量正好等于还需要的蓝格数量，所以它们都必须判蓝。",
                    "局部必然",
                )

    def _apply_pattern_rule(
        self,
        board: Board,
        spec: ConstraintSpec,
        moves: Dict[Coord, SuggestedMove],
    ) -> None:
        if spec.clue_type == ClueType.COUNT:
            return
        hidden = [coord for coord in spec.coords if board.get_cell(coord) and board.get_cell(coord).visual_type == CellVisualType.HIDDEN]
        if not hidden:
            return
        if len(spec.coords) > 10 and spec.clue_type == ClueType.NONCONSECUTIVE:
            return

        patterns = self._enumerate_local_patterns(board, spec)
        if not patterns:
            return
        for coord in hidden:
            idx = spec.coords.index(coord)
            values = {pattern[idx] for pattern in patterns}
            if len(values) != 1:
                continue
            action = MoveAction.MARK_BLUE if True in values else MoveAction.MARK_BLACK
            self._add_move(
                moves,
                coord,
                action,
                f"依据 {spec.label}：在这条线索的所有合法排列里，{board.describe_cell(coord)} 都只能是"
                f"{'蓝' if action == MoveAction.MARK_BLUE else '黑'}。",
                "排列推理",
            )

    def _apply_subset_rule(
        self,
        board: Board,
        constraints: List[ConstraintSpec],
        moves: Dict[Coord, SuggestedMove],
    ) -> None:
        for left, right in itertools.permutations(constraints, 2):
            left_hidden, left_blue = self._hidden_and_known_blue(board, left.coords)
            right_hidden, right_blue = self._hidden_and_known_blue(board, right.coords)
            left_need = left.number - left_blue
            right_need = right.number - right_blue
            if left_need < 0 or right_need < 0:
                continue
            left_set = set(left_hidden)
            right_set = set(right_hidden)
            if not left_set or not left_set.issubset(right_set):
                continue
            diff = sorted(right_set - left_set)
            if not diff:
                continue

            if left_need == right_need:
                for coord in diff:
                    self._add_move(
                        moves,
                        coord,
                        MoveAction.MARK_BLACK,
                        f"依据子集关系：{left.label} 的未知格完全包含在 {right.label} 里，且两者还需要的蓝格数相同，因此差集必须全黑。",
                        "子集差分",
                    )
            if right_need - left_need == len(diff):
                for coord in diff:
                    self._add_move(
                        moves,
                        coord,
                        MoveAction.MARK_BLUE,
                        f"依据子集关系：{right.label} 比 {left.label} 多出来的未知格数量，正好等于蓝格需求差，所以差集必须全蓝。",
                        "子集差分",
                    )

    def _apply_remaining_rule(self, board: Board, moves: Dict[Coord, SuggestedMove]) -> None:
        if board.remaining_blue is None:
            return
        hidden = board.hidden_cells()
        if not hidden:
            return
        if board.remaining_blue == 0:
            for cell in hidden:
                self._add_move(
                    moves,
                    cell.coord,
                    MoveAction.MARK_BLACK,
                    "依据顶部的“剩余蓝格数”：当前剩余蓝格为 0，所以所有未知格都必须判黑。",
                    "全局剩余",
                )
        elif board.remaining_blue == len(hidden):
            for cell in hidden:
                self._add_move(
                    moves,
                    cell.coord,
                    MoveAction.MARK_BLUE,
                    "依据顶部的“剩余蓝格数”：剩余未知格数量正好等于剩余蓝格数，所以全部必须判蓝。",
                    "全局剩余",
                )

    def _collect_global_forced_moves(self, board: Board) -> List[SuggestedMove]:
        satisfiable, _ = self._solve_model(board)
        if not satisfiable:
            raise SolverError("当前线索组合无解。请先检查 OCR 结果、行线索录入和剩余蓝格数。")

        forced_moves: List[SuggestedMove] = []
        for cell in board.hidden_cells():
            can_blue = self._solve_with_assumption(board, cell.coord, True)
            can_black = self._solve_with_assumption(board, cell.coord, False)
            if can_blue and can_black:
                continue
            if can_blue:
                forced_moves.append(
                    SuggestedMove(
                        coord=cell.coord,
                        action=MoveAction.MARK_BLUE,
                        reason=(
                            f"全局唯一性推理：把 {board.describe_cell(cell.coord)} 假设为黑会导致约束系统无解，"
                            "假设为蓝时仍有可行解，所以它必须判蓝。"
                        ),
                        source="全局求解",
                    )
                )
            elif can_black:
                forced_moves.append(
                    SuggestedMove(
                        coord=cell.coord,
                        action=MoveAction.MARK_BLACK,
                        reason=(
                            f"全局唯一性推理：把 {board.describe_cell(cell.coord)} 假设为蓝会导致约束系统无解，"
                            "假设为黑时仍有可行解，所以它必须判黑。"
                        ),
                        source="全局求解",
                    )
                )
        return forced_moves

    def _solve_model(
        self,
        board: Board,
        assumption: Optional[Tuple[Coord, bool]] = None,
    ) -> Tuple[bool, Dict[Coord, int]]:
        model = cp_model.CpModel()
        variables: Dict[Coord, cp_model.IntVar] = {}
        for cell in board.hidden_cells():
            variables[cell.coord] = model.NewBoolVar(f"cell_{cell.coord[0]}_{cell.coord[1]}")

        for spec in self._constraint_specs(board):
            sequence = [self._expr_for_coord(model, board, variables, coord) for coord in spec.coords]
            self._add_constraint(model, sequence, spec.number, spec.clue_type, spec.cyclic)

        if board.remaining_blue is not None:
            model.Add(sum(variables.values()) == board.remaining_blue)

        if assumption is not None and assumption[0] in variables:
            model.Add(variables[assumption[0]] == int(assumption[1]))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        solver.parameters.num_search_workers = 8
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return False, {}
        return True, {coord: solver.Value(var) for coord, var in variables.items()}

    def _solve_with_assumption(self, board: Board, coord: Coord, value: bool) -> bool:
        satisfiable, _ = self._solve_model(board, assumption=(coord, value))
        return satisfiable

    def _add_constraint(
        self,
        model: cp_model.CpModel,
        sequence: List[cp_model.IntVar],
        number: int,
        clue_type: ClueType,
        cyclic: bool,
    ) -> None:
        if number < 0:
            model.AddBoolOr([])
            return
        model.Add(sum(sequence) == number)
        n = len(sequence)
        if clue_type == ClueType.COUNT:
            return
        if clue_type == ClueType.CONSECUTIVE:
            if number == 0:
                return
            start_count = n if cyclic else n - number + 1
            starts = [model.NewBoolVar(f"start_{id(sequence)}_{idx}") for idx in range(max(start_count, 0))]
            if not starts:
                model.AddBoolOr([])
                return
            model.Add(sum(starts) == 1)
            for idx, expr in enumerate(sequence):
                covering = []
                for start_index, start_var in enumerate(starts):
                    if self._covers(idx, start_index, number, n, cyclic):
                        covering.append(start_var)
                model.Add(expr == sum(covering))
            return

        if clue_type == ClueType.NONCONSECUTIVE and number > 0:
            run_count = n if cyclic else max(n - number + 1, 0)
            for start in range(run_count):
                run = [sequence[idx] for idx in self._run_indices(start, number, n, cyclic)]
                model.Add(sum(run) <= number - 1)

    @staticmethod
    def _covers(index: int, start: int, length: int, total: int, cyclic: bool) -> bool:
        return index in HexReasoningSolver._run_indices(start, length, total, cyclic)

    @staticmethod
    def _run_indices(start: int, length: int, total: int, cyclic: bool) -> List[int]:
        indices: List[int] = []
        for offset in range(length):
            idx = start + offset
            if cyclic:
                indices.append(idx % total)
            elif idx < total:
                indices.append(idx)
        return indices

    def _expr_for_coord(
        self,
        model: cp_model.CpModel,
        board: Board,
        variables: Dict[Coord, cp_model.IntVar],
        coord: Coord,
    ) -> cp_model.IntVar:
        cell = board.get_cell(coord)
        if cell is None or not cell.is_playable:
            return model.NewConstant(0)
        if cell.visual_type == CellVisualType.HIDDEN:
            return variables[coord]
        if cell.visual_type == CellVisualType.BLUE:
            return model.NewConstant(1)
        return model.NewConstant(0)

    def _hidden_and_known_blue(self, board: Board, coords: Iterable[Coord]) -> Tuple[List[Coord], int]:
        hidden: List[Coord] = []
        known_blue = 0
        for coord in coords:
            cell = board.get_cell(coord)
            if cell is None or not cell.is_playable:
                continue
            if cell.visual_type == CellVisualType.HIDDEN:
                hidden.append(coord)
            elif cell.visual_type == CellVisualType.BLUE:
                known_blue += 1
        return hidden, known_blue

    def _enumerate_local_patterns(self, board: Board, spec: ConstraintSpec) -> List[List[bool]]:
        hidden_indices = [idx for idx, coord in enumerate(spec.coords) if board.get_cell(coord) and board.get_cell(coord).visual_type == CellVisualType.HIDDEN]
        if not hidden_indices:
            return []

        full_values: List[Optional[bool]] = []
        for coord in spec.coords:
            cell = board.get_cell(coord)
            if cell is None or not cell.is_playable:
                full_values.append(False)
            elif cell.visual_type == CellVisualType.HIDDEN:
                full_values.append(None)
            elif cell.visual_type == CellVisualType.BLUE:
                full_values.append(True)
            else:
                full_values.append(False)

        patterns: List[List[bool]] = []
        if spec.clue_type == ClueType.CONSECUTIVE:
            run_count = len(spec.coords) if spec.cyclic else max(len(spec.coords) - spec.number + 1, 0)
            for start in range(run_count):
                pattern = [False] * len(spec.coords)
                for idx in self._run_indices(start, spec.number, len(spec.coords), spec.cyclic):
                    pattern[idx] = True
                if self._pattern_matches(full_values, pattern):
                    patterns.append(pattern)
            return patterns

        for combo in itertools.product([False, True], repeat=len(hidden_indices)):
            pattern = [value if value is not None else False for value in full_values]
            for hidden_position, value in zip(hidden_indices, combo):
                pattern[hidden_position] = value
            if sum(pattern) != spec.number:
                continue
            if spec.clue_type == ClueType.NONCONSECUTIVE and self._is_single_consecutive_block(pattern, spec.cyclic):
                continue
            if self._pattern_matches(full_values, pattern):
                patterns.append(pattern)
        return patterns

    @staticmethod
    def _pattern_matches(full_values: List[Optional[bool]], pattern: List[bool]) -> bool:
        for expected, actual in zip(full_values, pattern):
            if expected is None:
                continue
            if expected != actual:
                return False
        return True

    @staticmethod
    def _is_single_consecutive_block(pattern: List[bool], cyclic: bool) -> bool:
        if not any(pattern):
            return True
        if cyclic:
            doubled = pattern + pattern
            longest = current = 0
            for value in doubled:
                if value:
                    current += 1
                    longest = max(longest, current)
                else:
                    current = 0
            return longest >= sum(pattern)

        segments = 0
        in_segment = False
        for value in pattern:
            if value and not in_segment:
                segments += 1
                in_segment = True
            elif not value:
                in_segment = False
        return segments <= 1

    def _neighbor_coords(self, board: Board, coord: Coord) -> List[Coord]:
        q, r = coord
        coords: List[Coord] = []
        for dq, dr in NEIGHBOR_DIRS:
            target = (q + dq, r + dr)
            cell = board.get_cell(target)
            if cell is not None and cell.is_playable:
                coords.append(target)
        return coords

    def _area_coords(self, board: Board, coord: Coord) -> List[Coord]:
        q, r = coord
        coords: List[Coord] = []
        for dq in range(-2, 3):
            for dr in range(-2, 3):
                if dq == 0 and dr == 0:
                    continue
                ds = -dq - dr
                if max(abs(dq), abs(dr), abs(ds)) > 2:
                    continue
                target = (q + dq, r + dr)
                cell = board.get_cell(target)
                if cell is not None and cell.is_playable:
                    coords.append(target)
        return coords

    @staticmethod
    def _add_move(
        moves: Dict[Coord, SuggestedMove],
        coord: Coord,
        action: MoveAction,
        reason: str,
        source: str,
    ) -> None:
        existing = moves.get(coord)
        if existing is not None and existing.action == action:
            return
        if existing is not None and existing.action != action:
            return
        moves[coord] = SuggestedMove(coord=coord, action=action, reason=reason, source=source)

