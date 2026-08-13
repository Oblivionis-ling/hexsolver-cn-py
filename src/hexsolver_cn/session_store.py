from __future__ import annotations

import json
import hashlib
import hmac
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from . import __version__
from .models import CellReveal, CellVisualType, ClueType, Coord, MoveAction, SuggestedMove
from .seed_cache import board_from_payload, board_to_payload
from .seed_workflow import Difficulty, GAME_BUILD_ID, SeedRequest
from .session import InteractivePuzzleSession, StateChange
from .solver import HexReasoningSolver


SESSION_SCHEMA_VERSION = 1
SESSION_FILE_SUFFIX = ".hexsave"
SESSION_ENVIRONMENT_VARIABLE = "HEXSOLVER_SESSION_DIR"
MAX_SESSION_FILE_BYTES = 32 * 1024 * 1024


class SessionStoreError(ValueError):
    pass


@dataclass(frozen=True)
class StoredSession:
    session: InteractivePuzzleSession
    request: Optional[SeedRequest]
    current_move: Optional[SuggestedMove]
    reason_scroll_value: int = 0
    pinned_reference_id: Optional[str] = None


def default_session_directory() -> Path:
    override = os.environ.get(SESSION_ENVIRONMENT_VARIABLE)
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "HexInfiniteSolver" / "sessions"
    return Path.home() / "AppData" / "Local" / "HexInfiniteSolver" / "sessions"


