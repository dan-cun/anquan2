from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any

from app.schemas.ledger import LedgerAnchor, LedgerEntry, LedgerVerifyResponse

_FLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_ZERO_HASH = "0" * 64


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JsonlLedgerStore:
    def __init__(self, ledger_dir: Path, snapshot_interval: int = 10) -> None:
        self.ledger_dir = ledger_dir
        self.snapshot_interval = max(snapshot_interval, 1)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def append(
        self,
        flow_id: str,
        *,
        event_type: str,
        actor: str,
        payload: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        self._validate_flow_id(flow_id)
        with self._lock:
            last_entry = self._read_last_entry(flow_id)
            seq = 1 if last_entry is None else last_entry.seq + 1
            prev_hash = _ZERO_HASH if last_entry is None else last_entry.hash
            entry = LedgerEntry(
                flow_id=flow_id,
                seq=seq,
                event_type=event_type,
                actor=actor,
                payload=payload or {},
                prev_hash=prev_hash,
                hash="",
                created_at=_utc_now(),
            )
            entry = entry.model_copy(update={"hash": self._compute_hash(entry)})
            with self._ledger_path(flow_id).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")
            if entry.seq % self.snapshot_interval == 0:
                self._append_anchor(entry)
            return entry

    def list_entries(
        self,
        flow_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
        after_sequence: int = 0,
    ) -> list[LedgerEntry]:
        self._validate_flow_id(flow_id)
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        entries = [
            entry for entry in self._read_entries(flow_id) if entry.seq > after_sequence
        ]
        sliced = entries[offset:]
        return sliced if limit is None else sliced[:limit]

    def list_anchors(self, flow_id: str) -> list[LedgerAnchor]:
        self._validate_flow_id(flow_id)
        path = self._anchor_path(flow_id)
        if not path.exists():
            return []
        return [
            LedgerAnchor.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def verify(self, flow_id: str) -> LedgerVerifyResponse:
        self._validate_flow_id(flow_id)
        errors: list[str] = []
        previous_hash = _ZERO_HASH
        last_hash: str | None = None
        entries = self._read_entries(flow_id)

        for expected_seq, entry in enumerate(entries, start=1):
            if entry.seq != expected_seq:
                errors.append(f"seq mismatch at entry {entry.seq}: expected {expected_seq}")
            if entry.prev_hash != previous_hash:
                errors.append(f"prev_hash mismatch at seq {entry.seq}")
            recomputed = self._compute_hash(entry)
            if entry.hash != recomputed:
                errors.append(f"hash mismatch at seq {entry.seq}")
            previous_hash = entry.hash
            last_hash = entry.hash

        anchors = self.list_anchors(flow_id)
        by_seq = {entry.seq: entry.hash for entry in entries}
        for anchor in anchors:
            if by_seq.get(anchor.seq) != anchor.hash:
                errors.append(f"anchor mismatch at seq {anchor.seq}")

        return LedgerVerifyResponse(
            flow_id=flow_id,
            valid=not errors,
            entries_checked=len(entries),
            anchors_checked=len(anchors),
            last_hash=last_hash,
            errors=errors,
        )

    def _read_entries(self, flow_id: str) -> list[LedgerEntry]:
        path = self._ledger_path(flow_id)
        if not path.exists():
            return []
        return [
            LedgerEntry.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _read_last_entry(self, flow_id: str) -> LedgerEntry | None:
        entries = self._read_entries(flow_id)
        return entries[-1] if entries else None

    def _append_anchor(self, entry: LedgerEntry) -> None:
        anchor = LedgerAnchor(
            flow_id=entry.flow_id,
            seq=entry.seq,
            hash=entry.hash,
            created_at=_utc_now(),
        )
        with self._anchor_path(entry.flow_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(anchor.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def _ledger_path(self, flow_id: str) -> Path:
        return self.ledger_dir / f"{flow_id}.jsonl"

    def _anchor_path(self, flow_id: str) -> Path:
        return self.ledger_dir / f"{flow_id}.anchors.jsonl"

    @staticmethod
    def _compute_hash(entry: LedgerEntry) -> str:
        payload = entry.model_dump(mode="json", exclude={"hash"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_flow_id(flow_id: str) -> None:
        if not _FLOW_ID_PATTERN.fullmatch(flow_id):
            raise ValueError("flow_id may only contain letters, numbers, dot, dash, and underscore")
