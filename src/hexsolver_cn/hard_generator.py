from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Tuple

from .models import CellVisualType, Coord
from .unity_random import UnityRandom, float32, unity_floor_to_int, unity_round_to_int


RawCoord = Tuple[int, int]


class HardShape(str, Enum):
    HEX = "hex"
    DIAMOND = "diamond"
    COLUMNAR = "columnar"
    TRIANGLE = "triangle"
    HOURGLASS = "hourglass"


@dataclass(frozen=True)
class HardLayout:
    seed: int
    shape: HardShape
    chance_black: float
    chance_blue: float
    target_count: int
    raw_cells: Tuple[Tuple[RawCoord, CellVisualType], ...]

    @property
    def answer(self) -> Mapping[Coord, CellVisualType]:
        return {raw_to_axial(raw): visual for raw, visual in self.raw_cells}


def raw_to_axial(raw: RawCoord) -> Coord:
    """Convert the game's doubled grid coordinates to ordinary axial coords."""

    x, y = raw
    q = x - 16
    numerator = y - 15 - q
    if numerator % 2:
        raise ValueError(f"原游戏坐标 {raw} 不在六边形格点上。")
    return q, numerator // 2


def axial_to_raw(coord: Coord) -> RawCoord:
    q, r = coord
    return q + 16, 15 + q + 2 * r


class HardLayoutGenerator:
    """Static Python port of Hard's shape and blue/black placement phase."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.random = UnityRandom(seed)
        self.chance_black = self.random.range_float(0.85, 0.96)
        minimum_blue = float32(self.chance_black * float32(0.07))
        maximum_blue = float32(self.chance_black * float32(0.10))
        self.chance_blue = self.random.range_float(minimum_blue, maximum_blue)
        maximum_tiles = unity_floor_to_int(float32(float32(180.0) * self.chance_black))
        self.target_count = self.random.range_int(65, maximum_tiles)
        self.shape_value = self.random.value()
        self.blue_bonus = float32(0.0)
        self.cells: List[Tuple[RawCoord, CellVisualType]] = []

    def generate(self) -> HardLayout:
        if self.shape_value <= float32(0.35):
            shape = HardShape.HEX
            self._shape_hex()
        elif self.shape_value < float32(0.65):
            shape = HardShape.DIAMOND
            self._shape_diamond()
        elif self.shape_value < float32(0.90):
            shape = HardShape.COLUMNAR
            self._shape_columnar()
        elif self.shape_value < float32(0.95):
            shape = HardShape.TRIANGLE
            self._shape_triangle()
        else:
            shape = HardShape.HOURGLASS
            self._shape_hourglass()
        return HardLayout(
            seed=self.seed,
            shape=shape,
            chance_black=self.chance_black,
            chance_blue=self.chance_blue,
            target_count=self.target_count,
            raw_cells=tuple(self.cells),
        )

    def _is_complete(self) -> bool:
        return len(self.cells) == self.target_count

    @staticmethod
    def _inside(x: int, y: int) -> bool:
        if y <= 0 or y >= 29:
            return False
        if x <= 1 or x >= 29:
            return False
        if x <= 6 and y >= 24 + x:
            return False
        if x >= 23 and y >= 24 + (29 - x):
            return False
        return True

    def _spawn(self, x: int, y: int) -> None:
        value = self.random.value()
        blue_threshold = float32(self.chance_blue + self.blue_bonus)
        if value < blue_threshold:
            self.blue_bonus = float32(0.0)
            self.cells.append(((x + 1, y), CellVisualType.BLUE))
        elif value < self.chance_black:
            self.blue_bonus = float32(self.blue_bonus + float32(0.30))
            self.cells.append(((x + 1, y), CellVisualType.BLACK))

    def _attempt(self, x: int, y: int) -> bool:
        if self._inside(x, y):
            self._spawn(x, y)
        return self._is_complete()

    def _shape_diamond(self) -> None:
        for radius in range(20):
            for x_offset in range(-2 * radius, 2 * radius + 1):
                y_offset = 2 * radius - abs(x_offset)
                if self._attempt(15 + x_offset, 15 + y_offset):
                    return
                if y_offset > 0 and self._attempt(15 + x_offset, 15 - y_offset):
                    return

    def _shape_hourglass(self) -> None:
        for radius in range(20):
            for x_offset in range(-radius, radius + 1):
                y_offset = 2 * radius - abs(x_offset)
                if self._attempt(15 + x_offset, 15 + y_offset):
                    return
                if radius and self._attempt(15 + x_offset, 15 - y_offset):
                    return

    def _shape_triangle(self) -> None:
        ratio = float32(float32(float(self.target_count)) / float32(180.0))
        height = unity_round_to_int(float32(float32(5.0) + float32(float32(5.0) * ratio)))
        for row in range(30):
            y_offset = height - row - 1
            for x_offset in range(-row, row + 1, 2):
                if self._attempt(15 + x_offset, 15 + y_offset):
                    return

    def _shape_columnar(self) -> None:
        toggle = True
        cutoff = (
            self.random.range_int(3, 9)
            if self.target_count < 100
            else self.random.range_int(1, 5)
        )
        for offset in range(15):
            for y in range(29 - cutoff, cutoff - 1, -1):
                toggle = not toggle
                if not toggle:
                    continue
                if self._inside(15 + offset, y):
                    self._spawn(15 + offset, y - 1)
                if offset:
                    self._spawn(15 - offset, y - 1)
                # The original columnar branch checks ``spawned >= target``
                # after attempting the mirrored pair.  It can therefore end
                # one tile above the sampled target.
                if len(self.cells) >= self.target_count:
                    return
            toggle = not toggle

    def _shape_hex(self) -> None:
        skip_extra_ring = False
        skip_center_column = self.random.value() < float32(0.15)
        radius = 0
        while radius < 20:
            x_offset = -radius
            while x_offset <= radius:
                if skip_center_column and x_offset == 0:
                    x_offset += 1
                vertical_radius = 2 * radius - abs(x_offset)
                y_offset = -vertical_radius
                while y_offset <= vertical_radius:
                    if self._attempt(15 + x_offset, 15 + y_offset):
                        return
                    if x_offset != -radius and x_offset != radius:
                        y_offset += vertical_radius * 2 - 2
                    y_offset += 2
                x_offset += 1
            if not skip_extra_ring and self.random.value() < float32(0.04):
                skip_extra_ring = True
                radius += 1
            radius += 1


def generate_hard_layout(seed: int) -> HardLayout:
    return HardLayoutGenerator(seed).generate()
