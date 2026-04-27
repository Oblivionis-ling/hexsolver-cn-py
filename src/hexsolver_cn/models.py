from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple


Coord = Tuple[int, int]


class CellVisualType(str, Enum):
    HIDDEN = "hidden"
    BLUE = "blue"
    BLACK = "black"
    GREY = "grey"
    OUTSIDE = "outside"


class ClueType(str, Enum):
    NONE = "none"
    COUNT = "count"
    CONSECUTIVE = "consecutive"
    NONCONSECUTIVE = "nonconsecutive"
    UNKNOWN = "unknown"


class LineFamily(str, Enum):
    HORIZONTAL = "horizontal"
    DOWN_RIGHT = "down_right"
    DOWN_LEFT = "down_left"


class MoveAction(str, Enum):
    MARK_BLUE = "mark_blue"
    MARK_BLACK = "mark_black"


@dataclass
class Cell:
    cell_id: int
    coord: Coord
    center: Tuple[float, float]
    visual_type: CellVisualType
    clue_text: str = ""
    clue_type: ClueType = ClueType.NONE
    clue_number: Optional[int] = None
    ocr_text: str = ""
    ocr_source: str = ""
    ocr_score: Optional[float] = None
    ocr_box: Optional[Tuple[float, float, float, float]] = None

    @property
    def is_playable(self) -> bool:
        return self.visual_type in {
            CellVisualType.HIDDEN,
            CellVisualType.BLUE,
            CellVisualType.BLACK,
        }

    @property
    def is_hidden(self) -> bool:
        return self.visual_type == CellVisualType.HIDDEN

    @property
    def is_known_blue(self) -> bool:
        return self.visual_type == CellVisualType.BLUE and self.clue_type == ClueType.NONE

    @property
    def is_known_black(self) -> bool:
        return self.visual_type == CellVisualType.BLACK and self.clue_type == ClueType.NONE

    @property
    def is_blue_clue(self) -> bool:
        return self.visual_type == CellVisualType.BLUE and self.clue_type != ClueType.NONE

    @property
    def is_black_clue(self) -> bool:
        return self.visual_type == CellVisualType.BLACK and self.clue_type != ClueType.NONE

    def short_name(self) -> str:
        q, r = self.coord
        return f"({q}, {r})"


@dataclass
class RowClue:
    line_id: str
    family: LineFamily
    line_key: int
    coords: List[Coord]
    anchor: Tuple[float, float]
    clue_text: str = ""
    clue_type: ClueType = ClueType.NONE
    clue_number: Optional[int] = None
    ocr_text: str = ""
    ocr_score: Optional[float] = None
    ocr_source: str = ""
    ocr_box: Optional[Tuple[float, float, float, float]] = None

    def family_label(self) -> str:
        if self.family == LineFamily.HORIZONTAL:
            return "横向"
        if self.family == LineFamily.DOWN_RIGHT:
            return "右下斜"
        return "左下斜"

    @property
    def is_confirmed(self) -> bool:
        return self.clue_type != ClueType.NONE

    def display_name(self) -> str:
        return f"{self.line_id} / {self.family_label()} / 长度 {len(self.coords)}"


@dataclass
class SuggestedMove:
    coord: Coord
    action: MoveAction
    reason: str
    source: str


@dataclass
class OCRObservation:
    text: str
    score: float
    box: Tuple[float, float, float, float]
    source: str = "rapidocr"

    @property
    def center(self) -> Tuple[float, float]:
        x0, y0, x1, y1 = self.box
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


@dataclass
class Board:
    image_path: str
    image_size: Tuple[int, int]
    cells: Dict[Coord, Cell]
    row_clues: List[RowClue]
    origin: Tuple[float, float]
    basis_a: Tuple[float, float]
    basis_b: Tuple[float, float]
    ring_threshold: float
    logs: List[str] = field(default_factory=list)
    remaining_blue: Optional[int] = None
    remaining_ocr_text: str = ""
    remaining_ocr_source: str = ""
    remaining_ocr_score: Optional[float] = None
    ocr_observations: List[OCRObservation] = field(default_factory=list)

    def playable_cells(self) -> List[Cell]:
        return [cell for cell in self.cells.values() if cell.is_playable]

    def hidden_cells(self) -> List[Cell]:
        return [cell for cell in self.cells.values() if cell.visual_type == CellVisualType.HIDDEN]

    def known_blue_cells(self) -> List[Cell]:
        return [cell for cell in self.cells.values() if cell.visual_type == CellVisualType.BLUE]

    def known_black_cells(self) -> List[Cell]:
        return [cell for cell in self.cells.values() if cell.visual_type == CellVisualType.BLACK]

    def get_cell(self, coord: Coord) -> Optional[Cell]:
        return self.cells.get(coord)

    def all_clue_cells(self) -> List[Cell]:
        return [
            cell
            for cell in self.cells.values()
            if cell.clue_type not in {ClueType.NONE}
        ]

    def describe_cell(self, coord: Coord) -> str:
        cell = self.cells[coord]
        return f"格子 {cell.short_name()}"

    def visible_cells(self) -> Iterable[Cell]:
        return self.cells.values()

    def clue_cells(self) -> List[Cell]:
        return [
            cell
            for cell in self.cells.values()
            if cell.visual_type in {CellVisualType.BLUE, CellVisualType.BLACK}
        ]

    def board_bounds(self) -> Tuple[float, float, float, float]:
        playable = self.playable_cells()
        xs = [cell.center[0] for cell in playable]
        ys = [cell.center[1] for cell in playable]
        return min(xs), min(ys), max(xs), max(ys)
