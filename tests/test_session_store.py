from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from hexsolver_cn.models import CellReveal, CellVisualType, ClueType, MoveAction, SuggestedMove
from hexsolver_cn.seed_workflow import Difficulty, SeedRequest
from hexsolver_cn.session import InteractivePuzzleSession
from hexsolver_cn.session_store import SESSION_SCHEMA_VERSION, SessionStore, SessionStoreError

from test_seed_workflow import build_count_one_board


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = SessionStore(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _session(self) -> InteractivePuzzleSession:
        board = build_count_one_board()
        board.remaining_blue = 1
        return InteractivePuzzleSession(
            board,
            private_reveals={
                (1, 0): CellReveal(
                    visual_type=CellVisualType.BLUE,
                    clue_text="2",
                    clue_type=ClueType.COUNT,
                    clue_number=2,
                )
            },
        )

    def test_round_trip_preserves_board_undo_redo_request_and_move(self) -> None:
        session = self._session()
        session.set_cell_state((1, 0), CellVisualType.BLUE)
        session.undo()
        request = SeedRequest(1, Difficulty.EASY)
        move = SuggestedMove(
            (1, 0),
            MoveAction.MARK_BLUE,
            "测试理由",
            "局部必然",
        )

        self.store.save_autosave(session, request, move, 37, "reason-ref-0")
        restored = self.store.load_autosave()

        self.assertEqual(request, restored.request)
        self.assertEqual(move, restored.current_move)
        self.assertEqual(37, restored.reason_scroll_value)
        self.assertEqual("reason-ref-0", restored.pinned_reference_id)
        self.assertEqual([], restored.session.history)
        self.assertEqual(1, len(restored.session.redo_history))
        self.assertEqual(1, restored.session.board.remaining_blue)
        restored.session.redo()
        cell = restored.session.board.get_cell((1, 0))
        self.assertIs(CellVisualType.BLUE, cell.visual_type)
        self.assertEqual("2", cell.clue_text)
        self.assertEqual(0, restored.session.board.remaining_blue)

    def test_atomic_overwrite_and_clear_autosave(self) -> None:
        session = self._session()
        self.store.save_autosave(session, None, None)
        session.set_cell_state((1, 0), CellVisualType.BLACK)
        self.store.save_autosave(session, None, None)

        restored = self.store.load_autosave()
        self.assertIs(
            CellVisualType.BLACK,
            restored.session.board.get_cell((1, 0)).visual_type,
        )
        self.assertEqual([], list(Path(self.directory.name).glob("*.tmp")))
        self.store.clear_autosave()
        self.assertFalse(self.store.has_autosave())

    def test_corrupt_or_future_schema_is_rejected(self) -> None:
        self.store.autosave_path.parent.mkdir(parents=True, exist_ok=True)
        self.store.autosave_path.write_text("not-json", encoding="utf-8")
        with self.assertRaises(SessionStoreError):
            self.store.load_autosave()

        self.store.save_autosave(self._session(), None, None)
        payload = json.loads(self.store.autosave_path.read_text(encoding="utf-8"))
        payload["schema_version"] = SESSION_SCHEMA_VERSION + 1
        payload["payload_sha256"] = _digest_without_hash(payload)
        self.store.autosave_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(SessionStoreError, "不兼容"):
            self.store.load_autosave()

    def test_tampered_history_is_rejected(self) -> None:
        session = self._session()
        session.set_cell_state((1, 0), CellVisualType.BLACK)
        self.store.save_autosave(session, None, None)
        payload = json.loads(self.store.autosave_path.read_text(encoding="utf-8"))
        payload["history"][0]["before"] = "blue"
        self.store.autosave_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(SessionStoreError, "校验|不一致"):
            self.store.load_autosave()


if __name__ == "__main__":
    unittest.main()


def _digest_without_hash(payload: dict) -> str:
    clean = {key: value for key, value in payload.items() if key != "payload_sha256"}
    encoded = json.dumps(
        clean,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
