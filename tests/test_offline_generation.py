from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from hexsolver_cn.hard_offline import OfflineHardBackend, OfflineHardGenerator
from hexsolver_cn.managed_easy import HeadlessEasyBackend, HeadlessEasyRunner
from hexsolver_cn.original_bridge import build_default_seed_registry, parse_original_export
from hexsolver_cn.seed_workflow import Difficulty, GeneratorFidelity, SeedRequest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
EASY_FIXTURE = WORKSPACE_ROOT / "reverse_harness" / "exports" / "easy_00000001_v1.tsv"
HARD_FIXTURE = WORKSPACE_ROOT / "reverse_harness" / "exports" / "hard_00000001_v4.tsv"
ORIGINAL_ASSEMBLY = (
    WORKSPACE_ROOT
    / "reverse_harness"
    / "game"
    / "Hexcells Infinite_Data"
    / "Managed"
    / "Assembly-CSharp.dll.orig"
)


class OfflineGenerationTests(unittest.TestCase):
    def test_easy_headless_core_matches_original_seed_one_exactly(self) -> None:
        expected = EASY_FIXTURE.read_text(encoding="utf-8-sig")
        runner = HeadlessEasyRunner(PROJECT_ROOT / "managed_core", ORIGINAL_ASSEMBLY)

        actual = runner.generate_tsv(1)

        self.assertEqual(expected, actual)

    def test_hard_python_port_matches_original_seed_one_exactly(self) -> None:
        expected = parse_original_export(HARD_FIXTURE.read_text(encoding="utf-8-sig"))

        actual = OfflineHardGenerator(1).generate_export()

        self.assertEqual(expected, actual)

    def test_default_registry_uses_only_no_game_backends(self) -> None:
        registry = build_default_seed_registry()

        easy = registry._backends[Difficulty.EASY]
        hard = registry._backends[Difficulty.HARD]
        self.assertIsInstance(easy, HeadlessEasyBackend)
        self.assertIsInstance(hard, OfflineHardBackend)
        self.assertIs(GeneratorFidelity.PARITY_VERIFIED, easy.fidelity)
        self.assertIs(GeneratorFidelity.PARITY_VERIFIED, hard.fidelity)

    def test_easy_runner_starts_headless_core_not_game_executable(self) -> None:
        calls: list[list[str]] = []
        fixture = EASY_FIXTURE.read_text(encoding="utf-8-sig")

        def fake_process(args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, fixture, "")

        runner = HeadlessEasyRunner(
            PROJECT_ROOT / "managed_core",
            ORIGINAL_ASSEMBLY,
            process_runner=fake_process,
        )

        puzzle = HeadlessEasyBackend(runner).generate(
            SeedRequest(seed=1, difficulty=Difficulty.EASY)
        )

        self.assertEqual(226, len(puzzle.public_board.cells))
        self.assertEqual(1, len(calls))
        launched = Path(calls[0][0])
        self.assertEqual("HexcellsHeadless.exe", launched.name)
        self.assertNotEqual("Hexcells Infinite.exe", launched.name)


if __name__ == "__main__":
    unittest.main()
