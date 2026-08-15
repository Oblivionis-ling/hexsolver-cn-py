from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter, process_time
from typing import Callable, Iterable

import ortools


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hexsolver_cn.models import CellVisualType, MoveAction, SuggestedMove  # noqa: E402
from hexsolver_cn.original_bridge import (  # noqa: E402
    OriginalRuntimeHardBackend,
)
from hexsolver_cn.seed_workflow import Difficulty, SeedRequest  # noqa: E402
from hexsolver_cn.session import InteractivePuzzleSession  # noqa: E402
from hexsolver_cn.session_store import SessionStore  # noqa: E402
from hexsolver_cn.solver import HexReasoningSolver, SolverError  # noqa: E402


HARD_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "hard_00000001_v4.tsv"


class _FixtureRunner:
    def __init__(self, text: str) -> None:
        self.text = text

    def generate_tsv(
        self,
        seed: int,
        difficulty: Difficulty = Difficulty.HARD,
    ) -> str:
        del seed, difficulty
        return self.text


class LegacyGlobalSolver(HexReasoningSolver):
    """The 0.8.1 two-color, rebuild-per-probe implementation."""

    def __init__(self) -> None:
        super().__init__(feasibility_workers=8)
        self.model_builds = 0
        self.feasibility_solves = 0

    def _prepare_global_model(self, board):  # type: ignore[no-untyped-def]
        self.model_builds += 1
        return super()._prepare_global_model(board)

    def _solve_model(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.feasibility_solves += 1
        return super()._solve_model(*args, **kwargs)

    def _collect_global_forced_moves(
        self,
        board,
        limit=None,
    ):  # type: ignore[no-untyped-def]
        satisfiable, _ = self._solve_model(board)
        if not satisfiable:
            raise SolverError("当前线索组合无解。")

        forced_moves: list[SuggestedMove] = []
        hidden_cells = sorted(
            board.hidden_cells(),
            key=lambda cell: (cell.coord[1], cell.coord[0]),
        )
        for cell in hidden_cells:
            can_blue = self._solve_with_assumption(board, cell.coord, True)
            can_black = self._solve_with_assumption(board, cell.coord, False)
            if can_blue and can_black:
                continue
            action = MoveAction.MARK_BLUE if can_blue else MoveAction.MARK_BLACK
            forced_moves.append(
                SuggestedMove(
                    coord=cell.coord,
                    action=action,
                    reason=self._global_reason(board, cell.coord, action),
                    source="全局求解",
                )
            )
            if limit is not None and len(forced_moves) >= limit:
                break
        return forced_moves


class MeasuredSolver(HexReasoningSolver):
    def __init__(self, workers: int) -> None:
        super().__init__(feasibility_workers=workers)
        self.model_builds = 0
        self.feasibility_solves = 0

    def _prepare_global_model(self, board):  # type: ignore[no-untyped-def]
        self.model_builds += 1
        return super()._prepare_global_model(board)

    def _solve_prepared_model(self, solver, prepared):  # type: ignore[no-untyped-def]
        self.feasibility_solves += 1
        return super()._solve_prepared_model(solver, prepared)


@dataclass(frozen=True)
class ReplayMetrics:
    wall_seconds: float
    cpu_seconds: float
    global_steps: int
    model_builds: int
    feasibility_solves: int
    move_sequence: tuple[tuple[tuple[int, int], str, str], ...]


@dataclass(frozen=True)
class Summary:
    name: str
    workers: int
    repeat: int
    wall_seconds: tuple[float, ...]
    median_wall_seconds: float
    cpu_seconds: tuple[float, ...]
    median_cpu_seconds: float
    global_steps: int
    model_builds: int
    feasibility_solves: int


def _hard_seed_one_puzzle():  # type: ignore[no-untyped-def]
    text = HARD_FIXTURE.read_text(encoding="utf-8-sig")
    backend = OriginalRuntimeHardBackend(_FixtureRunner(text))
    return backend.generate(SeedRequest(seed=1, difficulty=Difficulty.HARD))


def _run_replay(puzzle, solver: HexReasoningSolver) -> ReplayMetrics:  # type: ignore[no-untyped-def]
    session = InteractivePuzzleSession(
        puzzle.public_board,
        solver,
        private_reveals=puzzle.private_reveals,
    )
    sequence: list[tuple[tuple[int, int], str, str]] = []
    global_steps = 0
    wall_started = perf_counter()
    cpu_started = process_time()
    initial_hidden = len(session.board.hidden_cells())
    for step in range(1, initial_hidden + 1):
        move = session.next_step()
        if move is None:
            raise RuntimeError(f"第 {step} 步停住。")
        expected = (
            CellVisualType.BLUE
            if move.action is MoveAction.MARK_BLUE
            else CellVisualType.BLACK
        )
        if puzzle.private_answer[move.coord] is not expected:
            raise RuntimeError(f"第 {step} 步 {move.coord} 与私有答案不一致。")
        sequence.append((move.coord, move.action.value, move.source))
        global_steps += move.source == "全局求解"
        session.apply_suggested_move(move)
    wall_seconds = perf_counter() - wall_started
    cpu_seconds = process_time() - cpu_started
    return ReplayMetrics(
        wall_seconds=wall_seconds,
        cpu_seconds=cpu_seconds,
        global_steps=global_steps,
        model_builds=getattr(solver, "model_builds", 0),
        feasibility_solves=getattr(solver, "feasibility_solves", 0),
        move_sequence=tuple(sequence),
    )


def _summarize(
    name: str,
    workers: int,
    runs: Iterable[ReplayMetrics],
) -> Summary:
    items = tuple(runs)
    walls = tuple(item.wall_seconds for item in items)
    cpus = tuple(item.cpu_seconds for item in items)
    return Summary(
        name=name,
        workers=workers,
        repeat=len(items),
        wall_seconds=walls,
        median_wall_seconds=statistics.median(walls),
        cpu_seconds=cpus,
        median_cpu_seconds=statistics.median(cpus),
        global_steps=items[0].global_steps,
        model_builds=items[0].model_builds,
        feasibility_solves=items[0].feasibility_solves,
    )


def _benchmark_replay(
    puzzle,  # type: ignore[no-untyped-def]
    name: str,
    workers: int,
    repeat: int,
    factory: Callable[[], HexReasoningSolver],
    expected_sequence: tuple[tuple[tuple[int, int], str, str], ...] | None = None,
) -> tuple[Summary, tuple[tuple[tuple[int, int], str, str], ...]]:
    runs = tuple(_run_replay(puzzle, factory()) for _ in range(repeat))
    sequence = runs[0].move_sequence
    if any(run.move_sequence != sequence for run in runs[1:]):
        raise RuntimeError(f"{name} 的多次运行返回了不同步骤序列。")
    if expected_sequence is not None and sequence != expected_sequence:
        raise RuntimeError(f"{name} 改变了 0.8.1 的步骤序列。")
    return _summarize(name, workers, runs), sequence


def _benchmark_local_autosave(workers: int, repeat: int) -> dict[str, object] | None:
    restored = SessionStore().load_autosave(HexReasoningSolver())
    if restored is None:
        return None
    times: list[float] = []
    moves: list[tuple[tuple[int, int], str, str]] = []
    for _ in range(repeat):
        solver = MeasuredSolver(workers)
        started = perf_counter()
        move = solver.next_step(restored.session.board)
        times.append(perf_counter() - started)
        if move is None:
            raise RuntimeError("本地自动存档没有可证明的下一步。")
        moves.append((move.coord, move.action.value, move.source))
    if len(set(moves)) != 1:
        raise RuntimeError("本地自动存档的多次运行返回了不同建议。")
    return {
        "seed": restored.request.seed,
        "difficulty": restored.request.difficulty.value,
        "workers": workers,
        "wall_seconds": times,
        "median_wall_seconds": statistics.median(times),
        "move": moves[0],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="复现 0.8.2 全局求解性能试验。")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument(
        "--workers",
        default="1,2,4,8,12",
        help="优化实现要比较的 CP-SAT 工作线程数。",
    )
    parser.add_argument(
        "--include-local-autosave",
        action="store_true",
        help="额外测量当前用户自动存档；该结果不属于可移植基线。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat 必须至少为 1。")
    workers = tuple(int(value) for value in args.workers.split(",") if value)
    if not workers or any(value < 1 for value in workers):
        raise SystemExit("--workers 必须是正整数列表。")

    puzzle = _hard_seed_one_puzzle()
    baseline, baseline_sequence = _benchmark_replay(
        puzzle,
        "0.8.1-rebuild-two-colors",
        8,
        args.repeat,
        LegacyGlobalSolver,
    )
    summaries = [baseline]
    for worker_count in workers:
        summary, _ = _benchmark_replay(
            puzzle,
            "0.8.2-reuse-witness-and-model",
            worker_count,
            args.repeat,
            lambda count=worker_count: MeasuredSolver(count),
            expected_sequence=baseline_sequence,
        )
        summaries.append(summary)

    output: dict[str, object] = {
        "environment": {
            "python": platform.python_version(),
            "ortools": ortools.__version__,
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
        },
        "fixture": str(HARD_FIXTURE.relative_to(PROJECT_ROOT)),
        "summaries": [asdict(summary) for summary in summaries],
    }
    if args.include_local_autosave:
        output["local_autosave"] = [
            result
            for worker_count in workers
            if (result := _benchmark_local_autosave(worker_count, args.repeat))
            is not None
        ]
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
