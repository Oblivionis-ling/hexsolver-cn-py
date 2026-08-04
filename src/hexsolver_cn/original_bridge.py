from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .models import Board, Cell, CellReveal, CellVisualType, ClueType, Coord, LineFamily, RowClue
from .seed_workflow import (
    GAME_ASSEMBLY_SHA256,
    Difficulty,
    GeneratedPuzzle,
    GeneratorFidelity,
    SeedGenerationUnavailable,
    SeedRequest,
)


RawCoord = tuple[int, int]
ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
_CLUE_NUMBER_RE = re.compile(r"\d+")
_CELL_RADIUS = 32.0


@dataclass(frozen=True)
class ExportedCell:
    raw_coord: RawCoord
    name: str
    tag: str
    layer: int
    clue_text: str


@dataclass(frozen=True)
class ExportedColumn:
    raw_coord: RawCoord
    name: str
    tag: str
    clue_text: str


@dataclass(frozen=True)
class OriginalBoardExport:
    seed: int
    cells: tuple[ExportedCell, ...]
    columns: tuple[ExportedColumn, ...]


class OriginalExportError(ValueError):
    pass


@dataclass(frozen=True)
class ExportCoordinateSystem:
    """Doubled-coordinate phase used by one generated board."""

    base_y: int

    @classmethod
    def from_cells(cls, cells: Sequence[ExportedCell]) -> "ExportCoordinateSystem":
        phases = {(cell.raw_coord[1] - cell.raw_coord[0]) & 1 for cell in cells}
        if len(phases) != 1:
            raise OriginalExportError("原版导出混用了两套六边形坐标相位。")
        phase = phases.pop()
        return cls(base_y=15 if phase else 14)

    def to_axial(self, raw: RawCoord) -> Coord:
        x, y = raw
        q = x - 16
        numerator = y - self.base_y - q
        if numerator % 2:
            raise OriginalExportError(f"原游戏坐标 {raw} 不属于当前六边形网格相位。")
        return q, numerator // 2


def _parse_int(value: str, *, field: str, line_number: int) -> int:
    try:
        return int(value, 10)
    except ValueError as exc:
        raise OriginalExportError(f"第 {line_number} 行的 {field} 不是整数：{value!r}") from exc


def parse_original_export(text: str) -> OriginalBoardExport:
    """Parse the narrow TSV contract emitted by the isolated game copy."""

    rows = [line.rstrip("\r").split("\t") for line in text.lstrip("\ufeff").splitlines() if line]
    if not rows or rows[0] != ["HEXINFINITE_EXPORT", "1"]:
        raise OriginalExportError("原版生成器导出头无效或版本不受支持。")

    seed: int | None = None
    cells: list[ExportedCell] = []
    columns: list[ExportedColumn] = []
    seen_cells: set[RawCoord] = set()
    for line_number, row in enumerate(rows[1:], start=2):
        if row[0] == "SEED":
            if len(row) != 2 or seed is not None:
                raise OriginalExportError(f"第 {line_number} 行的 SEED 记录无效。")
            seed = _parse_int(row[1], field="种子", line_number=line_number)
            continue
        if row[0] == "CELL":
            if len(row) != 7:
                raise OriginalExportError(f"第 {line_number} 行的 CELL 字段数应为 7。")
            raw = (
                _parse_int(row[1], field="CELL.x", line_number=line_number),
                _parse_int(row[2], field="CELL.y", line_number=line_number),
            )
            if raw in seen_cells:
                raise OriginalExportError(f"第 {line_number} 行出现重复格子坐标 {raw}。")
            seen_cells.add(raw)
            cells.append(
                ExportedCell(
                    raw_coord=raw,
                    name=row[3],
                    tag=row[4],
                    layer=_parse_int(row[5], field="CELL.layer", line_number=line_number),
                    clue_text=row[6],
                )
            )
            continue
        if row[0] == "COLUMN":
            if len(row) != 6:
                raise OriginalExportError(f"第 {line_number} 行的 COLUMN 字段数应为 6。")
            columns.append(
                ExportedColumn(
                    raw_coord=(
                        _parse_int(row[1], field="COLUMN.x", line_number=line_number),
                        _parse_int(row[2], field="COLUMN.y", line_number=line_number),
                    ),
                    name=row[3],
                    tag=row[4],
                    clue_text=row[5],
                )
            )
            continue
        raise OriginalExportError(f"第 {line_number} 行包含未知记录类型 {row[0]!r}。")

    if seed is None:
        raise OriginalExportError("原版生成器导出中缺少 SEED。")
    if not cells:
        raise OriginalExportError("原版生成器导出中没有格子。")
    return OriginalBoardExport(seed=seed, cells=tuple(cells), columns=tuple(columns))