class SessionStore:
    """Versioned, validated and atomically written puzzle progress storage."""

    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        self.directory = (
            Path(directory).expanduser().resolve()
            if directory is not None
            else default_session_directory()
        )

    @property
    def autosave_path(self) -> Path:
        return self.directory / f"autosave{SESSION_FILE_SUFFIX}"

    def has_autosave(self) -> bool:
        try:
            return self.autosave_path.is_file()
        except OSError:
            return False

    def save_autosave(
        self,
        session: InteractivePuzzleSession,
        request: Optional[SeedRequest],
        current_move: Optional[SuggestedMove],
        reason_scroll_value: int = 0,
        pinned_reference_id: Optional[str] = None,
    ) -> None:
        self.save(
            self.autosave_path,
            session,
            request,
            current_move,
            reason_scroll_value,
            pinned_reference_id,
        )

    def load_autosave(self, solver: Optional[HexReasoningSolver] = None) -> StoredSession:
        return self.load(self.autosave_path, solver)

    def clear_autosave(self) -> None:
        try:
            self.autosave_path.unlink(missing_ok=True)
        except OSError as exc:
            raise SessionStoreError(f"无法删除自动保存：{exc}") from exc

    def save(
        self,
        path: str | os.PathLike[str],
        session: InteractivePuzzleSession,
        request: Optional[SeedRequest],
        current_move: Optional[SuggestedMove],
        reason_scroll_value: int = 0,
        pinned_reference_id: Optional[str] = None,
    ) -> None:
        destination = Path(path).expanduser().resolve()
        temporary_path: Optional[Path] = None
        try:
            encoded = json.dumps(
                _session_to_payload(
                    session,
                    request,
                    current_move,
                    reason_scroll_value,
                    pinned_reference_id,
                ),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if len(encoded) > MAX_SESSION_FILE_BYTES:
                raise SessionStoreError("存档超过允许的最大大小。")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="session-",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
        except SessionStoreError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise SessionStoreError(f"无法保存局面：{exc}") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def load(
        self,
        path: str | os.PathLike[str],
        solver: Optional[HexReasoningSolver] = None,
    ) -> StoredSession:
        source = Path(path).expanduser().resolve()
        try:
            if not source.is_file():
                raise SessionStoreError("找不到局面存档。")
            if source.stat().st_size > MAX_SESSION_FILE_BYTES:
                raise SessionStoreError("存档超过允许的最大大小。")
            return _session_from_payload(
                json.loads(source.read_text(encoding="utf-8")),
                solver or HexReasoningSolver(),
            )
        except SessionStoreError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise SessionStoreError(f"局面存档损坏或不兼容：{exc}") from exc


def _session_to_payload(
    session: InteractivePuzzleSession,
    request: Optional[SeedRequest],
    current_move: Optional[SuggestedMove],
    reason_scroll_value: int = 0,
    pinned_reference_id: Optional[str] = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "app_version": __version__,
        "game_build_id": request.game_build_id if request is not None else GAME_BUILD_ID,
        "request": _request_to_payload(request),
        "initial_board": board_to_payload(session.initial_board),
        "private_reveals": [
            {
                "coord": list(coord),
                "visual_type": reveal.visual_type.value,
                "clue_text": reveal.clue_text,
                "clue_type": reveal.clue_type.value,
                "clue_number": reveal.clue_number,
            }
            for coord, reveal in sorted(session.private_reveals.items())
        ],
        "history": [_change_to_payload(change) for change in session.history],
        "redo_history": [_change_to_payload(change) for change in session.redo_history],
        "current_move": _move_to_payload(current_move),
        "reason_state": {
            "scroll_value": max(0, int(reason_scroll_value)),
            "pinned_reference_id": pinned_reference_id,
        },
    }
    payload["payload_sha256"] = _payload_digest(payload)
    return payload


def _session_from_payload(value: Any, solver: HexReasoningSolver) -> StoredSession:
    payload = _mapping(value, "存档")
    if _integer(payload.get("schema_version"), "schema_version") != SESSION_SCHEMA_VERSION:
        raise SessionStoreError("存档版本与当前程序不兼容。")
    expected_digest = _string(payload.get("payload_sha256"), "payload_sha256")
    digest_payload = {key: item for key, item in payload.items() if key != "payload_sha256"}
    if not hmac.compare_digest(expected_digest, _payload_digest(digest_payload)):
        raise SessionStoreError("存档完整性校验失败，文件可能已损坏或被修改。")
    if _string(payload.get("game_build_id"), "game_build_id") != GAME_BUILD_ID:
        raise SessionStoreError("存档对应的游戏 Build 与当前程序不一致。")
    request = _request_from_payload(payload.get("request"))
    session = InteractivePuzzleSession(
        board_from_payload(payload.get("initial_board")),
        solver,
        private_reveals=_reveals_from_payload(payload.get("private_reveals")),
    )
    for item in _list(payload.get("history"), "history"):
        expected = _change_from_payload(item)
        actual = session.set_cell_state(expected.coord, expected.after)
        if actual != expected:
            raise SessionStoreError("存档操作记录与初始盘面不一致。")
    redo_history = [
        _change_from_payload(item)
        for item in _list(payload.get("redo_history"), "redo_history")
    ]
    _validate_redo_stack(session, redo_history)
    session.redo_history = redo_history
    current_move = _move_from_payload(payload.get("current_move"))
    if current_move is not None:
        cell = session.board.get_cell(current_move.coord)
        if cell is None or cell.visual_type is not CellVisualType.HIDDEN:
            current_move = None
    reason_state = _mapping(payload.get("reason_state"), "reason_state")
    scroll_value = _integer(reason_state.get("scroll_value"), "reason_state.scroll_value")
    if scroll_value < 0:
        raise SessionStoreError("推理滚动位置不能小于零。")
    pinned_reference_id = reason_state.get("pinned_reference_id")
    if pinned_reference_id is not None:
        pinned_reference_id = _string(
            pinned_reference_id,
            "reason_state.pinned_reference_id",
        )
    if current_move is None:
        scroll_value = 0
        pinned_reference_id = None
    return StoredSession(
        session=session,
        request=request,
        current_move=current_move,
        reason_scroll_value=scroll_value,
        pinned_reference_id=pinned_reference_id,
    )


def _validate_redo_stack(
    session: InteractivePuzzleSession,
    redo_history: list[StateChange],
) -> None:
    trial = deepcopy(session)
    for change in reversed(redo_history):
        try:
            actual = trial.set_cell_state(change.coord, change.after)
        except ValueError as exc:
            raise SessionStoreError("存档重做记录与当前盘面不一致。") from exc
        if actual != change:
            raise SessionStoreError("存档重做记录与当前盘面不一致。")


def _request_to_payload(request: Optional[SeedRequest]) -> Any:
    if request is None:
        return None
    return {
        "seed": request.seed,
        "difficulty": request.difficulty.value,
        "game_build_id": request.game_build_id,
    }


def _request_from_payload(value: Any) -> Optional[SeedRequest]:
    if value is None:
        return None
    payload = _mapping(value, "request")
    request = SeedRequest(
        seed=_integer(payload.get("seed"), "request.seed"),
        difficulty=Difficulty(_string(payload.get("difficulty"), "request.difficulty")),
        game_build_id=_string(payload.get("game_build_id"), "request.game_build_id"),
    )
    if request.game_build_id != GAME_BUILD_ID:
        raise SessionStoreError("种子存档对应的游戏 Build 与当前程序不一致。")
    return request


def _reveals_from_payload(value: Any) -> dict[Coord, CellReveal]:
    result: dict[Coord, CellReveal] = {}
    for index, item in enumerate(_list(value, "private_reveals")):
        reveal = _mapping(item, f"private_reveals[{index}]")
        coord = _coord(reveal.get("coord"), "private reveal coord")
        if coord in result:
            raise SessionStoreError("私有揭示包含重复坐标。")
        result[coord] = CellReveal(
            visual_type=CellVisualType(
                _string(reveal.get("visual_type"), "private reveal visual_type")
            ),
            clue_text=_string(reveal.get("clue_text"), "private reveal clue_text"),
            clue_type=ClueType(_string(reveal.get("clue_type"), "private reveal clue_type")),
            clue_number=_optional_integer(reveal.get("clue_number"), "private reveal clue_number"),
        )
    return result


def _change_to_payload(change: StateChange) -> dict[str, Any]:
    return {
        "coord": list(change.coord),
        "before": change.before.value,
        "after": change.after.value,
        "before_clue_text": change.before_clue_text,
        "before_clue_type": change.before_clue_type.value,
        "before_clue_number": change.before_clue_number,
        "after_clue_text": change.after_clue_text,
        "after_clue_type": change.after_clue_type.value,
        "after_clue_number": change.after_clue_number,
    }


def _change_from_payload(value: Any) -> StateChange:
    payload = _mapping(value, "state change")
    before = CellVisualType(_string(payload.get("before"), "change.before"))
    after = CellVisualType(_string(payload.get("after"), "change.after"))
    if before not in InteractivePuzzleSession.EDITABLE_STATES or after not in InteractivePuzzleSession.EDITABLE_STATES:
        raise SessionStoreError("操作记录包含不可编辑的格子状态。")
    if before is after:
        raise SessionStoreError("操作记录不能是无变化操作。")
    return StateChange(
        coord=_coord(payload.get("coord"), "change.coord"),
        before=before,
        after=after,
        before_clue_text=_string(payload.get("before_clue_text"), "change.before_clue_text"),
        before_clue_type=ClueType(
            _string(payload.get("before_clue_type"), "change.before_clue_type")
        ),
        before_clue_number=_optional_integer(
            payload.get("before_clue_number"), "change.before_clue_number"
        ),
        after_clue_text=_string(payload.get("after_clue_text"), "change.after_clue_text"),
        after_clue_type=ClueType(
            _string(payload.get("after_clue_type"), "change.after_clue_type")
        ),
        after_clue_number=_optional_integer(
            payload.get("after_clue_number"), "change.after_clue_number"
        ),
    )


def _move_to_payload(move: Optional[SuggestedMove]) -> Any:
    if move is None:
        return None
    return {
        "coord": list(move.coord),
        "action": move.action.value,
        "reason": move.reason,
        "source": move.source,
    }


def _move_from_payload(value: Any) -> Optional[SuggestedMove]:
    if value is None:
        return None
    payload = _mapping(value, "current_move")
    return SuggestedMove(
        coord=_coord(payload.get("coord"), "current_move.coord"),
        action=MoveAction(_string(payload.get("action"), "current_move.action")),
        reason=_string(payload.get("reason"), "current_move.reason"),
        source=_string(payload.get("source"), "current_move.source"),
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SessionStoreError(f"{name} 必须是对象。")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SessionStoreError(f"{name} 必须是数组。")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise SessionStoreError(f"{name} 必须是文本。")
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SessionStoreError(f"{name} 必须是整数。")
    return value


def _optional_integer(value: Any, name: str) -> Optional[int]:
    return None if value is None else _integer(value, name)


def _coord(value: Any, name: str) -> Coord:
    items = _list(value, name)
    if len(items) != 2:
        raise SessionStoreError(f"{name} 必须包含两个整数。")
    return (_integer(items[0], name), _integer(items[1], name))


def _payload_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
