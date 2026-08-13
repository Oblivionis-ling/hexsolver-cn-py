from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import List, Mapping, Optional

from .models import Board, CellReveal, CellVisualType, ClueType, Coord, MoveAction, SuggestedMove
from .solver import HexReasoningSolver


class BoardStateError(ValueError):
    pass


@dataclass(frozen=True)
class StateChange:
    coord: Coord
    before: CellVisualType
    after: CellVisualType
    before_clue_text: str = ""
    before_clue_type: ClueType = ClueType.NONE
    before_clue_number: Optional[int] = None
    after_clue_text: str = ""
    after_clue_type: ClueType = ClueType.NONE
    after_clue_number: Optional[int] = None


class InteractivePuzzleSession:
    """Mutable public-board session used to mirror the player's current game state."""

    EDITABLE_STATES = {
        CellVisualType.HIDDEN,
        CellVisualType.BLUE,
        CellVisualType.BLACK,
    }

    def __init__(
        self,
        board: Board,
        solver: Optional[HexReasoningSolver] = None,
        private_reveals: Optional[Mapping[Coord, CellReveal]] = None,
    ) -> None:
        self.initial_board = deepcopy(board)
        self.board = deepcopy(board)
        self.solver = solver or HexReasoningSolver()
        self.private_reveals = dict(private_reveals or {})
        self._fixed_coords = {
            cell.coord
            for cell in self.initial_board.cells.values()
            if cell.clue_type is not ClueType.NONE
        }
        self.history: List[StateChange] = []
        self.redo_history: List[StateChange] = []

    def set_cell_state(self, coord: Coord, state: CellVisualType) -> StateChange:
        if state not in self.EDITABLE_STATES:
            raise BoardStateError("手动状态只能设为未知、蓝或黑。")
        cell = self.board.get_cell(coord)
        if cell is None or not cell.is_playable:
            raise BoardStateError(f"坐标 {coord} 不是可编辑格子。")
        if coord in self._fixed_coords:
            raise BoardStateError(f"格子 {coord} 是固定线索格，不能修改颜色状态。")
        after_clue_text = ""
        after_clue_type = ClueType.NONE
        after_clue_number = None
        reveal = self.private_reveals.get(coord)
        if state is not CellVisualType.HIDDEN and reveal is not None and reveal.visual_type is state:
            after_clue_text = reveal.clue_text
            after_clue_type = reveal.clue_type
            after_clue_number = reveal.clue_number
        change = StateChange(
            coord=coord,
            before=cell.visual_type,
            after=state,
            before_clue_text=cell.clue_text,
            before_clue_type=cell.clue_type,
            before_clue_number=cell.clue_number,
            after_clue_text=after_clue_text,
            after_clue_type=after_clue_type,
            after_clue_number=after_clue_number,
        )
        if change.before is change.after:
            return change
        if self.board.remaining_blue is not None:
            next_remaining = self.board.remaining_blue
            if change.before is CellVisualType.BLUE and change.after is not CellVisualType.BLUE:
                next_remaining += 1
            elif change.before is not CellVisualType.BLUE and change.after is CellVisualType.BLUE:
                next_remaining -= 1
            if next_remaining < 0:
                raise BoardStateError("蓝格标记数量超过顶部的剩余蓝格数。")
            self.board.remaining_blue = next_remaining
        cell.visual_type = state
        cell.clue_text = change.after_clue_text
        cell.clue_type = change.after_clue_type
        cell.clue_number = change.after_clue_number
        self.history.append(change)
        self.redo_history.clear()
        return change

    def cycle_cell_state(self, coord: Coord) -> StateChange:
        cell = self.board.get_cell(coord)
        if cell is None:
            raise BoardStateError(f"坐标 {coord} 不存在。")
        order = [CellVisualType.HIDDEN, CellVisualType.BLUE, CellVisualType.BLACK]
        try:
            next_state = order[(order.index(cell.visual_type) + 1) % len(order)]
        except ValueError as exc:
            raise BoardStateError(f"格子 {coord} 当前状态不可循环。") from exc
        return self.set_cell_state(coord, next_state)

    def undo(self) -> Optional[StateChange]:
        if not self.history:
            return None
        change = self.history.pop()
        self._apply_change(change, forward=False, operation="撤销")
        self.redo_history.append(change)
        return change

    def redo(self) -> Optional[StateChange]:
        if not self.redo_history:
            return None
        change = self.redo_history.pop()
        self._apply_change(change, forward=True, operation="重做")
        self.history.append(change)
        return change

    def _apply_change(
        self,
        change: StateChange,
        *,
        forward: bool,
        operation: str,
    ) -> None:
        cell = self.board.get_cell(change.coord)
        if cell is None:
            raise BoardStateError(f"{operation}时找不到格子 {change.coord}。")
        expected = change.before if forward else change.after
        target = change.after if forward else change.before
        if cell.visual_type is not expected:
            raise BoardStateError(
                f"{operation}时格子 {change.coord} 的当前状态与操作记录不一致。"
            )
        if self.board.remaining_blue is not None:
            delta = 0
            if expected is CellVisualType.BLUE and target is not CellVisualType.BLUE:
                delta = 1
            elif expected is not CellVisualType.BLUE and target is CellVisualType.BLUE:
                delta = -1
            next_remaining = self.board.remaining_blue + delta
            if next_remaining < 0:
                raise BoardStateError(f"{operation}会使剩余蓝格数小于零。")
            self.board.remaining_blue = next_remaining
        cell.visual_type = target
        if forward:
            cell.clue_text = change.after_clue_text
            cell.clue_type = change.after_clue_type
            cell.clue_number = change.after_clue_number
        else:
            cell.clue_text = change.before_clue_text
            cell.clue_type = change.before_clue_type
            cell.clue_number = change.before_clue_number

    def reset(self) -> None:
        self.board = deepcopy(self.initial_board)
        self.history.clear()
        self.redo_history.clear()

    def next_step(self) -> Optional[SuggestedMove]:
        return self.solver.next_step(self.board)

    def apply_suggested_move(self, move: SuggestedMove) -> StateChange:
        target = CellVisualType.BLUE if move.action is MoveAction.MARK_BLUE else CellVisualType.BLACK
        return self.set_cell_state(move.coord, target)