def _clue_number(text: str) -> int | None:
    match = _CLUE_NUMBER_RE.search(text)
    return int(match.group(0), 10) if match else None


def _clue_type(tag: str, text: str) -> ClueType:
    if _clue_number(text) is None:
        return ClueType.NONE
    normalized = tag.casefold()
    if "not sequential" in normalized:
        return ClueType.NONCONSECUTIVE
    if "sequential" in normalized:
        return ClueType.CONSECUTIVE
    return ClueType.COUNT


def _center(coord: Coord) -> tuple[float, float]:
    q, r = coord
    return (
        1.5 * _CELL_RADIUS * q,
        # Unity world-space Y grows upward, while Qt scene-space Y grows
        # downward.  Negate it here so the board has the same top/bottom
        # orientation as the official game instead of a vertical mirror.
        -math.sqrt(3.0) * _CELL_RADIUS * (r + q / 2.0),
    )


_COLUMN_SPECS: Mapping[str, tuple[RawCoord, LineFamily]] = {
    "Column Number": ((0, -2), LineFamily.HORIZONTAL),
    # The original names describe the diagonal label before Unity world Y is
    # reflected into Qt scene Y.  Reflection swaps the two visible diagonal
    # families, but the ray directions that select constrained cells stay in
    # the original doubled-coordinate system.
    "Column Number Diagonal Right": ((1, -1), LineFamily.DOWN_LEFT),
    "Column Number Diagonal Left": ((-1, -1), LineFamily.DOWN_RIGHT),
}


def _coords_on_ray(
    start: RawCoord,
    direction: RawCoord,
    raw_cells: set[RawCoord],
    coordinate_system: ExportCoordinateSystem,
) -> list[Coord]:
    coords: list[Coord] = []
    x, y = start
    dx, dy = direction
    for distance in range(1, 65):
        raw = (x + dx * distance, y + dy * distance)
        if raw in raw_cells:
            coords.append(coordinate_system.to_axial(raw))
    return coords


def board_from_original_export(
    export: OriginalBoardExport,
    difficulty: Difficulty = Difficulty.HARD,
) -> tuple[Board, Mapping[Coord, CellVisualType]]:
    """Convert final original-game objects into a public board and private answer."""

    cells: dict[Coord, Cell] = {}
    private_answer: dict[Coord, CellVisualType] = {}
    coordinate_system = ExportCoordinateSystem.from_cells(export.cells)
    for cell_id, exported in enumerate(export.cells, start=1):
        coord = coordinate_system.to_axial(exported.raw_coord)
        answer = CellVisualType.BLUE if exported.name.startswith("Blue") else CellVisualType.BLACK
        private_answer[coord] = answer

        is_public = exported.layer == 8
        visual = answer if is_public else CellVisualType.HIDDEN
        clue_text = exported.clue_text if is_public else ""
        clue_type = _clue_type(exported.tag, clue_text) if is_public else ClueType.NONE
        if is_public and clue_type is ClueType.NONE:
            # Easy can reveal blank black cells ("?") and plain blue cells as
            # fixed starting information.  UNKNOWN keeps them non-editable
            # without inventing a numerical constraint.
            clue_type = ClueType.UNKNOWN
        cells[coord] = Cell(
            cell_id=cell_id,
            coord=coord,
            center=_center(coord),
            visual_type=visual,
            clue_text=clue_text,
            clue_type=clue_type,
            clue_number=_clue_number(clue_text),
        )

    raw_cells = {cell.raw_coord for cell in export.cells}
    row_clues: list[RowClue] = []
    for index, column in enumerate(export.columns, start=1):
        try:
            direction, family = _COLUMN_SPECS[column.name]
        except KeyError as exc:
            raise OriginalExportError(f"未知的原版行线索类型：{column.name!r}") from exc
        coords = _coords_on_ray(column.raw_coord, direction, raw_cells, coordinate_system)
        if not coords:
            raise OriginalExportError(f"行线索 {column.raw_coord} 没有指向任何格子。")
        anchor_coord = coordinate_system.to_axial(column.raw_coord)
        clue_number = _clue_number(column.clue_text)
        if clue_number is None:
            raise OriginalExportError(f"行线索 {column.raw_coord} 缺少数字：{column.clue_text!r}")
        row_clues.append(
            RowClue(
                line_id=f"R{index}",
                family=family,
                line_key=index,
                coords=coords,
                anchor=_center(anchor_coord),
                clue_text=column.clue_text,
                clue_type=_clue_type(column.tag, column.clue_text),
                clue_number=clue_number,
            )
        )

    remaining_blue = sum(
        private_answer[cell.coord] is CellVisualType.BLUE
        for cell in cells.values()
        if cell.visual_type is CellVisualType.HIDDEN
    )
    board = Board(
        image_path="",
        image_size=(1100, 900),
        cells=cells,
        row_clues=row_clues,
        origin=_center((0, 0)),
        basis_a=(1.5 * _CELL_RADIUS, -math.sqrt(3.0) * _CELL_RADIUS / 2.0),
        basis_b=(0.0, -math.sqrt(3.0) * _CELL_RADIUS),
        ring_threshold=_CELL_RADIUS * 0.55,
        logs=[
            f"{difficulty.label} 种子 {export.seed:08d} 由隔离副本中的原版生成器与内置求解器生成。",
            f"导入 {len(cells)} 个最终格子和 {len(row_clues)} 条行线索。",
        ],
        remaining_blue=remaining_blue,
    )
    return board, private_answer


