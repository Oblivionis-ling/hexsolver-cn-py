from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hexsolver_cn.hard_offline import OfflineHardBackend, OfflineHardGenerator
from hexsolver_cn.managed_easy import HeadlessEasyBackend, HeadlessEasyRunner
from hexsolver_cn.original_bridge import build_default_seed_registry, parse_original_export
from hexsolver_cn.seed_workflow import Difficulty, GeneratorFidelity, SeedRequest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"
EASY_FIXTURE = FIXTURE_DIR / "easy_00000001_v1.tsv"
HARD_FIXTURE = FIXTURE_DIR / "hard_00000001_v4.tsv"


class FixtureHeadlessEasyRunner(HeadlessEasyRunner):
    """Exercise process routing without requiring proprietary game files."""

    def validate(self) -> None:
        return


class OfflineGenerationTests(unittest.TestCase):
    def test_easy_headless_core_matches_original_seed_one_exactly(self) -> None:
        expected = EASY_FIXTURE.read_text(encoding="utf-8-sig")
        runner = HeadlessEasyRunner.discover()
        if not runner.assembly_path.is_file():
            self.skipTest(
                "需要本机 Hexcells Infinite 的 Assembly-CSharp.dll 才能执行 Easy 集成校验。"
            )

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

        runner = FixtureHeadlessEasyRunner(
            PROJECT_ROOT / "managed_core",
            PROJECT_ROOT / "tests" / "fixtures" / "not-used.dll",
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

    def test_frozen_easy_runner_uses_bundle_managed_core(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            assembly = bundle_root / "Assembly-CSharp.dll"
            assembly.write_bytes(b"test-only")
            with (
                patch.dict(os.environ, {"HEXCELLS_ASSEMBLY": str(assembly)}),
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "_MEIPASS", str(bundle_root), create=True),
            ):
                runner = HeadlessEasyRunner.discover()

            self.assertEqual(bundle_root / "managed_core", runner.core_dir)
            self.assertEqual(assembly, runner.assembly_path)


if __name__ == "__main__":
    unittest.main()
