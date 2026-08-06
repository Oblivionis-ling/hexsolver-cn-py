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
    is_global_remaining: bool = False


class SolverError(RuntimeError):
    pass


class HexReasoningSolver:
    SOURCE_PRIORITY = {
        "局部必然": 0,
        "排列推理": 1,
        "子集差分": 2,
        "全局剩余": 3,
        "全局求解": 4,
    }

    def solve(self, board: Board) -> List[SuggestedMove]:
        local_moves = self._collect_local_moves(board)
        if local_moves:
            return sorted(local_moves.values(), key=self._move_sort_key)
        return sorted(self._collect_global_forced_moves(board), key=self._move_sort_key)

    def next_step(self, board: Board) -> Optional[SuggestedMove]:
        """Return one deterministic, most explainable forced move."""

        for tier_moves in self._collect_local_move_tiers(board):
            if tier_moves:
                return sorted(tier_moves.values(), key=self._move_sort_key)[0]
        global_moves = self._collect_global_forced_moves(board, limit=1)
        return global_moves[0] if global_moves else None

    def _move_sort_key(self, move: SuggestedMove) -> Tuple[int, int, int, str]:
        return (
            self.SOURCE_PRIORITY.get(move.source, 99),
            move.coord[1],
            move.coord[0],
            move.action.value,
        )

    def _collect_local_moves(self, board: Board) -> Dict[Coord, SuggestedMove]:
        moves: Dict[Coord, SuggestedMove] = {}
        constraints = self._constraint_specs(board)

        for spec in constraints:
            self._apply_simple_count_rule(board, spec, moves)
            self._apply_pattern_rule(board, spec, moves)

        self._apply_subset_rule(board, constraints, moves)
        self._apply_remaining_rule(board, moves)
        return moves

    def _collect_local_move_tiers(
        self,
        board: Board,
    ) -> Iterable[Dict[Coord, SuggestedMove]]:
        """Yield local deductions from simplest to most expensive.

        ``next_step`` stops at the first non-empty tier, so a global
        uniqueness proof is attempted only after every local tier is empty.
        ``solve`` continues to use ``_collect_local_moves`` so its public
        batch-candidate behavior remains unchanged.
        """

        constraints = self._constraint_specs(board)

        moves: Dict[Coord, SuggestedMove] = {}
        for spec in constraints:
            self._apply_simple_count_rule(board, spec, moves)
        yield moves

        moves = {}
        for spec in constraints:
            self._apply_pattern_rule(board, spec, moves)
        yield moves

        moves = {}
        self._apply_subset_rule(board, constraints, moves)
        yield moves

        moves = {}
        self._apply_remaining_rule(board, moves)
        yield moves

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

    def _all_model_specs(self, board: Board) -> List[ConstraintSpec]:
        specs = self._constraint_specs(board)
        if board.remaining_blue is not None:
            specs.append(
                ConstraintSpec(
                    label="顶部“剩余蓝格数”",
                    clue_type=ClueType.COUNT,
                    number=board.remaining_blue,
                    coords=[cell.coord for cell in board.hidden_cells()],
                    is_global_remaining=True,
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
                    self._simple_count_reason(board, spec, coord, MoveAction.MARK_BLACK),
                    "局部必然",
                )
        elif need == len(hidden):
            for coord in hidden:
                self._add_move(
                    moves,
                    coord,
                    MoveAction.MARK_BLUE,
                    self._simple_count_reason(board, spec, coord, MoveAction.MARK_BLUE),
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
                self._pattern_reason(board, spec, coord, action, patterns),
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
                        self._subset_reason(
                            board,
                            left,
                            right,
                            coord,
                            MoveAction.MARK_BLACK,
                        ),
                        "子集差分",
                    )
            if right_need - left_need == len(diff):
                for coord in diff:
                    self._add_move(
                        moves,
                        coord,
                        MoveAction.MARK_BLUE,
                        self._subset_reason(
                            board,
                            left,
                            right,
                            coord,
                            MoveAction.MARK_BLUE,
                        ),
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
                    self._remaining_reason(board, cell.coord, MoveAction.MARK_BLACK),
                    "全局剩余",
                )
        elif board.remaining_blue == len(hidden):
            for cell in hidden:
                self._add_move(
                    moves,
                    cell.coord,
                    MoveAction.MARK_BLUE,
                    self._remaining_reason(board, cell.coord, MoveAction.MARK_BLUE),
                    "全局剩余",
                )

    def _collect_global_forced_moves(
        self,
        board: Board,
        limit: Optional[int] = None,
    ) -> List[SuggestedMove]:
        satisfiable, _ = self._solve_model(board)
        if not satisfiable:
            raise SolverError("当前线索组合无解。请先检查 OCR 结果、行线索录入和剩余蓝格数。")

        forced_moves: List[SuggestedMove] = []
        hidden_cells = sorted(board.hidden_cells(), key=lambda cell: (cell.coord[1], cell.coord[0]))
        for cell in hidden_cells:
            can_blue = self._solve_with_assumption(board, cell.coord, True)
            can_black = self._solve_with_assumption(board, cell.coord, False)
            if can_blue and can_black:
                continue
            if can_blue:
                forced_moves.append(
                    SuggestedMove(
                        coord=cell.coord,
                        action=MoveAction.MARK_BLUE,
                        reason=self._global_reason(board, cell.coord, MoveAction.MARK_BLUE),
                        source="全局求解",
                    )
                )
            elif can_black:
                forced_moves.append(
                    SuggestedMove(
                        coord=cell.coord,
                        action=MoveAction.MARK_BLACK,
                        reason=self._global_reason(board, cell.coord, MoveAction.MARK_BLACK),
                        source="全局求解",
                    )
                )
            if limit is not None and len(forced_moves) >= limit:
                break
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

        for spec in self._all_model_specs(board):
            sequence = [self._expr_for_coord(model, board, variables, coord) for coord in spec.coords]
            self._add_constraint(model, sequence, spec.number, spec.clue_type, spec.cyclic)

        if assumption is not None and assumption[0] in variables:
            model.Add(variables[assumption[0]] == int(assumption[1]))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        solver.parameters.num_search_workers = 8
        status = solver.Solve(model)
        if status == cp_model.INFEASIBLE:
            return False, {}
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise SolverError("全局约束检查未在 5 秒内得到确定结论；本次不会把超时误判成必然步。")
        return True, {coord: solver.Value(var) for coord, var in variables.items()}

    def _solve_with_assumption(self, board: Board, coord: Coord, value: bool) -> bool:
        satisfiable, _ = self._solve_model(board, assumption=(coord, value))
        return satisfiable

    def _conflict_core(
        self,
        board: Board,
        coord: Coord,
        wrong_value: bool,
    ) -> Tuple[List[ConstraintSpec], bool]:
        """Return a sufficient (not necessarily minimum) infeasible constraint core."""

        model = cp_model.CpModel()
        variables: Dict[Coord, cp_model.IntVar] = {
            cell.coord: model.NewBoolVar(f"cell_{cell.coord[0]}_{cell.coord[1]}")
            for cell in board.hidden_cells()
        }
        specs = self._all_model_specs(board)
        spec_by_literal: Dict[int, ConstraintSpec] = {}
        for index, spec in enumerate(specs):
            active = model.NewBoolVar(f"proof_constraint_{index}")
            sequence = [self._expr_for_coord(model, board, variables, item) for item in spec.coords]
            self._add_constraint(
                model,
                sequence,
                spec.number,
                spec.clue_type,
                spec.cyclic,
                active=active,
            )
            model.AddAssumption(active)
            spec_by_literal[active.Index()] = spec

        target = variables.get(coord)
        if target is None:
            return specs, False
        target_assumption = model.NewBoolVar("proof_target_assumption")
        model.Add(target == int(wrong_value)).OnlyEnforceIf(target_assumption)
        model.AddAssumption(target_assumption)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        solver.parameters.num_search_workers = 8
        solver.parameters.core_minimization_level = 2
        status = solver.Solve(model)
        if status != cp_model.INFEASIBLE:
            return specs, False

        core_literals = solver.SufficientAssumptionsForInfeasibility()
        core_specs: List[ConstraintSpec] = []
        for literal in core_literals:
            literal_index = literal if literal >= 0 else -literal - 1
            spec = spec_by_literal.get(literal_index)
            if spec is not None:
                core_specs.append(spec)
        return (core_specs, True) if core_specs else (specs, False)

    def _add_constraint(
        self,
        model: cp_model.CpModel,
        sequence: List[cp_model.IntVar],
        number: int,
        clue_type: ClueType,
        cyclic: bool,
        active: Optional[cp_model.IntVar] = None,
    ) -> None:
        def add(constraint: cp_model.Constraint) -> cp_model.Constraint:
            if active is not None:
                constraint.only_enforce_if(active)
            return constraint

        if number < 0:
            add(model.AddBoolOr([]))
            return
        add(model.Add(sum(sequence) == number))
        n = len(sequence)
        if clue_type == ClueType.COUNT:
            return
        if clue_type == ClueType.CONSECUTIVE:
            if number == 0:
                return
            start_count = n if cyclic else n - number + 1
            starts = [model.NewBoolVar(f"start_{id(sequence)}_{idx}") for idx in range(max(start_count, 0))]
            if not starts:
                add(model.AddBoolOr([]))
                return
            add(model.Add(sum(starts) == 1))
            for idx, expr in enumerate(sequence):
                covering = []
                for start_index, start_var in enumerate(starts):
                    if self._covers(idx, start_index, number, n, cyclic):
                        covering.append(start_var)
                add(model.Add(expr == sum(covering)))
            return

        if clue_type == ClueType.NONCONSECUTIVE and number > 0:
            run_count = n if cyclic else max(n - number + 1, 0)
            for start in range(run_count):
                run = [sequence[idx] for idx in self._run_indices(start, number, n, cyclic)]
                add(model.Add(sum(run) <= number - 1))

    def _simple_count_reason(
        self,
        board: Board,
        spec: ConstraintSpec,
        coord: Coord,
        action: MoveAction,
    ) -> str:
        hidden, known_blue_coords = self._hidden_and_known_blue_coords(board, spec.coords)
        known_blue = len(known_blue_coords)
        need = spec.number - known_blue
        target_color = "蓝" if action is MoveAction.MARK_BLUE else "黑"
        if action is MoveAction.MARK_BLACK:
            deduction = (
                f"还需蓝格数为 0；如果 {board.describe_cell(coord)} 再取蓝，蓝格总数就会超过 {spec.number}。"
            )
        else:
            deduction = (
                f"还需 {need} 个蓝格，而未知格也正好只有 {len(hidden)} 个；少取任意一个都会无法凑到 {spec.number}。"
            )
        return "\n".join(
            (
                "推理过程：",
                f"1. 条件：{spec.label}，{self._clue_requirement(spec)}。",
                f"2. 当前：已知蓝格 {known_blue} 个 {self._format_coords(known_blue_coords)}；"
                f"未知格 {len(hidden)} 个 {self._format_coords(hidden)}。",
                f"3. 计算：还需蓝格 = 线索数 - 已知蓝格 = {spec.number} - {known_blue} = {need}。",
                f"4. 判断：{deduction}",
                f"5. 结论：{board.describe_cell(coord)} 必须判{target_color}。",
            )
        )

    def _pattern_reason(
        self,
        board: Board,
        spec: ConstraintSpec,
        coord: Coord,
        action: MoveAction,
        patterns: List[List[bool]],
    ) -> str:
        hidden, known_blue_coords = self._hidden_and_known_blue_coords(board, spec.coords)
        target_index = spec.coords.index(coord)
        blue_count = sum(1 for pattern in patterns if pattern[target_index])
        black_count = len(patterns) - blue_count
        preview = self._pattern_preview(spec, hidden, patterns)
        target_color = "蓝" if action is MoveAction.MARK_BLUE else "黑"
        return "\n".join(
            (
                "推理过程：",
                f"1. 条件：{spec.label}，{self._clue_requirement(spec)}。",
                f"2. 当前：已知蓝格 {len(known_blue_coords)} 个 {self._format_coords(known_blue_coords)}；"
                f"未知格 {len(hidden)} 个 {self._format_coords(hidden)}。",
                f"3. 枚举：保留同时满足数量与排列要求的方案后，共有 {len(patterns)} 种合法排列。{preview}",
                f"4. 核对目标：在这 {len(patterns)} 种排列中，{board.describe_cell(coord)} 为蓝 {blue_count} 次、为黑 {black_count} 次。",
                f"5. 结论：目标格在所有合法排列中都固定为{target_color}，因此必须判{target_color}。",
            )
        )

    def _subset_reason(
        self,
        board: Board,
        left: ConstraintSpec,
        right: ConstraintSpec,
        coord: Coord,
        action: MoveAction,
    ) -> str:
        left_hidden, left_blue_coords = self._hidden_and_known_blue_coords(board, left.coords)
        right_hidden, right_blue_coords = self._hidden_and_known_blue_coords(board, right.coords)
        left_need = left.number - len(left_blue_coords)
        right_need = right.number - len(right_blue_coords)
        diff = sorted(set(right_hidden) - set(left_hidden), key=lambda item: (item[1], item[0]))
        demand_diff = right_need - left_need
        target_color = "蓝" if action is MoveAction.MARK_BLUE else "黑"
        if action is MoveAction.MARK_BLACK:
            comparison = (
                f"B 与 A 的蓝格需求差 = {right_need} - {left_need} = {demand_diff}；"
                "差集不能再贡献蓝格，所以差集全部为黑。"
            )
        else:
            comparison = (
                f"B 与 A 的蓝格需求差 = {right_need} - {left_need} = {demand_diff}，"
                f"正好等于差集大小 {len(diff)}；差集每一格都必须贡献 1 个蓝格。"
            )
        return "\n".join(
            (
                "推理过程：",
                f"1. 条件 A：{left.label}。已知蓝格 {len(left_blue_coords)} 个，"
                f"所以还需 {left.number} - {len(left_blue_coords)} = {left_need} 个；"
                f"未知集合 A = {self._format_coords(left_hidden)}。",
                f"2. 条件 B：{right.label}。已知蓝格 {len(right_blue_coords)} 个，"
                f"所以还需 {right.number} - {len(right_blue_coords)} = {right_need} 个；"
                f"未知集合 B = {self._format_coords(right_hidden)}。",
                f"3. 包含关系：A 完全包含于 B；差集 B - A = {self._format_coords(diff)}，共 {len(diff)} 格。",
                f"4. 差分计算：{comparison}",
                f"5. 结论：{board.describe_cell(coord)} 位于差集中，必须判{target_color}。",
            )
        )

    def _remaining_reason(self, board: Board, coord: Coord, action: MoveAction) -> str:
        hidden = [cell.coord for cell in board.hidden_cells()]
        remaining = board.remaining_blue
        target_color = "蓝" if action is MoveAction.MARK_BLUE else "黑"
        if action is MoveAction.MARK_BLACK:
            comparison = "剩余蓝格为 0，任何未知格再取蓝都会超过全盘剩余数。"
        else:
            comparison = (
                f"剩余蓝格数 {remaining} = 未知格数 {len(hidden)}，所以每个未知格都必须贡献 1 个蓝格。"
            )
        return "\n".join(
            (
                "推理过程：",
                f"1. 全盘当前还有 {len(hidden)} 个未知格：{self._format_coords(hidden)}。",
                f"2. 顶部显示还需要 {remaining} 个蓝格。",
                f"3. 比较：{comparison}",
                f"4. 结论：{board.describe_cell(coord)} 必须判{target_color}。",
            )
        )

    def _global_reason(self, board: Board, coord: Coord, action: MoveAction) -> str:
        correct_value = action is MoveAction.MARK_BLUE
        wrong_value = not correct_value
        correct_color = "蓝" if correct_value else "黑"
        wrong_color = "蓝" if wrong_value else "黑"
        core_specs, extracted = self._conflict_core(board, coord, wrong_value)
        condition_lines = [
            f"   {index}. {self._constraint_state_text(board, spec)}"
            for index, spec in enumerate(core_specs, start=1)
        ]
        core_description = (
            "求解器从全部约束中提取出以下一组足以造成矛盾的关键条件"
            if extracted
            else "求解器使用以下完整条件集合复核矛盾"
        )
        return "\n".join(
            (
                "全局唯一性推理（反证）：",
                f"1. 目标：判断 {board.describe_cell(coord)} 的颜色；局部计数、排列和子集规则目前都不能直接确定它。",
                f"2. 错误假设：先假设该格为{wrong_color}。",
                f"3. 关键条件：{core_description}：",
                *condition_lines,
                f"4. 冲突检查：把“目标格为{wrong_color}”与上述条件同时成立作为要求时，约束模型无可行解；"
                "也就是不存在一种蓝黑分配能同时满足它们。",
                f"5. 反向验证：改为假设目标格为{correct_color}时，完整的当前约束系统至少存在一个可行解。",
                f"6. 结论：{wrong_color}的假设被排除，因此 {board.describe_cell(coord)} 必须判{correct_color}。",
                "说明：这里列出的是一组足以证明无解的冲突条件，不宣称它是唯一或数学上最小的证明。",
            )
        )

    def _constraint_state_text(self, board: Board, spec: ConstraintSpec) -> str:
        hidden, known_blue_coords = self._hidden_and_known_blue_coords(board, spec.coords)
        if spec.is_global_remaining:
            return (
                f"{spec.label}：全盘 {len(hidden)} 个未知格中必须恰有 {spec.number} 个蓝格；"
                f"未知格为 {self._format_coords(hidden)}。"
            )
        need = spec.number - len(known_blue_coords)
        return (
            f"{spec.label}：{self._clue_requirement(spec)}；当前已知蓝格 {len(known_blue_coords)} 个 "
            f"{self._format_coords(known_blue_coords)}，未知格 {len(hidden)} 个 {self._format_coords(hidden)}；"
            f"还需蓝格 = {spec.number} - {len(known_blue_coords)} = {need}。"
        )

    @staticmethod
    def _clue_requirement(spec: ConstraintSpec) -> str:
        if spec.clue_type is ClueType.COUNT:
            return f"范围内必须恰有 {spec.number} 个蓝格"
        order = "首尾相接的环形顺序" if spec.cyclic else "线性顺序"
        if spec.clue_type is ClueType.CONSECUTIVE:
            return f"必须恰有 {spec.number} 个蓝格，并且按{order}连成一段"
        return f"必须恰有 {spec.number} 个蓝格，并且按{order}不能全部连成一个连续段"

    def _pattern_preview(
        self,
        spec: ConstraintSpec,
        hidden: List[Coord],
        patterns: List[List[bool]],
        limit: int = 4,
    ) -> str:
        hidden_set = set(hidden)
        previews: List[str] = []
        for pattern in patterns[:limit]:
            blue_hidden = [
                coord
                for coord, value in zip(spec.coords, pattern)
                if coord in hidden_set and value
            ]
            previews.append(self._format_coords(blue_hidden))
        prefix = "合法排列中，未知格取蓝的坐标"
        if len(patterns) > limit:
            return f"{prefix}（前 {limit} 种）依次为：" + "；".join(previews) + "；其余略。"
        return f"{prefix}依次为：" + "；".join(previews) + "。"

    @staticmethod
    def _format_coords(coords: Iterable[Coord]) -> str:
        items = list(coords)
        if not items:
            return "[无]"
        return "[" + "、".join(f"({q}, {r})" for q, r in items) + "]"

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
        hidden, known_blue_coords = self._hidden_and_known_blue_coords(board, coords)
        return hidden, len(known_blue_coords)

    def _hidden_and_known_blue_coords(
        self,
        board: Board,
        coords: Iterable[Coord],
    ) -> Tuple[List[Coord], List[Coord]]:
        hidden: List[Coord] = []
        known_blue_coords: List[Coord] = []
        for coord in coords:
            cell = board.get_cell(coord)
            if cell is None or not cell.is_playable:
                continue
            if cell.visual_type == CellVisualType.HIDDEN:
                hidden.append(coord)
            elif cell.visual_type == CellVisualType.BLUE:
                known_blue_coords.append(coord)
        return hidden, known_blue_coords

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
        # Preserve all six positions.  A hole in the generated board counts as
        # a non-blue separator for consecutive/non-consecutive clues; removing
        # it would incorrectly join blue runs on either side of the gap.
        return [(q + dq, r + dr) for dq, dr in NEIGHBOR_DIRS]

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