def private_reveals_from_original_export(
    export: OriginalBoardExport,
) -> Mapping[Coord, CellReveal]:
    reveals: dict[Coord, CellReveal] = {}
    coordinate_system = ExportCoordinateSystem.from_cells(export.cells)
    for exported in export.cells:
        coord = coordinate_system.to_axial(exported.raw_coord)
        visual = CellVisualType.BLUE if exported.name.startswith("Blue") else CellVisualType.BLACK
        clue_type = _clue_type(exported.tag, exported.clue_text)
        if exported.clue_text and clue_type is ClueType.NONE:
            clue_type = ClueType.UNKNOWN
        reveals[coord] = CellReveal(
            visual_type=visual,
            clue_text=exported.clue_text,
            clue_type=clue_type,
            clue_number=_clue_number(exported.clue_text),
        )
    return reveals


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class OriginalGameBridgeRunner:
    """Run only the patched, isolated game copy and return its final TSV export."""

    def __init__(
        self,
        game_dir: Path,
        *,
        timeout_seconds: float = 45.0,
        process_runner: ProcessRunner = subprocess.run,
    ) -> None:
        self.game_dir = Path(game_dir).resolve()
        self.timeout_seconds = timeout_seconds
        self._process_runner = process_runner

    @classmethod
    def discover(cls) -> "OriginalGameBridgeRunner":
        workspace_root = Path(__file__).resolve().parents[3]
        return cls(workspace_root / "reverse_harness" / "game")

    @property
    def executable(self) -> Path:
        return self.game_dir / "Hexcells Infinite.exe"

    @property
    def managed_dir(self) -> Path:
        return self.game_dir / "Hexcells Infinite_Data" / "Managed"

    def validate(self) -> None:
        required = (
            self.executable,
            self.managed_dir / "Assembly-CSharp.dll",
            self.managed_dir / "Assembly-CSharp.dll.orig",
            self.managed_dir / "RandomTraceHelper.dll",
            self.game_dir / "steam_appid.txt",
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise SeedGenerationUnavailable("原版隔离桥接缺少文件：" + "；".join(missing))
        original_hash = _sha256(self.managed_dir / "Assembly-CSharp.dll.orig")
        if original_hash != GAME_ASSEMBLY_SHA256:
            raise SeedGenerationUnavailable(
                "隔离副本的原始 Assembly-CSharp.dll 版本不匹配，拒绝生成可能不一致的地图。"
            )

    def generate_tsv(self, seed: int, difficulty: Difficulty = Difficulty.HARD) -> str:
        self.validate()
        with tempfile.TemporaryDirectory(prefix="hexinfinite_bridge_") as temp_dir:
            temp_root = Path(temp_dir)
            export_path = temp_root / f"hard_{seed:08d}.tsv"
            log_path = temp_root / "unity.log"
            env = os.environ.copy()
            env.update(
                {
                    "HEXINFINITE_AUTOGEN": "1",
                    "HEXINFINITE_DIFFICULTY": difficulty.value,
                    "HEXINFINITE_SEED": str(seed),
                    "HEXINFINITE_EXPORT_PATH": str(export_path),
                }
            )
            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                completed = self._process_runner(
                    [
                        str(self.executable),
                        "-batchmode",
                        "-screen-width",
                        "640",
                        "-screen-height",
                        "480",
                        "-logFile",
                        str(log_path),
                    ],
                    cwd=str(self.game_dir),
                    env=env,
                    timeout=self.timeout_seconds,
                    check=False,
                    text=True,
                    capture_output=True,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
            except subprocess.TimeoutExpired as exc:
                raise SeedGenerationUnavailable(
                    f"原版生成器在 {self.timeout_seconds:g} 秒内没有完成，请重试。"
                ) from exc
            except OSError as exc:
                raise SeedGenerationUnavailable(f"无法启动原版隔离副本：{exc}") from exc

            if completed.returncode != 0:
                tail = ""
                if log_path.is_file():
                    tail = " ".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-4:])
                raise SeedGenerationUnavailable(
                    f"原版生成器异常退出（代码 {completed.returncode}）。{tail}".strip()
                )
            if not export_path.is_file():
                raise SeedGenerationUnavailable("原版生成器已退出，但没有产生地图导出文件。")
            return export_path.read_text(encoding="utf-8-sig")


