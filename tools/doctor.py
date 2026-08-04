from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from hexsolver_cn.hard_offline import OfflineHardGenerator  # noqa: E402
from hexsolver_cn.managed_easy import HeadlessEasyRunner  # noqa: E402
from hexsolver_cn.models import CellVisualType, MoveAction  # noqa: E402
from hexsolver_cn.original_bridge import (  # noqa: E402
    OriginalGameBridgeRunner,
    build_default_seed_registry,
    parse_original_export,
)
from hexsolver_cn.seed_workflow import Difficulty, SeedRequest  # noqa: E402
from hexsolver_cn.session import InteractivePuzzleSession  # noqa: E402
from hexsolver_cn.solver import HexReasoningSolver  # noqa: E402


def selected_difficulties(value: str) -> tuple[Difficulty, ...]:
    return {
        "easy": (Difficulty.EASY,),
        "hard": (Difficulty.HARD,),
        "both": (Difficulty.EASY, Difficulty.HARD),
    }[value]


def offline_export(seed: int, difficulty: Difficulty):  # type: ignore[no-untyped-def]
    if difficulty is Difficulty.EASY:
        text = HeadlessEasyRunner.discover().generate_tsv(seed)
        return parse_original_export(text)
    return OfflineHardGenerator(seed).generate_export()


def compare_with_original(seed: int, difficulties: tuple[Difficulty, ...]) -> None:
    runner = OriginalGameBridgeRunner.discover()
    runner.validate()
    print(f"[OK] 可选原版校验桥：{runner.game_dir}")
    for difficulty in difficulties:
        original = parse_original_export(runner.generate_tsv(seed, difficulty))
        offline = offline_export(seed, difficulty)
        if original != offline:
            raise SystemExit(
                f"[FAIL] {difficulty.label} seed {seed:08d} 与原版逐字段差分不一致。"
            )
        print(
            f"[OK] {difficulty.label} seed {seed:08d} 原版差分："
            f"{len(offline.cells)} 格、{len(offline.columns)} 条行线索，逐字段一致"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 HexInfinite 离线生成与逐步求解链路。")
    parser.add_argument(
        "--smoke-seed",
        type=int,
        help="可选：用离线后端生成指定种子并核对第一条建议。",
    )
    parser.add_argument(
        "--full-replay",
        action="store_true",
        help="把冒烟种子逐步解到零未知格，并逐步核对私有答案。",
    )
    parser.add_argument(
        "--compare-original",
        action="store_true",
        help="显式启动隔离原版一次，与离线结果做逐字段差分；默认绝不启动游戏。",
    )
    parser.add_argument(
        "--difficulty",
        choices=("easy", "hard", "both"),
        default="both",
        help="冒烟或原版差分的难度范围，默认两者都检查。",
    )
    args = parser.parse_args()
    if (args.full_replay or args.compare_original) and args.smoke_seed is None:
        parser.error("--full-replay / --compare-original 必须与 --smoke-seed 一起使用。")

    easy_runner = HeadlessEasyRunner.discover()
    easy_runner.validate()
    print(f"[OK] Easy 无游戏托管核心：{easy_runner.executable}")
    print(f"[OK] 原版托管程序集哈希匹配 Steam Build 5455383：{easy_runner.assembly_path}")

    registry = build_default_seed_registry()
    all_difficulties = (Difficulty.EASY, Difficulty.HARD)
    for difficulty in all_difficulties:
        fidelity = registry.fidelity_for(difficulty)
        print(f"[OK] {difficulty.label} 默认后端：{fidelity.label}")
    print("[OK] 默认生成链路不包含 Hexcells Infinite.exe")

    if args.smoke_seed is None:
        print("离线静态诊断完成。添加 --smoke-seed 1 可做真实离线生成冒烟测试。")
        return

    difficulties = selected_difficulties(args.difficulty)
    solver = HexReasoningSolver()
    for difficulty in difficulties:
        request = SeedRequest(seed=args.smoke_seed, difficulty=difficulty)
        puzzle = registry.generate(request)
        move = solver.next_step(puzzle.public_board)
        if move is None:
            verdict = "当前没有必然步"
        else:
            expected = (
                CellVisualType.BLUE
                if move.action is MoveAction.MARK_BLUE
                else CellVisualType.BLACK
            )
            if puzzle.private_answer[move.coord] is not expected:
                raise SystemExit(f"[FAIL] {difficulty.label} 第一条建议与私有答案不一致。")
            verdict = f"第一步 {move.coord} / {move.action.value} 已核对"
        print(
            f"[OK] {difficulty.label} seed {args.smoke_seed:08d}: "
            f"{len(puzzle.public_board.cells)} 格，{len(puzzle.public_board.row_clues)} 条行线索；{verdict}"
        )
        if args.full_replay:
            session = InteractivePuzzleSession(
                puzzle.public_board,
                solver,
                private_reveals=puzzle.private_reveals,
            )
            initial_hidden = len(session.board.hidden_cells())
            for step in range(1, initial_hidden + 1):
                replay_move = session.next_step()
                if replay_move is None:
                    raise SystemExit(
                        f"[FAIL] {difficulty.label} 第 {step} 步停住，"
                        f"仍有 {len(session.board.hidden_cells())} 个未知格。"
                    )
                expected = (
                    CellVisualType.BLUE
                    if replay_move.action is MoveAction.MARK_BLUE
                    else CellVisualType.BLACK
                )
                if puzzle.private_answer[replay_move.coord] is not expected:
                    raise SystemExit(
                        f"[FAIL] {difficulty.label} 第 {step} 步 {replay_move.coord} 与私有答案不一致。"
                    )
                session.apply_suggested_move(replay_move)
            print(
                f"[OK] {difficulty.label} 完整回放：{initial_hidden} 步，未知格 0，剩余蓝格 0"
            )

    if args.compare_original:
        compare_with_original(args.smoke_seed, difficulties)


if __name__ == "__main__":
    main()
