"""Undo/redo for segmentation maps with a hard memory budget."""

from __future__ import annotations

from vectorizer.segmentation.map import SegmentationMap

DEFAULT_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB of PNG snapshots
DEFAULT_MAX_STEPS = 80


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
        self._undo: list[bytes] = [initial.to_png_bytes()]
        self._redo: list[bytes] = []
        self._bytes = len(self._undo[0])

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
        return SegmentationMap.from_png_bytes(self._undo[-1])

    def commit(self, map_: SegmentationMap) -> None:
        payload = map_.to_png_bytes()
        self._undo.append(payload)
        self._bytes += len(payload)
        self._redo.clear()
        self._trim()

    def undo(self) -> SegmentationMap | None:
        if not self.can_undo:
            return None
        payload = self._undo.pop()
        self._bytes -= len(payload)
        self._redo.append(payload)
        return self.current()

    def redo(self) -> SegmentationMap | None:
        if not self.can_redo:
            return None
        payload = self._redo.pop()
        self._undo.append(payload)
        self._bytes += len(payload)
        self._trim()
        return self.current()

    def reset(self, map_: SegmentationMap) -> None:
        payload = map_.to_png_bytes()
        self._undo = [payload]
        self._redo.clear()
        self._bytes = len(payload)

    def _trim(self) -> None:
        while len(self._undo) > self._max_steps and len(self._undo) > 1:
            dropped = self._undo.pop(0)
            self._bytes -= len(dropped)
        while self._bytes > self._max_bytes and len(self._undo) > 1:
            dropped = self._undo.pop(0)
            self._bytes -= len(dropped)
