from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import (
    Board,
    Cell,
    CellReveal,
    CellVisualType,
    ClueType,
    Coord,
    LineFamily,
    OCRObservation,
    RowClue,
)
from .seed_workflow import GeneratedPuzzle, GeneratorFidelity, SeedRequest


CACHE_SCHEMA_VERSION = 1
CACHE_ENVIRONMENT_VARIABLE = "HEXSOLVER_CACHE_DIR"
MAX_CACHE_FILE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class SeedCacheStats:
    entry_count: int
    total_bytes: int
    directory: Path


def default_seed_cache_directory() -> Path:
    override = os.environ.get(CACHE_ENVIRONMENT_VARIABLE)
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "HexInfiniteSolver" / "seed-cache" / "v1"
    return Path.home() / "AppData" / "Local" / "HexInfiniteSolver" / "seed-cache" / "v1"


class SeedResultCache:
    """Versioned, validated cache for exact generated seed results.

    Cache failures are intentionally non-fatal: callers always retain the exact
    generator as the source of truth.
    """

    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        self.directory = (
            Path(directory).expanduser().resolve()
            if directory is not None
            else default_seed_cache_directory()
        )
        self._lock = threading.RLock()

    def get(
        self,
        request: SeedRequest,
        *,
        backend_id: str,
        fidelity: GeneratorFidelity,
    ) -> GeneratedPuzzle | None:
        with self._lock:
            return self._get_unlocked(request, backend_id=backend_id, fidelity=fidelity)

    def _get_unlocked(
        self,
        request: SeedRequest,
        *,
        backend_id: str,
        fidelity: GeneratorFidelity,
    ) -> GeneratedPuzzle | None:
        path = self._entry_path(request, backend_id=backend_id, fidelity=fidelity)
        try:
            if not path.is_file() or path.stat().st_size > MAX_CACHE_FILE_BYTES:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            puzzle = _puzzle_from_payload(payload)
            metadata = _mapping(payload, "cache document")
            if _integer(metadata.get("schema_version"), "schema_version") != CACHE_SCHEMA_VERSION:
                return None
            if puzzle.request != request:
                return None
            if puzzle.backend_id != backend_id or puzzle.fidelity is not fidelity:
                return None
            puzzle.verify_public_board_has_no_hidden_answer()
            puzzle.cache_hit = True
            return puzzle
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def put(self, puzzle: GeneratedPuzzle) -> bool:
        with self._lock:
            return self._put_unlocked(puzzle)

    def _put_unlocked(self, puzzle: GeneratedPuzzle) -> bool:
        path = self._entry_path(
            puzzle.request,
            backend_id=puzzle.backend_id,
            fidelity=puzzle.fidelity,
        )
        temporary_path: Path | None = None
        try:
            payload = _puzzle_to_payload(puzzle)
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if len(encoded) > MAX_CACHE_FILE_BYTES:
                return False
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="seed-",
                suffix=".tmp",
                dir=self.directory,
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
            return True
        except (OSError, ValueError, TypeError):
            return False
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def stats(self) -> SeedCacheStats:
        with self._lock:
            return self._stats_unlocked()

    def _stats_unlocked(self) -> SeedCacheStats:
        count = 0
        total_bytes = 0
        try:
            for path in self.directory.glob("seed-*.json"):
                try:
                    if path.is_file():
                        count += 1
                        total_bytes += path.stat().st_size
                except OSError:
                    continue
        except OSError:
            pass
        return SeedCacheStats(count, total_bytes, self.directory)

    def clear(self) -> int:
        """Delete only files owned by this cache implementation."""

        with self._lock:
            return self._clear_unlocked()

    def _clear_unlocked(self) -> int:
        removed = 0
        try:
            candidates = list(self.directory.glob("seed-*.json"))
            candidates.extend(self.directory.glob("seed-*.tmp"))
        except OSError:
            return 0
        for path in candidates:
            try:
                if path.is_file():
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    def _entry_path(
        self,
        request: SeedRequest,
        *,
        backend_id: str,
        fidelity: GeneratorFidelity,
    ) -> Path:
        identity = "|".join(
            (
                str(CACHE_SCHEMA_VERSION),
                request.game_build_id,
                request.difficulty.value,
                f"{request.seed:08d}",
                backend_id,
                fidelity.value,
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return self.directory / (
            f"seed-{request.difficulty.value}-{request.seed:08d}-{digest}.json"
        )


def _puzzle_to_payload(puzzle: GeneratedPuzzle) -> dict[str, Any]:
    puzzle.verify_public_board_has_no_hidden_answer()
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "request": {
            "seed": puzzle.request.seed,
            "difficulty": puzzle.request.difficulty.value,
            "game_build_id": puzzle.request.game_build_id,
        },
        "backend_id": puzzle.backend_id,
        "fidelity": puzzle.fidelity.value,
        "public_board": board_to_payload(puzzle.public_board),
        "private_answer": [
            {"coord": list(coord), "visual_type": visual_type.value}
            for coord, visual_type in sorted(puzzle.private_answer.items())
        ],
        "private_reveals": [
            {
                "coord": list(coord),
                "visual_type": reveal.visual_type.value,
                "clue_text": reveal.clue_text,
                "clue_type": reveal.clue_type.value,
                "clue_number": reveal.clue_number,
            }
            for coord, reveal in sorted(puzzle.private_reveals.items())
        ],
    }


def _puzzle_from_payload(value: Any) -> GeneratedPuzzle:
    payload = _mapping(value, "cache document")
    request_payload = _mapping(payload.get("request"), "request")
    from .seed_workflow import Difficulty

    request = SeedRequest(
        seed=_integer(request_payload.get("seed"), "request.seed"),
        difficulty=Difficulty(
            _string(request_payload.get("difficulty"), "request.difficulty")
        ),
        game_build_id=_string(request_payload.get("game_build_id"), "request.game_build_id"),
    )
    private_answer: dict[Coord, CellVisualType] = {}
    for index, item in enumerate(_list(payload.get("private_answer"), "private_answer")):
        answer = _mapping(item, f"private_answer[{index}]")
        coord = _coord(answer.get("coord"), f"private_answer[{index}].coord")
        if coord in private_answer:
            raise ValueError("private_answer contains a duplicate coordinate")
        private_answer[coord] = CellVisualType(
            _string(answer.get("visual_type"), f"private_answer[{index}].visual_type")
        )

    private_reveals: dict[Coord, CellReveal] = {}
    for index, item in enumerate(_list(payload.get("private_reveals"), "private_reveals")):
        reveal_payload = _mapping(item, f"private_reveals[{index}]")
        coord = _coord(reveal_payload.get("coord"), f"private_reveals[{index}].coord")
        if coord in private_reveals:
            raise ValueError("private_reveals contains a duplicate coordinate")
        private_reveals[coord] = CellReveal(
            visual_type=CellVisualType(
                _string(reveal_payload.get("visual_type"), "private reveal visual_type")
            ),
            clue_text=_string(reveal_payload.get("clue_text"), "private reveal clue_text"),
            clue_type=ClueType(
                _string(reveal_payload.get("clue_type"), "private reveal clue_type")
            ),
            clue_number=_optional_integer(
                reveal_payload.get("clue_number"), "private reveal clue_number"
            ),
        )

    return GeneratedPuzzle(
        request=request,
        public_board=board_from_payload(payload.get("public_board")),
        private_answer=private_answer,
        private_reveals=private_reveals,
        backend_id=_string(payload.get("backend_id"), "backend_id"),
        fidelity=GeneratorFidelity(_string(payload.get("fidelity"), "fidelity")),
        cache_hit=True,
    )


def board_to_payload(board: Board) -> dict[str, Any]:
    return {
        "image_path": board.image_path,
        "image_size": list(board.image_size),
        "cells": [_cell_to_payload(cell) for _, cell in sorted(board.cells.items())],
        "row_clues": [_row_clue_to_payload(row) for row in board.row_clues],
        "origin": list(board.origin),
        "basis_a": list(board.basis_a),
        "basis_b": list(board.basis_b),
        "ring_threshold": board.ring_threshold,
        "logs": list(board.logs),
        "remaining_blue": board.remaining_blue,
        "remaining_ocr_text": board.remaining_ocr_text,
        "remaining_ocr_source": board.remaining_ocr_source,
        "remaining_ocr_score": board.remaining_ocr_score,
        "ocr_observations": [
            {
                "text": observation.text,
                "score": observation.score,
                "box": list(observation.box),
                "source": observation.source,
            }
            for observation in board.ocr_observations
        ],
    }


def _cell_to_payload(cell: Cell) -> dict[str, Any]:
    return {
        "cell_id": cell.cell_id,
        "coord": list(cell.coord),
        "center": list(cell.center),
        "visual_type": cell.visual_type.value,
        "clue_text": cell.clue_text,
        "clue_type": cell.clue_type.value,
        "clue_number": cell.clue_number,
        "ocr_text": cell.ocr_text,
        "ocr_source": cell.ocr_source,
        "ocr_score": cell.ocr_score,
        "ocr_box": list(cell.ocr_box) if cell.ocr_box is not None else None,
    }


def _row_clue_to_payload(row: RowClue) -> dict[str, Any]:
    return {
        "line_id": row.line_id,
        "family": row.family.value,
        "line_key": row.line_key,
        "coords": [list(coord) for coord in row.coords],
        "anchor": list(row.anchor),
        "clue_text": row.clue_text,
        "clue_type": row.clue_type.value,
        "clue_number": row.clue_number,
        "ocr_text": row.ocr_text,
        "ocr_score": row.ocr_score,
        "ocr_source": row.ocr_source,
        "ocr_box": list(row.ocr_box) if row.ocr_box is not None else None,
    }


def board_from_payload(value: Any) -> Board:
    payload = _mapping(value, "public_board")
    cells: dict[Coord, Cell] = {}
    for index, item in enumerate(_list(payload.get("cells"), "public_board.cells")):
        cell_payload = _mapping(item, f"public_board.cells[{index}]")
        coord = _coord(cell_payload.get("coord"), f"public_board.cells[{index}].coord")
        if coord in cells:
            raise ValueError("public_board.cells contains a duplicate coordinate")
        cells[coord] = Cell(
            cell_id=_integer(cell_payload.get("cell_id"), "cell.cell_id"),
            coord=coord,
            center=_float_pair(cell_payload.get("center"), "cell.center"),
            visual_type=CellVisualType(
                _string(cell_payload.get("visual_type"), "cell.visual_type")
            ),
            clue_text=_string(cell_payload.get("clue_text"), "cell.clue_text"),
            clue_type=ClueType(_string(cell_payload.get("clue_type"), "cell.clue_type")),
            clue_number=_optional_integer(cell_payload.get("clue_number"), "cell.clue_number"),
            ocr_text=_string(cell_payload.get("ocr_text"), "cell.ocr_text"),
            ocr_source=_string(cell_payload.get("ocr_source"), "cell.ocr_source"),
            ocr_score=_optional_number(cell_payload.get("ocr_score"), "cell.ocr_score"),
            ocr_box=_optional_float_quad(cell_payload.get("ocr_box"), "cell.ocr_box"),
        )

    row_clues: list[RowClue] = []
    for index, item in enumerate(_list(payload.get("row_clues"), "public_board.row_clues")):
        row = _mapping(item, f"public_board.row_clues[{index}]")
        row_clues.append(
            RowClue(
                line_id=_string(row.get("line_id"), "row.line_id"),
                family=LineFamily(_string(row.get("family"), "row.family")),
                line_key=_integer(row.get("line_key"), "row.line_key"),
                coords=[
                    _coord(coord, "row.coords item")
                    for coord in _list(row.get("coords"), "row.coords")
                ],
                anchor=_float_pair(row.get("anchor"), "row.anchor"),
                clue_text=_string(row.get("clue_text"), "row.clue_text"),
                clue_type=ClueType(_string(row.get("clue_type"), "row.clue_type")),
                clue_number=_optional_integer(row.get("clue_number"), "row.clue_number"),
                ocr_text=_string(row.get("ocr_text"), "row.ocr_text"),
                ocr_score=_optional_number(row.get("ocr_score"), "row.ocr_score"),
                ocr_source=_string(row.get("ocr_source"), "row.ocr_source"),
                ocr_box=_optional_float_quad(row.get("ocr_box"), "row.ocr_box"),
            )
        )

    observations: list[OCRObservation] = []
    for index, item in enumerate(
        _list(payload.get("ocr_observations"), "public_board.ocr_observations")
    ):
        observation = _mapping(item, f"public_board.ocr_observations[{index}]")
        observations.append(
            OCRObservation(
                text=_string(observation.get("text"), "observation.text"),
                score=_number(observation.get("score"), "observation.score"),
                box=_float_quad(observation.get("box"), "observation.box"),
                source=_string(observation.get("source"), "observation.source"),
            )
        )

    logs = _list(payload.get("logs"), "public_board.logs")
    if not all(isinstance(log, str) for log in logs):
        raise ValueError("public_board.logs must contain only strings")
    return Board(
        image_path=_string(payload.get("image_path"), "public_board.image_path"),
        image_size=_int_pair(payload.get("image_size"), "public_board.image_size"),
        cells=cells,
        row_clues=row_clues,
        origin=_float_pair(payload.get("origin"), "public_board.origin"),
        basis_a=_float_pair(payload.get("basis_a"), "public_board.basis_a"),
        basis_b=_float_pair(payload.get("basis_b"), "public_board.basis_b"),
        ring_threshold=_number(payload.get("ring_threshold"), "public_board.ring_threshold"),
        logs=list(logs),
        remaining_blue=_optional_integer(
            payload.get("remaining_blue"), "public_board.remaining_blue"
        ),
        remaining_ocr_text=_string(
            payload.get("remaining_ocr_text"), "public_board.remaining_ocr_text"
        ),
        remaining_ocr_source=_string(
            payload.get("remaining_ocr_source"), "public_board.remaining_ocr_source"
        ),
        remaining_ocr_score=_optional_number(
            payload.get("remaining_ocr_score"), "public_board.remaining_ocr_score"
        ),
        ocr_observations=observations,
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_integer(value: Any, name: str) -> int | None:
    return None if value is None else _integer(value, name)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _optional_number(value: Any, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _coord(value: Any, name: str) -> Coord:
    items = _list(value, name)
    if len(items) != 2:
        raise ValueError(f"{name} must contain two integers")
    return (_integer(items[0], name), _integer(items[1], name))


def _int_pair(value: Any, name: str) -> tuple[int, int]:
    return _coord(value, name)


def _float_pair(value: Any, name: str) -> tuple[float, float]:
    items = _list(value, name)
    if len(items) != 2:
        raise ValueError(f"{name} must contain two numbers")
    return (_number(items[0], name), _number(items[1], name))


def _float_quad(value: Any, name: str) -> tuple[float, float, float, float]:
    items = _list(value, name)
    if len(items) != 4:
        raise ValueError(f"{name} must contain four numbers")
    return tuple(_number(item, name) for item in items)  # type: ignore[return-value]


def _optional_float_quad(value: Any, name: str) -> tuple[float, float, float, float] | None:
    return None if value is None else _float_quad(value, name)