class OriginalRuntimeHardBackend:
    backend_id = "original-runtime-hard-v1"
    difficulty = Difficulty.HARD
    fidelity = GeneratorFidelity.ORIGINAL_RUNTIME

    def __init__(self, runner: OriginalGameBridgeRunner | None = None) -> None:
        self.runner = runner or OriginalGameBridgeRunner.discover()

    def generate(self, request: SeedRequest) -> GeneratedPuzzle:
        if request.difficulty is not Difficulty.HARD:
            raise ValueError("原版 Hard 桥接后端只能处理 Hard 请求。")
        export = parse_original_export(self.runner.generate_tsv(request.seed, request.difficulty))
        if export.seed != request.seed:
            raise OriginalExportError(
                f"原版返回了种子 {export.seed:08d}，与请求的 {request.seed:08d} 不一致。"
            )
        board, private_answer = board_from_original_export(export, request.difficulty)
        private_reveals = private_reveals_from_original_export(export)
        return GeneratedPuzzle(
            request=request,
            public_board=board,
            private_answer=private_answer,
            private_reveals=private_reveals,
            backend_id=self.backend_id,
            fidelity=self.fidelity,
        )


class OriginalRuntimeEasyBackend:
    backend_id = "original-runtime-easy-v1"
    difficulty = Difficulty.EASY
    fidelity = GeneratorFidelity.ORIGINAL_RUNTIME

    def __init__(self, runner: OriginalGameBridgeRunner | None = None) -> None:
        self.runner = runner or OriginalGameBridgeRunner.discover()

    def generate(self, request: SeedRequest) -> GeneratedPuzzle:
        if request.difficulty is not Difficulty.EASY:
            raise ValueError("原版 Easy 桥接后端只能处理 Easy 请求。")
        export = parse_original_export(self.runner.generate_tsv(request.seed, request.difficulty))
        if export.seed != request.seed:
            raise OriginalExportError(
                f"原版返回了种子 {export.seed:08d}，与请求的 {request.seed:08d} 不一致。"
            )
        board, private_answer = board_from_original_export(export, request.difficulty)
        private_reveals = private_reveals_from_original_export(export)
        return GeneratedPuzzle(
            request=request,
            public_board=board,
            private_answer=private_answer,
            private_reveals=private_reveals,
            backend_id=self.backend_id,
            fidelity=self.fidelity,
        )


def build_default_seed_registry():
    from .hard_offline import OfflineHardBackend
    from .managed_easy import HeadlessEasyBackend
    from .seed_workflow import SeedGeneratorRegistry

    registry = SeedGeneratorRegistry()
    registry.register(HeadlessEasyBackend())
    registry.register(OfflineHardBackend())
    return registry
