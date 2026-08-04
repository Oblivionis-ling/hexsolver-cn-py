from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable

from .hard_generator import HardLayoutGenerator, RawCoord
from .models import CellVisualType
from .original_bridge import (
    ExportedCell,
    ExportedColumn,
    OriginalBoardExport,
    board_from_original_export,
    private_reveals_from_original_export,
)
from .seed_workflow import Difficulty, GeneratedPuzzle, GeneratorFidelity, SeedRequest


SURROUND: tuple[RawCoord, ...] = (
    (0, 2),
    (1, 1),
    (1, -1),
    (0, -2),
    (-1, -1),
    (-1, 1),
)
FLOWER: tuple[RawCoord, ...] = SURROUND + (
    (0, 4),
    (1, 3),
    (2, 2),
    (2, 0),
    (2, -2),
    (1, -3),
    (0, -4),
    (-1, -3),
    (-2, -2),
    (-2, 0),
    (-2, 2),
    (-1, 3),
)


class _Modifier(IntEnum):
    NONE = 0
    CONSECUTIVE = 1
    NOT_CONSECUTIVE = 2


class _SetType(IntEnum):
    SURROUND = 0
    FLOWER = 1
    LINE = 2
    WHOLE_LEVEL = 3


class _CellState(IntEnum):
    ORANGE = 0
    BLUE = 1
    BLACK = 2
    HYPOTHETICAL_BLUE = 3
    HYPOTHETICAL_BLACK = 4
    EMPTY = 5


@dataclass(eq=False)
class _Tile:
    raw_coord: RawCoord
    is_blue: bool
    public: bool = False
    covered: bool = True
    flower: bool = False
    modifier: _Modifier = _Modifier.NONE
    blank: bool = False


@dataclass(eq=False)
class _Line:
    raw_coord: RawCoord
    name: str
    modifier: _Modifier = _Modifier.NONE
    attached: bool = True

    @property
    def direction(self) -> RawCoord:
        if self.name == "Column Number Diagonal Right":
            return (1, -1)
        if self.name == "Column Number Diagonal Left":
            return (-1, -1)
        return (0, -2)


@dataclass(eq=False)
class _SolverCell:
    tile: _Tile | None
    state: _CellState = _CellState.ORANGE
    solution_appearances: int = 0
    sets: list["_ConstraintSet"] = field(default_factory=list)
    sets_count: int = 0
    set_this_cell_hides: "_ConstraintSet | None" = None


