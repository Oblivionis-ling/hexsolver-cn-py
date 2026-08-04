from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .original_bridge import (
    OriginalExportError,
    board_from_original_export,
    parse_original_export,
    private_reveals_from_original_export,
)
from .seed_workflow import (
    GAME_ASSEMBLY_SHA256,
    Difficulty,
    GeneratedPuzzle,
    GeneratorFidelity,
    SeedGenerationUnavailable,
    SeedRequest,
)


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class HeadlessEasyRunner:
    """Execute the original managed Easy generator without starting Unity."""

    def __init__(
        self,
        core_dir: Path,
        assembly_path: Path,
        *,
        timeout_seconds: float = 30.0,
        process_runner: ProcessRunner = subprocess.run,
    ) -> None:
        self.core_dir = Path(core_dir).resolve()
        self.assembly_path = Path(assembly_path).resolve()
        self.timeout_seconds = timeout_seconds
        self._process_runner = process_runner

    @classmethod
    def discover(cls) -> "HeadlessEasyRunner":
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            project_root = Path(sys._MEIPASS).resolve()
        else:
            project_root = Path(__file__).resolve().parents[2]
        workspace_root = project_root.parent
        configured = os.environ.get("HEXCELLS_ASSEMBLY")
        executable_dir = Path(sys.executable).resolve().parent
        program_files_x86 = Path(
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        )
        candidates = [
            Path(configured) if configured else None,
            executable_dir / "Assembly-CSharp.dll",
            workspace_root
            / "reverse_harness"
            / "game"
            / "Hexcells Infinite_Data"
            / "Managed"
            / "Assembly-CSharp.dll.orig",
            Path(r"F:\SteamLibrary\steamapps\common\Hexcells Infinite")
            / "Hexcells Infinite_Data"
            / "Managed"
            / "Assembly-CSharp.dll",
            program_files_x86
            / "Steam"
            / "steamapps"
            / "common"
            / "Hexcells Infinite"
            / "Hexcells Infinite_Data"
            / "Managed"
            / "Assembly-CSharp.dll",
        ]
        assembly = next((path for path in candidates if path is not None and path.is_file()), None)
        if assembly is None:
            assembly = candidates[1]
            assert assembly is not None
        return cls(project_root / "managed_core", assembly)

    @property
    def executable(self) -> Path:
        return self.core_dir / "bin" / "HexcellsHeadless.exe"

    @property
    def build_script(self) -> Path:
        return self.core_dir / "build.ps1"

    def _ensure_built(self) -> None:
        dependencies = (
            self.executable,
            self.core_dir / "bin" / "UnityEngine.dll",
            self.core_dir / "bin" / "TextMeshPro-5.6-Runtime.dll",
        )
        if all(path.is_file() for path in dependencies):
            return
        if not self.build_script.is_file():
            raise SeedGenerationUnavailable(
                f"Easy 无游戏托管核心尚未构建，且缺少构建脚本：{self.build_script}"
            )
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(self.build_script),
                ],
                cwd=str(self.core_dir.parent),
                timeout=60.0,
                check=False,
                text=True,
                capture_output=True,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SeedGenerationUnavailable(f"无法构建 Easy 无游戏托管核心：{exc}") from exc
        if completed.returncode != 0 or not all(path.is_file() for path in dependencies):
            details = (completed.stderr or completed.stdout).strip()
            raise SeedGenerationUnavailable(
                f"Easy 无游戏托管核心构建失败（代码 {completed.returncode}）：{details}"
            )

    def validate(self) -> None:
        self._ensure_built()
        if not self.assembly_path.is_file():
            raise SeedGenerationUnavailable(
                "找不到原版 Assembly-CSharp.dll。请确认 Steam 版 Hexcells Infinite 已安装，"
                "或通过 HEXCELLS_ASSEMBLY 指定原版程序集；打包版不会分发游戏文件。"
            )
        if _sha256(self.assembly_path) != GAME_ASSEMBLY_SHA256:
            raise SeedGenerationUnavailable(
                "原版 Assembly-CSharp.dll 的版本与 Steam Build 5455383 不匹配，"
                "为避免静默生成错误地图，已拒绝运行。"
            )

    def generate_tsv(self, seed: int) -> str:
        self.validate()
        env = os.environ.copy()
        env["HEXCELLS_ASSEMBLY"] = str(self.assembly_path)
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = self._process_runner(
                [str(self.executable), "easy", str(seed)],
                cwd=str(self.executable.parent),
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
                f"Easy 无游戏托管核心在 {self.timeout_seconds:g} 秒内没有完成。"
            ) from exc
        except OSError as exc:
            raise SeedGenerationUnavailable(f"无法启动 Easy 无游戏托管核心：{exc}") from exc
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout).strip()
            raise SeedGenerationUnavailable(
                f"Easy 无游戏托管核心异常退出（代码 {completed.returncode}）：{details}"
            )
        if not completed.stdout.startswith("HEXINFINITE_EXPORT\t1"):
            raise SeedGenerationUnavailable("Easy 无游戏托管核心没有返回有效的地图 TSV。")
        return completed.stdout


class HeadlessEasyBackend:
    backend_id = "headless-original-managed-easy-v1"
    difficulty = Difficulty.EASY
    fidelity = GeneratorFidelity.PARITY_VERIFIED

    def __init__(self, runner: HeadlessEasyRunner | None = None) -> None:
        self.runner = runner or HeadlessEasyRunner.discover()

    def generate(self, request: SeedRequest) -> GeneratedPuzzle:
        if request.difficulty is not Difficulty.EASY:
            raise ValueError("Easy 无游戏托管后端只能处理 Easy 请求。")
        export = parse_original_export(self.runner.generate_tsv(request.seed))
        if export.seed != request.seed:
            raise OriginalExportError(
                f"Easy 无游戏托管核心返回种子 {export.seed:08d}，"
                f"与请求的 {request.seed:08d} 不一致。"
            )
        board, private_answer = board_from_original_export(export, Difficulty.EASY)
        board.logs = [
            f"Easy 种子 {request.seed:08d} 由原版 OldLevelGenerator 与 "
            "MarvinHexcellsSolver 的无 Unity 托管核心生成。",
            f"离线导入 {len(export.cells)} 个最终格子和 {len(export.columns)} 条行线索；"
            "未启动 Hexcells Infinite.exe。",
        ]
        return GeneratedPuzzle(
            request=request,
            public_board=board,
            private_answer=private_answer,
            private_reveals=private_reveals_from_original_export(export),
            backend_id=self.backend_id,
            fidelity=self.fidelity,
        )
