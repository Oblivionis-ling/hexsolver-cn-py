from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Mapping, Protocol

from .models import Board, CellReveal, CellVisualType, Coord


GAME_BUILD_ID = "5455383"
GAME_UNITY_VERSION = "5.6.3f1"
GAME_ASSEMBLY_SHA256 = "835DEC694D7685809EDAC963E0F47306AD4300C7D7C9C555AD457F20EFAA8083"


class Difficulty(str, Enum):
    EASY = "easy"
    HARD = "hard"

    @property
    def label(self) -> str:
        return "Easy" if self is Difficulty.EASY else "Hard"

    @classmethod
    def from_text(cls, value: str) -> "Difficulty":
        normalized = value.strip().lower()
        aliases = {
            "easy": cls.EASY,
            "简单": cls.EASY,
            "hard": cls.HARD,
            "困难": cls.HARD,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise ValueError("难度必须是 Easy 或 Hard。") from exc


class GeneratorFidelity(str, Enum):
    SCAFFOLD = "scaffold"
    STATIC_REVERSED = "static_reversed"
    PARITY_VERIFIED = "parity_verified"
    ORIGINAL_RUNTIME = "original_runtime"

    @property
    def is_exact(self) -> bool:
        return self in {
            GeneratorFidelity.PARITY_VERIFIED,
            GeneratorFidelity.ORIGINAL_RUNTIME,
        }

    @property
    def label(self) -> str:
        return {
            GeneratorFidelity.SCAFFOLD: "接口骨架",
            GeneratorFidelity.STATIC_REVERSED: "已静态逆向，未做同种子验证",
            GeneratorFidelity.PARITY_VERIFIED: "离线精确复刻（已通过同种子验证）",
            GeneratorFidelity.ORIGINAL_RUNTIME: "原版运行时直接生成",
        }[self]


@dataclass(frozen=True)
class SeedRequest:
    seed: int
    difficulty: Difficulty
    game_build_id: str = GAME_BUILD_ID

    @classmethod
    def parse(cls, seed_text: str, difficulty_text: str) -> "SeedRequest":
        value = seed_text.strip()
        if not value:
            raise ValueError("请输入种子号。")
        try:
            seed = int(value, 10)
        except ValueError as exc:
            raise ValueError("种子号必须是十进制整数。") from exc
        if seed < 0 or seed > 2_147_483_647:
            raise ValueError("种子号必须位于 0 到 2147483647 之间。")
        return cls(seed=seed, difficulty=Difficulty.from_text(difficulty_text))


@dataclass
class GeneratedPuzzle:
    request: SeedRequest
    public_board: Board
    private_answer: Mapping[Coord, CellVisualType] = field(repr=False)
    private_reveals: Mapping[Coord, CellReveal] = field(default_factory=dict, repr=False)
    backend_id: str = ""
    fidelity: GeneratorFidelity = GeneratorFidelity.SCAFFOLD

    def verify_public_board_has_no_hidden_answer(self) -> None:
        hidden_coords = {cell.coord for cell in self.public_board.hidden_cells()}
        answer_coords = set(self.private_answer)
        missing = hidden_coords - answer_coords
        if missing:
            raise ValueError(f"私有答案缺少 {len(missing)} 个未知格。")
        for coord in hidden_coords:
            if self.private_answer[coord] not in {CellVisualType.BLUE, CellVisualType.BLACK}:
                raise ValueError(f"格子 {coord} 的私有答案不是蓝或黑。")
            reveal = self.private_reveals.get(coord)
            if reveal is not None and reveal.visual_type is not self.private_answer[coord]:
                raise ValueError(f"格子 {coord} 的私有揭示颜色与答案不一致。")


class SeedGeneratorBackend(Protocol):
    backend_id: str
    difficulty: Difficulty
    fidelity: GeneratorFidelity

    def generate(self, request: SeedRequest) -> GeneratedPuzzle:
        ...


class SeedGenerationUnavailable(RuntimeError):
    pass


class SeedGeneratorRegistry:
    def __init__(self) -> None:
        self._backends: Dict[Difficulty, SeedGeneratorBackend] = {}

    def register(self, backend: SeedGeneratorBackend) -> None:
        self._backends[backend.difficulty] = backend

    def fidelity_for(self, difficulty: Difficulty) -> GeneratorFidelity:
        backend = self._backends.get(difficulty)
        return backend.fidelity if backend is not None else GeneratorFidelity.SCAFFOLD

    def generate(self, request: SeedRequest, *, require_verified: bool = True) -> GeneratedPuzzle:
        backend = self._backends.get(request.difficulty)
        if backend is None:
            raise SeedGenerationUnavailable(
                f"{request.difficulty.label} 种子生成器尚未接入。"
                "当前已经完成静态逆向，下一步是实现并通过原游戏同种子对照。"
            )
        if require_verified and not backend.fidelity.is_exact:
            raise SeedGenerationUnavailable(
                f"后端 {backend.backend_id} 的状态是“{backend.fidelity.label}”，"
                "尚不能声称会生成与原游戏完全相同的地图。"
            )
        puzzle = backend.generate(request)
        if puzzle.request != request:
            raise ValueError("生成器返回的种子请求与输入不一致。")
        puzzle.verify_public_board_has_no_hidden_answer()
        return puzzle
