"""Undo/redo for segmentation maps with a hard memory budget."""

from __future__ import annotations

from dataclasses import dataclass
import io

from PIL import Image

from vectorizer.segmentation.map import SegmentationMap

DEFAULT_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB of PNG snapshots
DEFAULT_MAX_STEPS = 80


@dataclass(frozen=True)
class _Snapshot:
    hard: bytes
    soft: bytes | None = None

    @property
    def nbytes(self) -> int:
        return len(self.hard) + (len(self.soft) if self.soft else 0)


def _encode(map_: SegmentationMap) -> _Snapshot:
    return _Snapshot(hard=map_.to_png_bytes(), soft=map_.soft_to_png_bytes())


def _decode(snapshot: _Snapshot) -> SegmentationMap:
    soft = None
    if snapshot.soft:
        soft = Image.open(io.BytesIO(snapshot.soft))
        soft.load()
        soft = soft.convert("RGBA")
    return SegmentationMap.from_png_bytes(snapshot.hard, soft_source=soft)


class SegmentationHistory:
    """Stores PNG-compressed snapshots. Drops oldest undos when over budget."""

    def __init__(
        self,
        initial: SegmentationMap,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        self._max_bytes = max(1_000_000, int(max_bytes))
        self._max_steps = max(2, int(max_steps))
        first = _encode(initial)
        self._undo: list[_Snapshot] = [first]
        self._redo: list[_Snapshot] = []
        self._bytes = first.nbytes

    @property
    def can_undo(self) -> bool:
        return len(self._undo) > 1

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def memory_bytes(self) -> int:
        return self._bytes

    @property
    def depth(self) -> int:
        return len(self._undo)

    def current(self) -> SegmentationMap:
        return _decode(self._undo[-1])

    def commit(self, map_: SegmentationMap) -> None:
        snapshot = _encode(map_)
        self._undo.append(snapshot)
        self._bytes += snapshot.nbytes
        self._redo.clear()
        self._trim()

    def undo(self) -> SegmentationMap | None:
        if not self.can_undo:
            return None
        snapshot = self._undo.pop()
        self._bytes -= snapshot.nbytes
        self._redo.append(snapshot)
        return self.current()

    def redo(self) -> SegmentationMap | None:
        if not self.can_redo:
            return None
        snapshot = self._redo.pop()
        self._undo.append(snapshot)
        self._bytes += snapshot.nbytes
        self._trim()
        return self.current()

    def reset(self, map_: SegmentationMap) -> None:
        snapshot = _encode(map_)
        self._undo = [snapshot]
        self._redo.clear()
        self._bytes = snapshot.nbytes

    def _trim(self) -> None:
        while len(self._undo) > self._max_steps and len(self._undo) > 1:
            dropped = self._undo.pop(0)
            self._bytes -= dropped.nbytes
        while self._bytes > self._max_bytes and len(self._undo) > 1:
            dropped = self._undo.pop(0)
            self._bytes -= dropped.nbytes
