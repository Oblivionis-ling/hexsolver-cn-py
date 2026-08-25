from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Optional

from .models import Board, CellVisualType, ClueType, Coord
from .session import BoardStateError, StateChange


class SimulationSession:
    """Isolated hypothesis branch that never receives private reveal data."""

    EDITABLE_STATES = {
        CellVisualType.HIDDEN,
        CellVisualType.BLUE,
        CellVisualType.BLACK,
    }

    def __init__(self, board: Board) -> None:
        self.initial_board = deepcopy(board)
        self.board = deepcopy(board)
        self._editable_coords = {
            cell.coord
            for cell in self.initial_board.cells.values()
            if cell.visual_type is CellVisualType.HIDDEN
            and cell.clue_type is ClueType.NONE
        }
        self.history: List[StateChange] = []
        self.redo_history: List[StateChange] = []

    @property
    def changed_coords(self) -> tuple[Coord, ...]:
        return tuple(
            sorted(
                (
                    coord
                    for coord in self._editable_coords
                    if self.board.cells[coord].visual_type
                    is not self.initial_board.cells[coord].visual_type
                ),
                key=lambda coord: (coord[1], coord[0]),
            )
        )

    def assumed_states(self) -> Dict[Coord, CellVisualType]:
        return {
            coord: self.board.cells[coord].visual_type
            for coord in self.changed_coords
            if self.board.cells[coord].visual_type
            in {CellVisualType.BLUE, CellVisualType.BLACK}
        }

    def set_cell_state(self, coord: Coord, state: CellVisualType) -> StateChange:
        if state not in self.EDITABLE_STATES:
            raise BoardStateError("模拟状态只能设为未知、蓝色或排除。")
        cell = self.board.get_cell(coord)
        if cell is None or coord not in self._editable_coords:
            raise BoardStateError(f"格子 {coord} 属于推演起始局面，已被固定。")
        change = StateChange(
            coord=coord,
            before=cell.visual_type,
            after=state,
            before_clue_text=cell.clue_text,
            before_clue_type=cell.clue_type,
            before_clue_number=cell.clue_number,
        )
        if change.before is change.after:
            return change
        self._update_remaining(change.before, change.after)
        cell.visual_type = state
        # Simulation marks are hypotheses, never openings.  They deliberately
        # carry no clue metadata even when the real generated answer has one.
        cell.clue_text = ""
        cell.clue_type = ClueType.NONE
        cell.clue_number = None
        self.history.append(change)
        self.redo_history.clear()
        return change

    def undo(self) -> Optional[StateChange]:
        if not self.history:
            return None
        change = self.history.pop()
        self._apply_change(change, forward=False, operation="撤销模拟")
        self.redo_history.append(change)
        return change

    def redo(self) -> Optional[StateChange]:
        if not self.redo_history:
            return None
        change = self.redo_history.pop()
        self._apply_change(change, forward=True, operation="重做模拟")
        self.history.append(change)
        return change

    def reset(self) -> None:
        self.board = deepcopy(self.initial_board)
        self.history.clear()
        self.redo_history.clear()

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
                f"{operation}时格子 {change.coord} 的状态与模拟记录不一致。"
            )
        self._update_remaining(expected, target)
        cell.visual_type = target
        if forward:
            cell.clue_text = change.after_clue_text
            cell.clue_type = change.after_clue_type
            cell.clue_number = change.after_clue_number
        else:
            cell.clue_text = change.before_clue_text
            cell.clue_type = change.before_clue_type
            cell.clue_number = change.before_clue_number

    def _update_remaining(
        self,
        before: CellVisualType,
        after: CellVisualType,
    ) -> None:
        if self.board.remaining_blue is None:
            return
        if before is CellVisualType.BLUE and after is not CellVisualType.BLUE:
            self.board.remaining_blue += 1
        elif before is not CellVisualType.BLUE and after is CellVisualType.BLUE:
            # Unlike the real session, simulation permits an impossible mark
            # so the public constraint checker can display the contradiction.
            self.board.remaining_blue -= 1