@dataclass(eq=False)
class _ConstraintSet:
    set_type: _SetType
    modifier: _Modifier
    blues_in_set: int
    cells: list[_SolverCell]
    is_visible: bool = False
    permutation_complexity: int = 0
    set_is_complete: bool = False
    has_already_tested: bool = False
    hypothetical_black_indices: list[int] = field(default_factory=list)

    @property
    def cells_in_set(self) -> int:
        return len(self.cells)

    def calculate_complexity(self) -> None:
        blues_left = self.blues_in_set
        orange = 0
        for cell in reversed(self.cells):
            if cell.state is _CellState.ORANGE:
                orange += 1
            elif cell.state is _CellState.BLUE:
                blues_left -= 1
        self.permutation_complexity = min(blues_left, orange - blues_left) * orange

    def primary_solve(self, max_depth: int) -> bool:
        orange = 0
        blues_left = self.blues_in_set
        for cell in reversed(self.cells):
            if cell.state is _CellState.ORANGE:
                orange += 1
            elif cell.state is _CellState.BLUE or cell.state is _CellState.HYPOTHETICAL_BLUE:
                blues_left -= 1
        for cell in reversed(self.cells):
            cell.solution_appearances = 0

        valid_solutions = [0]
        if orange > 0 and blues_left != 0:
            self._count_valid_solutions(blues_left, valid_solutions, 0, 0, max_depth)

        changed = False
        for cell in reversed(self.cells):
            if cell.state is not _CellState.ORANGE:
                continue
            if cell.solution_appearances == 0:
                cell.state = _CellState.BLACK
            elif cell.solution_appearances == valid_solutions[0]:
                cell.state = _CellState.BLUE
            else:
                continue
            changed = True
            if cell.tile is not None:
                cell.tile.covered = False
            orange -= 1
            if cell.set_this_cell_hides is not None:
                cell.set_this_cell_hides.is_visible = True

        if orange == 0:
            for cell in reversed(self.cells):
                if self in cell.sets:
                    cell.sets.remove(self)
                    cell.sets_count -= 1
            self.set_is_complete = True
        return changed

    def _count_valid_solutions(
        self,
        blues_left: int,
        valid_solutions: list[int],
        bit_index: int,
        start: int,
        max_depth: int,
    ) -> None:
        cells = self.cells
        last = len(cells) - (blues_left - bit_index)
        for index in range(start, last + 1):
            cell = cells[index]
            if cell.state is not _CellState.ORANGE:
                continue
            cell.state = _CellState.HYPOTHETICAL_BLUE
            if bit_index < blues_left - 1:
                self._count_valid_solutions(
                    blues_left,
                    valid_solutions,
                    bit_index + 1,
                    index + 1,
                    max_depth,
                )
            else:
                valid = self.modifier is _Modifier.NONE or self._modifier_valid()
                if valid:
                    for own_cell in reversed(cells):
                        if own_cell.state is _CellState.ORANGE:
                            own_cell.state = _CellState.HYPOTHETICAL_BLACK
                        for set_index in range(own_cell.sets_count - 1, -1, -1):
                            other = own_cell.sets[set_index]
                            if other.is_visible and other is not self:
                                other.has_already_tested = False
                    for own_cell in reversed(cells):
                        if (
                            own_cell.state is not _CellState.HYPOTHETICAL_BLUE
                            and own_cell.state is not _CellState.HYPOTHETICAL_BLACK
                        ):
                            continue
                        for set_index in range(own_cell.sets_count - 1, -1, -1):
                            other = own_cell.sets[set_index]
                            if (
                                other.is_visible
                                and not other.has_already_tested
                                and other.permutation_complexity < 40
                                and not other.secondary_still_solvable(1, max_depth)
                            ):
                                valid = False
                                break
                        if not valid:
                            break
                    if valid:
                        valid_solutions[0] += 1
                        for own_cell in reversed(cells):
                            if own_cell.state is _CellState.HYPOTHETICAL_BLUE:
                                own_cell.solution_appearances += 1
                    for own_cell in reversed(cells):
                        if own_cell.state is _CellState.HYPOTHETICAL_BLACK:
                            own_cell.state = _CellState.ORANGE
            cell.state = _CellState.ORANGE

    def secondary_still_solvable(self, search_depth: int, max_depth: int) -> bool:
        self.has_already_tested = True
        blues_left = self.blues_in_set
        orange = 0
        for cell in reversed(self.cells):
            if cell.state is _CellState.ORANGE:
                orange += 1
            elif cell.state is _CellState.BLUE or cell.state is _CellState.HYPOTHETICAL_BLUE:
                blues_left -= 1
        if blues_left < 0 or blues_left > orange:
            return False
        if blues_left == 0 and orange == 0:
            return True
        return self._search_any(blues_left, 0, 0, search_depth, max_depth)

    def _search_any(
        self,
        blues_left: int,
        bit_index: int,
        start: int,
        search_depth: int,
        max_depth: int,
    ) -> bool:
        cells = self.cells
        last = len(cells) - (blues_left - bit_index)
        if blues_left == 0:
            valid = self.modifier is _Modifier.NONE or self._modifier_valid()
            if valid and search_depth < max_depth:
                self._mark_remaining_black_and_reset_neighbours()
                valid = self._neighbours_still_solvable(search_depth, max_depth)
            self._clear_hypothetical_black()
            return valid

        for index in range(start, last + 1):
            cell = cells[index]
            if cell.state is not _CellState.ORANGE:
                continue
            cell.state = _CellState.HYPOTHETICAL_BLUE
            if bit_index < blues_left - 1:
                if self._search_any(
                    blues_left,
                    bit_index + 1,
                    index + 1,
                    search_depth,
                    max_depth,
                ):
                    cell.state = _CellState.ORANGE
                    return True
            else:
                valid = self.modifier is _Modifier.NONE or self._modifier_valid()
                if valid and search_depth < max_depth:
                    self._mark_remaining_black_and_reset_neighbours()
                    valid = self._neighbours_still_solvable(search_depth, max_depth)
                self._clear_hypothetical_black()
                if valid:
                    cell.state = _CellState.ORANGE
                    return True
            cell.state = _CellState.ORANGE
        return False

    def _mark_remaining_black_and_reset_neighbours(self) -> None:
        cells = self.cells
        black_indices = self.hypothetical_black_indices
        for index in range(len(cells) - 1, -1, -1):
            cell = cells[index]
            if cell.state is _CellState.ORANGE:
                cell.state = _CellState.HYPOTHETICAL_BLACK
                black_indices.append(index)
        for cell in reversed(cells):
            for set_index in range(cell.sets_count - 1, -1, -1):
                other = cell.sets[set_index]
                if other.is_visible and other is not self:
                    other.has_already_tested = False

    def _neighbours_still_solvable(self, search_depth: int, max_depth: int) -> bool:
        for cell in reversed(self.cells):
            if (
                cell.state is not _CellState.HYPOTHETICAL_BLUE
                and cell.state is not _CellState.HYPOTHETICAL_BLACK
            ):
                continue
            for set_index in range(cell.sets_count - 1, -1, -1):
                other = cell.sets[set_index]
                if (
                    other.is_visible
                    and not other.has_already_tested
                    and other.permutation_complexity < 40
                    and not other.secondary_still_solvable(search_depth + 1, max_depth)
                ):
                    return False
        return True

    def _clear_hypothetical_black(self) -> None:
        cells = self.cells
        black_indices = self.hypothetical_black_indices
        for index in reversed(black_indices):
            cells[index].state = _CellState.ORANGE
        black_indices.clear()

    def _modifier_valid(self) -> bool:
        cells = self.cells
        cells_in_set = len(cells)
        longest = 0
        run = 0
        passes = 0
        index = cells_in_set - 1
        while index >= 0:
            state = cells[index].state
            if state is _CellState.BLUE or state is _CellState.HYPOTHETICAL_BLUE:
                run += 1
                if run > longest:
                    longest = run
            else:
                run = 0
            if index == 0 and passes == 0 and self.set_type is _SetType.SURROUND:
                index = cells_in_set
                passes += 1
            index -= 1
        if self.modifier is _Modifier.CONSECUTIVE:
            return longest == self.blues_in_set
        if self.modifier is _Modifier.NOT_CONSECUTIVE:
            return longest < self.blues_in_set
        return False


