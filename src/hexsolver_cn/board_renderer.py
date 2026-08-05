from __future__ import annotations

import math
from typing import Dict, Tuple

from PIL import Image, ImageDraw

from .models import Board, CellVisualType, Coord, MoveAction, SuggestedMove


COLORS = {
    CellVisualType.HIDDEN: (232, 145, 43),
    CellVisualType.BLUE: (73, 174, 224),
    CellVisualType.BLACK: (49, 51, 57),
    CellVisualType.GREY: (197, 197, 190),
    CellVisualType.OUTSIDE: (22, 27, 34),
}


def render_board(
    board: Board,
    *,
    moves: Tuple[SuggestedMove, ...] = (),
    padding: int = 48,
) -> Image.Image:
    """Render a Board without depending on a game screenshot."""

    visible = [cell for cell in board.visible_cells() if cell.visual_type is not CellVisualType.OUTSIDE]
    if not visible:
        return Image.new("RGB", (640, 420), (17, 22, 29))

    xs = [cell.center[0] for cell in visible]
    ys = [cell.center[1] for cell in visible]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    radius = _estimate_radius(board)
    width = max(320, int(math.ceil(max_x - min_x + radius * 2 + padding * 2)))
    height = max(240, int(math.ceil(max_y - min_y + radius * 2 + padding * 2)))
    offset_x = padding + radius - min_x
    offset_y = padding + radius - min_y

    image = Image.new("RGB", (width, height), (17, 22, 29))
    draw = ImageDraw.Draw(image)
    centers: Dict[Coord, Tuple[float, float]] = {}
    for cell in visible:
        cx = cell.center[0] + offset_x
        cy = cell.center[1] + offset_y
        centers[cell.coord] = (cx, cy)
        polygon = _hex_points(cx, cy, radius)
        draw.polygon(polygon, fill=COLORS[cell.visual_type], outline=(242, 234, 220), width=2)
        if cell.clue_text:
            draw.text((cx, cy), cell.clue_text, anchor="mm", fill=(245, 245, 242))

    for move in moves:
        center = centers.get(move.coord)
        if center is None:
            continue
        cx, cy = center
        color = (47, 230, 193) if move.action is MoveAction.MARK_BLUE else (255, 114, 107)
        draw.ellipse(
            (cx - radius - 5, cy - radius - 5, cx + radius + 5, cy + radius + 5),
            outline=color,
            width=4,
        )
    return image


def _estimate_radius(board: Board) -> float:
    candidates = [
        math.hypot(*board.basis_a),
        math.hypot(*board.basis_b),
    ]
    spacing = min((value for value in candidates if value > 0.1), default=42.0)
    return max(8.0, spacing * 0.48)


def _hex_points(cx: float, cy: float, radius: float) -> Tuple[Tuple[float, float], ...]:
    return tuple(
        (
            cx + radius * math.cos(math.radians(60 * index)),
            cy + radius * math.sin(math.radians(60 * index)),
        )
        for index in range(6)
    )
