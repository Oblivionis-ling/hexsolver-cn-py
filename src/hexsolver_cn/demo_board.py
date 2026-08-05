from __future__ import annotations

import math
from typing import Dict, Iterable, List

from .models import Board, Cell, CellVisualType, ClueType, Coord, LineFamily, RowClue


RADIUS = 5
CELL_RADIUS = 32.0


def _coords_in_radius(radius: int) -> Iterable[Coord]:
    for q in range(-radius, radius + 1):
        minimum_r = max(-radius, -q - radius)
        maximum_r = min(radius, -q + radius)
        for r in range(minimum_r, maximum_r + 1):
            yield q, r


def _center(coord: Coord) -> tuple[float, float]:
    q, r = coord
    return (
        1.5 * CELL_RADIUS * q,
        math.sqrt(3.0) * CELL_RADIUS * (r + q / 2.0),
    )


def _is_blue(coord: Coord) -> bool:
    q, r = coord
    if coord in {(1, 0), (0, 1)}:
        return True
    if coord in {(-1, 1), (-1, 0), (0, -1), (1, -1)}:
        return False
    return (q * 11 + r * 7 + q * r * 3) % 9 in {0, 1, 4}


def _neighbor_coords(coord: Coord) -> List[Coord]:
    q, r = coord
    return [
        (q, r - 1),
        (q + 1, r - 1),
        (q + 1, r),
        (q, r + 1),
        (q - 1, r + 1),
        (q - 1, r),
    ]


def _anchor_beyond_top_endpoint(centers: List[tuple[float, float]]) -> tuple[float, float]:
    endpoint = min(centers, key=lambda point: (point[1], point[0]))
    neighbor = min(
        (point for point in centers if point != endpoint),
        key=lambda point: (point[0] - endpoint[0]) ** 2 + (point[1] - endpoint[1]) ** 2,
    )
    dx = endpoint[0] - neighbor[0]
    dy = endpoint[1] - neighbor[1]
    length = math.hypot(dx, dy)
    offset = CELL_RADIUS * 1.7
    return endpoint[0] + dx / length * offset, endpoint[1] + dy / length * offset


def build_demo_board() -> Board:
    """Build a coherent visual/interaction fixture while seed parity is pending."""

    coords = list(_coords_in_radius(RADIUS))
    coord_set = set(coords)
    clue_coords = {(0, 0), (3, -2), (-3, 2), (2, 2)}
    revealed_blue = {(1, 0), (0, 1), (-4, 1), (4, -3), (2, -4), (-2, 4)}

    answer_blue = {coord for coord in coords if coord not in clue_coords and _is_blue(coord)}
    cells: Dict[Coord, Cell] = {}
    for cell_id, coord in enumerate(coords, start=1):
        visual_type = CellVisualType.HIDDEN
        clue_type = ClueType.NONE
        clue_number = None
        clue_text = ""
        if coord in clue_coords:
            clue_number = sum(neighbor in answer_blue for neighbor in _neighbor_coords(coord) if neighbor in coord_set)
            clue_type = ClueType.COUNT
            clue_text = str(clue_number)
            visual_type = CellVisualType.BLACK
        elif coord in revealed_blue:
            visual_type = CellVisualType.BLUE
        cells[coord] = Cell(
            cell_id=cell_id,
            coord=coord,
            center=_center(coord),
            visual_type=visual_type,
            clue_text=clue_text,
            clue_type=clue_type,
            clue_number=clue_number,
        )

    row_clues: List[RowClue] = []
    family_specs = [
        (LineFamily.HORIZONTAL, lambda c: c[0]),
        (LineFamily.DOWN_RIGHT, lambda c: c[0] + c[1]),
        (LineFamily.DOWN_LEFT, lambda c: c[1]),
    ]
    line_id = 1
    for family, key_fn in family_specs:
        groups: Dict[int, List[Coord]] = {}
        for coord in coords:
            groups.setdefault(key_fn(coord), []).append(coord)
        for key in sorted(groups):
            line = sorted(groups[key], key=lambda c: (c[0], c[1]))
            if len(line) < 7 or key % 2:
                continue
            clue_number = sum(coord in answer_blue for coord in line)
            centers = [_center(coord) for coord in line]
            anchor = _anchor_beyond_top_endpoint(centers)
            row_clues.append(
                RowClue(
                    line_id=f"D{line_id}",
                    family=family,
                    line_key=key,
                    coords=line,
                    anchor=anchor,
                    clue_text=str(clue_number),
                    clue_type=ClueType.COUNT,
                    clue_number=clue_number,
                )
            )
            line_id += 1

    return Board(
        image_path="",
        image_size=(920, 780),
        cells=cells,
        row_clues=row_clues,
        origin=_center((0, 0)),
        basis_a=(1.5 * CELL_RADIUS, math.sqrt(3.0) * CELL_RADIUS / 2.0),
        basis_b=(0.0, math.sqrt(3.0) * CELL_RADIUS),
        ring_threshold=CELL_RADIUS * 0.55,
        logs=["界面演示盘：仅用于交互与视觉验收，不代表种子生成结果。"],
        remaining_blue=len(answer_blue) - len(revealed_blue),
    )
