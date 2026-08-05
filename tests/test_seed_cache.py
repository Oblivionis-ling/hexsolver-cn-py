from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hexsolver_cn.models import (
    Board,
    Cell,
    CellReveal,
    CellVisualType,
    ClueType,
    LineFamily,
    OCRObservation,
    RowClue,
)
from hexsolver_cn.seed_cache import CACHE_SCHEMA_VERSION, SeedResultCache
from hexsolver_cn.seed_workflow import (
    Difficulty,
    GeneratedPuzzle,
    GeneratorFidelity,
    SeedGeneratorRegistry,
    SeedRequest,
)


def build_cache_board(seed: int) -> Board:
    hidden_coord = (seed % 7, 0)
    clue_coord = (hidden_coord[0] - 1, 0)
    cells = {
        clue_coord: Cell(
            cell_id=1,
            coord=clue_coord,
            center=(40.5, 60.25),
            visual_type=CellVisualType.BLACK,
            clue_text="1",
            clue_type=ClueType.COUNT,
            clue_number=1,
            ocr_text="1",
            ocr_source="fixture",
            ocr_score=0.99,
            ocr_box=(30.0, 50.0, 50.0, 70.0),
        ),
        hidden_coord: Cell(
            cell_id=2,
            coord=hidden_coord,
            center=(80.5, 60.25),
            visual_type=CellVisualType.HIDDEN,
        ),
    }
    return Board(
        image_path="",
        image_size=(160, 120),
        cells=cells,
        row_clues=[
            RowClue(
                line_id="H0",
                family=LineFamily.HORIZONTAL,
                line_key=0,
                coords=[clue_coord, hidden_coord],
                anchor=(18.0, 60.25),
                clue_text="1",
                clue_type=ClueType.COUNT,
                clue_number=1,
                ocr_text="1",
                ocr_score=0.98,
                ocr_source="fixture",
                ocr_box=(4.0, 48.0, 24.0, 70.0),
            )
        ],
        origin=(40.5, 60.25),
        basis_a=(40.0, 0.0),
        basis_b=(20.0, 34.5),
        ring_threshold=18.25,
        logs=["cache fixture"],
        remaining_blue=1,
        remaining_ocr_text="1",
        remaining_ocr_source="fixture",
        remaining_ocr_score=0.97,
        ocr_observations=[
            OCRObservation(
                text="1",
                score=0.96,
                box=(1.0, 2.0, 3.0, 4.0),
                source="fixture",
            )
        ],
    )


class CountingBackend:
    fidelity = GeneratorFidelity.PARITY_VERIFIED

    def __init__(self, difficulty: Difficulty, backend_id: str | None = None) -> None:
        self.difficulty = difficulty
        self.backend_id = backend_id or f"counting-{difficulty.value}-v1"
        self.calls = 0

    def generate(self, request: SeedRequest) -> GeneratedPuzzle:
        self.calls += 1
        board = build_cache_board(request.seed)
        hidden_coord = next(cell.coord for cell in board.hidden_cells())
        return GeneratedPuzzle(
            request=request,
            public_board=board,
            private_answer={hidden_coord: CellVisualType.BLUE},
            private_reveals={
                hidden_coord: CellReveal(
                    visual_type=CellVisualType.BLUE,
                    clue_text="2",
                    clue_type=ClueType.COUNT,
                    clue_number=2,
                )
            },
            backend_id=self.backend_id,
            fidelity=self.fidelity,
        )


class SeedResultCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.cache = SeedResultCache(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _registry(self, backend: CountingBackend) -> SeedGeneratorRegistry:
        registry = SeedGeneratorRegistry(cache=self.cache)
        registry.register(backend)
        return registry

    def test_first_generation_writes_and_second_generation_reads_cache(self) -> None:
        backend = CountingBackend(Difficulty.HARD)
        registry = self._registry(backend)
        request = SeedRequest(seed=1, difficulty=Difficulty.HARD)

        first = registry.generate(request)
        second = registry.generate(request)

        self.assertEqual(1, backend.calls)
        self.assertFalse(first.cache_hit)
        self.assertTrue(first.cache_saved)
        self.assertTrue(second.cache_hit)
        self.assertEqual(first.public_board, second.public_board)
        self.assertEqual(first.private_answer, second.private_answer)
        self.assertEqual(first.private_reveals, second.private_reveals)
        self.assertEqual(1, self.cache.stats().entry_count)

    def test_difficulty_and_seed_have_independent_cache_entries(self) -> None:
        easy = CountingBackend(Difficulty.EASY)
        hard = CountingBackend(Difficulty.HARD)
        registry = SeedGeneratorRegistry(cache=self.cache)
        registry.register(easy)
        registry.register(hard)

        registry.generate(SeedRequest(seed=1, difficulty=Difficulty.EASY))
        registry.generate(SeedRequest(seed=1, difficulty=Difficulty.HARD))
        registry.generate(SeedRequest(seed=2, difficulty=Difficulty.HARD))
        registry.generate(SeedRequest(seed=1, difficulty=Difficulty.EASY))
        registry.generate(SeedRequest(seed=2, difficulty=Difficulty.HARD))

        self.assertEqual(1, easy.calls)
        self.assertEqual(2, hard.calls)
        self.assertEqual(3, self.cache.stats().entry_count)

    def test_backend_and_game_build_changes_invalidate_cache(self) -> None:
        request = SeedRequest(seed=3, difficulty=Difficulty.HARD)
        first_backend = CountingBackend(Difficulty.HARD, "counting-hard-v1")
        self._registry(first_backend).generate(request)

        second_backend = CountingBackend(Difficulty.HARD, "counting-hard-v2")
        self._registry(second_backend).generate(request)
        self._registry(second_backend).generate(
            SeedRequest(seed=3, difficulty=Difficulty.HARD, game_build_id="new-build")
        )

        self.assertEqual(1, first_backend.calls)
        self.assertEqual(2, second_backend.calls)
        self.assertEqual(3, self.cache.stats().entry_count)

    def test_schema_mismatch_and_corrupt_json_are_ignored_and_rebuilt(self) -> None:
        backend = CountingBackend(Difficulty.HARD)
        registry = self._registry(backend)
        request = SeedRequest(seed=4, difficulty=Difficulty.HARD)
        registry.generate(request)
        entry = next(Path(self.temporary_directory.name).glob("seed-*.json"))

        payload = json.loads(entry.read_text(encoding="utf-8"))
        payload["schema_version"] = CACHE_SCHEMA_VERSION + 1
        entry.write_text(json.dumps(payload), encoding="utf-8")
        registry.generate(request)
        self.assertEqual(2, backend.calls)

        entry.write_text("{not-json", encoding="utf-8")
        registry.generate(request)
        self.assertEqual(3, backend.calls)
        self.assertTrue(json.loads(entry.read_text(encoding="utf-8")))

    def test_write_failure_does_not_block_generation(self) -> None:
        backend = CountingBackend(Difficulty.EASY)
        registry = self._registry(backend)
        request = SeedRequest(seed=5, difficulty=Difficulty.EASY)

        with patch("hexsolver_cn.seed_cache.os.replace", side_effect=OSError("read only")):
            puzzle = registry.generate(request)

        self.assertEqual(request, puzzle.request)
        self.assertFalse(puzzle.cache_hit)
        self.assertFalse(puzzle.cache_saved)
        self.assertEqual(1, backend.calls)
        self.assertEqual(0, self.cache.stats().entry_count)

    def test_clear_removes_only_owned_cache_files(self) -> None:
        backend = CountingBackend(Difficulty.EASY)
        self._registry(backend).generate(SeedRequest(seed=6, difficulty=Difficulty.EASY))
        root = Path(self.temporary_directory.name)
        unrelated = root / "keep.txt"
        unrelated.write_text("do not remove", encoding="utf-8")
        owned_temporary = root / "seed-interrupted.tmp"
        owned_temporary.write_text("temporary", encoding="utf-8")

        removed = self.cache.clear()

        self.assertEqual(2, removed)
        self.assertTrue(unrelated.is_file())
        self.assertEqual(0, self.cache.stats().entry_count)

    def test_registry_without_cache_does_not_write_user_state(self) -> None:
        backend = CountingBackend(Difficulty.HARD)
        registry = SeedGeneratorRegistry()
        registry.register(backend)
        registry.generate(SeedRequest(seed=7, difficulty=Difficulty.HARD))
        registry.generate(SeedRequest(seed=7, difficulty=Difficulty.HARD))

        self.assertIsNone(registry.cache)
        self.assertEqual(2, backend.calls)
        self.assertEqual(0, self.cache.stats().entry_count)


if __name__ == "__main__":
    unittest.main()