class _OriginalHardSolver:
    def __init__(self, tiles: list[_Tile], lines: list[_Line]) -> None:
        self.tiles = tiles
        self.lines = lines
        self.sets: list[_ConstraintSet] = []
        self.cells: list[_SolverCell] = []
        self._cell_by_coord: dict[RawCoord, _SolverCell] = {}

    def load(self) -> None:
        self.sets = []
        self.cells = []
        self._cell_by_coord = {}
        tile_by_coord = {tile.raw_coord: tile for tile in self.tiles}

        whole = _ConstraintSet(
            set_type=_SetType.WHOLE_LEVEL,
            modifier=_Modifier.NONE,
            blues_in_set=sum(tile.is_blue for tile in self.tiles),
            cells=[],
            is_visible=True,
        )
        for tile in self.tiles:
            state = (
                _CellState.BLUE
                if not tile.covered and tile.is_blue
                else _CellState.BLACK
                if not tile.covered
                else _CellState.ORANGE
            )
            cell = _SolverCell(tile=tile, state=state)
            cell.sets.append(whole)
            whole.cells.append(cell)
            self.cells.append(cell)
            self._cell_by_coord[tile.raw_coord] = cell
        self.sets.append(whole)

        line_at: dict[RawCoord, _Line] = {}
        for line in self.lines:
            if line.attached:
                line_at[line.raw_coord] = line

        coords = set(tile_by_coord) | set(line_at)
        if coords:
            minimum_x = min(x for x, _ in coords) - 2
            maximum_x = max(x for x, _ in coords) + 2
            minimum_y = min(y for _, y in coords) - 2
            maximum_y = max(y for _, y in coords) + 2
        else:
            minimum_x = minimum_y = 0
            maximum_x = maximum_y = 0

        for x in range(minimum_x, maximum_x + 1):
            for y in range(minimum_y, maximum_y + 1):
                raw = (x, y)
                line = line_at.get(raw)
                if line is not None:
                    members = [
                        self._cell_by_coord[coord]
                        for coord in self._ray(raw, line.direction)
                        if coord in self._cell_by_coord
                    ]
                    clue_set = _ConstraintSet(
                        set_type=_SetType.LINE,
                        modifier=line.modifier,
                        blues_in_set=sum(tile_by_coord[cell.tile.raw_coord].is_blue for cell in members if cell.tile),
                        cells=members,
                        is_visible=True,
                    )
                    self._attach_set(clue_set)
                    continue

                tile = tile_by_coord.get(raw)
                if tile is None or (tile.is_blue and not tile.flower) or tile.blank:
                    continue
                offsets = FLOWER if tile.flower else SURROUND
                members: list[_SolverCell] = []
                target = 0
                for dx, dy in offsets:
                    neighbour = (x + dx, y + dy)
                    other = tile_by_coord.get(neighbour)
                    if other is not None:
                        target += int(other.is_blue)
                        members.append(self._cell_by_coord[neighbour])
                    elif not tile.flower and tile.modifier is not _Modifier.NONE:
                        members.append(_SolverCell(tile=None, state=_CellState.EMPTY))
                clue_set = _ConstraintSet(
                    set_type=_SetType.FLOWER if tile.flower else _SetType.SURROUND,
                    modifier=tile.modifier,
                    blues_in_set=target,
                    cells=members,
                    is_visible=not tile.covered,
                )
                if tile.covered:
                    self._cell_by_coord[raw].set_this_cell_hides = clue_set
                self._attach_set(clue_set)

        for cell in self.cells:
            cell.sets_count = len(cell.sets)
        for constraint in self.sets:
            constraint.set_is_complete = constraint.cells_in_set == 0
        self.sort_by_complexity()

    def _attach_set(self, constraint: _ConstraintSet) -> None:
        for cell in constraint.cells:
            cell.sets.append(constraint)
        self.sets.append(constraint)

    @staticmethod
    def _ray(start: RawCoord, direction: RawCoord) -> Iterable[RawCoord]:
        x, y = start
        dx, dy = direction
        while y > 0:
            x += dx
            y += dy
            if -4 <= x < 40 and -4 <= y < 40:
                yield x, y

    def sort_by_complexity(self) -> None:
        for constraint in reversed(self.sets):
            constraint.calculate_complexity()
        self._mono_comparison_qsort(0, len(self.sets) - 1)

    def _mono_comparison_qsort(self, low: int, high: int) -> None:
        """Match the generic qsort used by Unity 5.6's bundled Mono runtime."""

        if low >= high:
            return
        left = low
        right = high
        pivot = self.sets[left + (right - left) // 2].permutation_complexity
        while True:
            if left < high and self.sets[left].permutation_complexity < pivot:
                left += 1
                continue
            while right > low and pivot < self.sets[right].permutation_complexity:
                right -= 1
            if left > right:
                break
            self.sets[left], self.sets[right] = self.sets[right], self.sets[left]
            left += 1
            right -= 1
        if low < right:
            self._mono_comparison_qsort(low, right)
        if left < high:
            self._mono_comparison_qsort(left, high)

    def attempt_solve(self) -> bool:
        index = 0
        while index < len(self.sets):
            constraint = self.sets[index]
            if constraint.is_visible and constraint.permutation_complexity <= 40:
                changed = constraint.primary_solve(max_depth=2)
                if constraint.set_is_complete:
                    self.sets.pop(index)
                    index -= 1
                    if not self.sets:
                        return True
                if changed:
                    self.sort_by_complexity()
                    index = -1
            index += 1
        return False

    def select_cell(self, random) -> _Tile:
        index = random.range_int(0, len(self.sets))
        while self.sets[index].permutation_complexity == 0:
            index += 1
        for cell in self.sets[index].cells:
            if cell.state is _CellState.ORANGE and cell.tile is not None:
                return cell.tile
        raise RuntimeError("原版 Hard 求解器选中的约束没有未解格。")


class OfflineHardGenerator:
    """Unity-free port of LevelGenerator plus its Solver/Set verifier."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        layout_generator = HardLayoutGenerator(seed)
        layout = layout_generator.generate()
        self.random = layout_generator.random
        self.tiles = [
            _Tile(raw_coord=raw, is_blue=visual is CellVisualType.BLUE)
            for raw, visual in layout.raw_cells
        ]
        self.lines: list[_Line] = []

    @property
    def tile_at(self) -> dict[RawCoord, _Tile]:
        return {tile.raw_coord: tile for tile in self.tiles}

    def generate_export(self) -> OriginalBoardExport:
        self._trim_simple_zeroes()
        solver = _OriginalHardSolver(self.tiles, self.lines)
        solver.load()
        attempts = 0
        while not solver.attempt_solve():
            selected = solver.select_cell(self.random)
            if not self._try_add_clue(selected):
                selected.public = True
                selected.covered = False
            solver = _OriginalHardSolver(self.tiles, self.lines)
            solver.load()
            attempts += 1
            if attempts > 500:
                raise RuntimeError("离线 Hard 生成器超过原版线索添加安全上限。")
        self._trim_unnecessary_clues()
        return self._to_export()

    def _trim_simple_zeroes(self) -> None:
        initial_blue = {tile.raw_coord for tile in self.tiles if tile.is_blue}
        zeroes = {
            tile.raw_coord
            for tile in self.tiles
            if not tile.is_blue
            and not any((tile.raw_coord[0] + dx, tile.raw_coord[1] + dy) in initial_blue for dx, dy in SURROUND)
        }
        # Unity's Transform enumerator walks the live child list.  Replacing
        # the current child appends the new blue tile and shifts the next
        # child into the current index, so MoveNext skips that shifted child.
        index = 0
        while index < len(self.tiles):
            tile = self.tiles[index]
            if not tile.is_blue and tile.raw_coord in zeroes and self.random.value() < 0.85:
                self._replace_tile(tile, _Tile(raw_coord=tile.raw_coord, is_blue=True))
            index += 1

    def _replace_tile(self, old: _Tile, new: _Tile) -> None:
        self.tiles.remove(old)
        self.tiles.append(new)

    def _try_add_clue(self, selected: _Tile) -> bool:
        if self.random.value() < 0.1:
            return False
        order = [0, 1, 2, 3]
        shuffled: list[int] = []
        for _ in range(4):
            index = self.random.range_int(0, len(order))
            shuffled.append(order.pop(index))
        for clue_kind in shuffled:
            if clue_kind == 0 and self._try_add_flower(selected):
                return True
            if clue_kind == 1 and self._try_add_surround_modifier(selected):
                return True
            if clue_kind == 2 and self._try_add_vertical_line(selected):
                return True
            if clue_kind == 3 and self._try_add_diagonal_line(selected):
                return True
        return False

    def _try_add_flower(self, selected: _Tile) -> bool:
        tiles = self.tile_at
        x, y = selected.raw_coord
        for dx, dy in FLOWER:
            candidate = tiles.get((x + dx, y + dy))
            if candidate is not None and not candidate.covered and candidate.is_blue and not candidate.flower:
                self._replace_tile(
                    candidate,
                    _Tile(
                        raw_coord=candidate.raw_coord,
                        is_blue=True,
                        public=candidate.public,
                        covered=False,
                        flower=True,
                    ),
                )
                return True
        return False

    def _try_add_surround_modifier(self, selected: _Tile) -> bool:
        tiles = self.tile_at
        x, y = selected.raw_coord
        for dx, dy in SURROUND:
            candidate = tiles.get((x + dx, y + dy))
            if (
                candidate is None
                or candidate.covered
                or candidate.is_blue
                or candidate.blank
                or candidate.modifier is not _Modifier.NONE
            ):
                continue
            total = blue_count = run = longest = 0
            cx, cy = candidate.raw_coord
            for index in range(11):
                ox, oy = SURROUND[index % 6]
                neighbour = tiles.get((cx + ox, cy + oy))
                if neighbour is not None and neighbour.is_blue:
                    if index < 6:
                        total += 1
                        blue_count += 1
                    run += 1
                    longest = max(longest, run)
                elif neighbour is not None:
                    if index < 6:
                        total += 1
                    run = 0
                else:
                    run = 0
            if 1 < blue_count < 5 and blue_count < total:
                candidate.modifier = (
                    _Modifier.CONSECUTIVE if blue_count == longest else _Modifier.NOT_CONSECUTIVE
                )
                return True
        return False

    def _line_at(self) -> dict[RawCoord, _Line]:
        result: dict[RawCoord, _Line] = {}
        for line in self.lines:
            if line.attached:
                result[line.raw_coord] = line
        return result

    def _try_add_vertical_line(self, selected: _Tile) -> bool:
        tiles = self.tile_at
        lines = self._line_at()
        x, selected_y = selected.raw_coord
        cells_seen = blues = run = longest = 0
        inside_segment = False
        y = 0
        while y <= 31:
            if y == 0 and x % 2 == 0:
                y += 1
            line = lines.get((x, y))
            if y >= selected_y and line is not None and line.modifier is _Modifier.NONE and blues > 1 and line.name == "Column Number":
                if blues == longest:
                    line.modifier = _Modifier.CONSECUTIVE
                    return True
                if longest >= blues - 2:
                    line.modifier = _Modifier.NOT_CONSECUTIVE
                    return True
            tile = tiles.get((x, y))
            if y >= selected_y and tile is None and line is None and inside_segment and cells_seen >= 2 and blues >= 1 and blues != cells_seen:
                self.lines.append(_Line((x, y), "Column Number"))
                return True
            if tile is not None:
                inside_segment = True
                cells_seen += 1
                if tile.is_blue:
                    blues += 1
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
            else:
                inside_segment = False
            y += 2
        return False

    def _try_add_diagonal_line(self, selected: _Tile) -> bool:
        if self.random.value() < 0.5:
            return self._scan_diagonal(selected, right=True)
        return self._scan_diagonal(selected, right=False)

    def _scan_diagonal(self, selected: _Tile, *, right: bool) -> bool:
        tiles = self.tile_at
        lines = self._line_at()
        sx, sy = selected.raw_coord
        cells_seen = blues = run = longest = 0
        inside_segment = False
        x, y = sx, sy
        if right:
            while x < 32 and y >= 0:
                x += 1
                y -= 1
            step_x = -1
            name = "Column Number Diagonal Right"
        else:
            while x > 0 and y >= 0:
                x -= 1
                y -= 1
            step_x = 1
            name = "Column Number Diagonal Left"

        while (x > 0 if right else x < 32) and y < 32:
            x += step_x
            y += 1
            line = lines.get((x, y))
            if y >= sy and line is not None and line.modifier is _Modifier.NONE and blues > 1 and line.name == name:
                if blues == longest:
                    line.modifier = _Modifier.CONSECUTIVE
                    return True
                if longest >= blues - 2:
                    line.modifier = _Modifier.NOT_CONSECUTIVE
                    return True
            tile = tiles.get((x, y))
            if y >= sy and tile is None and line is None and inside_segment and cells_seen >= 2 and blues >= 1 and blues != cells_seen:
                self.lines.append(_Line((x, y), name))
                return True
            if tile is not None:
                inside_segment = True
                cells_seen += 1
                if tile.is_blue:
                    blues += 1
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
            else:
                inside_segment = False
        return False

    def _is_solvable(self) -> bool:
        for tile in self.tiles:
            tile.covered = not tile.public
        solver = _OriginalHardSolver(self.tiles, self.lines)
        solver.load()
        return solver.attempt_solve()

    def _trim_unnecessary_clues(self) -> None:
        for line in list(self.lines):
            line.attached = False
            if self._is_solvable():
                self.lines.remove(line)
            else:
                line.attached = True
                self.lines.remove(line)
                self.lines.append(line)

        flowers = [tile for tile in self.tiles if tile.flower]
        for tile in flowers:
            tile.flower = False
            if self._is_solvable():
                self._replace_tile(
                    tile,
                    _Tile(
                        raw_coord=tile.raw_coord,
                        is_blue=True,
                        public=tile.public,
                        covered=not tile.public,
                    ),
                )
            else:
                tile.flower = True

        clue_tiles = [tile for tile in self.tiles if not tile.is_blue and not tile.blank]
        for tile in clue_tiles:
            old_modifier = tile.modifier
            tile.blank = True
            tile.modifier = _Modifier.NONE
            if not self._is_solvable():
                tile.blank = False
                tile.modifier = old_modifier

    def _to_export(self) -> OriginalBoardExport:
        tiles = self.tile_at
        exported_cells: list[ExportedCell] = []
        for tile in self.tiles:
            clue_text = ""
            tag = "Blue" if tile.is_blue else "Untagged"
            name = "Blue Hex" if tile.is_blue else "Black Hex"
            if tile.flower:
                name = "Blue Hex (Flower)"
                clue_text = str(self._count_blue_neighbours(tile.raw_coord, FLOWER, tiles))
            elif not tile.is_blue:
                if tile.blank:
                    tag = "Clue Hex Blank"
                    clue_text = "?"
                else:
                    count = self._count_blue_neighbours(tile.raw_coord, SURROUND, tiles)
                    tag, clue_text = self._format_modifier(tile.modifier, count, surround=True)
            exported_cells.append(
                ExportedCell(
                    raw_coord=tile.raw_coord,
                    name=name,
                    tag=tag,
                    layer=8 if tile.public else 0,
                    clue_text=clue_text,
                )
            )

        exported_lines: list[ExportedColumn] = []
        for line in self.lines:
            if not line.attached:
                continue
            count = sum(tiles[coord].is_blue for coord in self._ray_for_export(line) if coord in tiles)
            tag, text = self._format_modifier(line.modifier, count, surround=False)
            exported_lines.append(
                ExportedColumn(
                    raw_coord=line.raw_coord,
                    name=line.name,
                    tag=tag,
                    clue_text=text,
                )
            )
        return OriginalBoardExport(seed=self.seed, cells=tuple(exported_cells), columns=tuple(exported_lines))

    @staticmethod
    def _count_blue_neighbours(raw: RawCoord, offsets: Iterable[RawCoord], tiles: dict[RawCoord, _Tile]) -> int:
        x, y = raw
        return sum(bool(tiles.get((x + dx, y + dy)) and tiles[(x + dx, y + dy)].is_blue) for dx, dy in offsets)

    @staticmethod
    def _format_modifier(modifier: _Modifier, count: int, *, surround: bool) -> tuple[str, str]:
        if modifier is _Modifier.CONSECUTIVE:
            return ("Clue Hex (Sequential)" if surround else "Column Sequential", f"{{{count}}}")
        if modifier is _Modifier.NOT_CONSECUTIVE:
            return ("Clue Hex (NOT Sequential)" if surround else "Column NOT Sequential", f"-{count}-")
        return ("Untagged", str(count))

    @staticmethod
    def _ray_for_export(line: _Line) -> Iterable[RawCoord]:
        x, y = line.raw_coord
        dx, dy = line.direction
        for _ in range(64):
            x += dx
            y += dy
            yield x, y


class OfflineHardBackend:
    backend_id = "offline-original-hard-v1"
    difficulty = Difficulty.HARD
    fidelity = GeneratorFidelity.PARITY_VERIFIED

    def generate(self, request: SeedRequest) -> GeneratedPuzzle:
        if request.difficulty is not Difficulty.HARD:
            raise ValueError("离线 Hard 后端只能处理 Hard 请求。")
        export = OfflineHardGenerator(request.seed).generate_export()
        board, private_answer = board_from_original_export(export, Difficulty.HARD)
        board.logs = [
            f"Hard 种子 {request.seed:08d} 由内置 LevelGenerator 与 Solver/Set 的纯 Python 移植生成。",
            f"离线导入 {len(export.cells)} 个最终格子和 {len(export.columns)} 条行线索。",
        ]
        return GeneratedPuzzle(
            request=request,
            public_board=board,
            private_answer=private_answer,
            private_reveals=private_reveals_from_original_export(export),
            backend_id=self.backend_id,
            fidelity=self.fidelity,
        )
