"""Undo/redo stack for document-level actions (vectorize, recolor)."""

from __future__ import annotations

from dataclasses import dataclass

from vectorizer.domain.settings import TraceSettings
from vectorizer.vectorize.backend import TraceResult

DEFAULT_MAX_STEPS = 40


@dataclass(frozen=True)
class SessionSnapshot:
    """One restore point for the traced document and matching settings."""

    label: str
    result: TraceResult | None
    settings: TraceSettings


class SessionHistory:
    """Step-by-step undo/redo of document snapshots.

    The live state is kept outside this class; callers push the *previous*
    state before applying a new action, then undo/redo returns the snapshot
    to restore.
    """

    def __init__(self, *, max_steps: int = DEFAULT_MAX_STEPS) -> None:
        self._max_steps = max(2, int(max_steps))
        self._undo: list[SessionSnapshot] = []
        self._redo: list[SessionSnapshot] = []

    def set_max_steps(self, max_steps: int) -> None:
        self._max_steps = max(2, int(max_steps))
        self._trim()

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1].label if self._undo else None

    @property
    def redo_label(self) -> str | None:
        return self._redo[-1].label if self._redo else None

    @property
    def depth(self) -> int:
        return len(self._undo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def push(self, snapshot: SessionSnapshot) -> None:
        """Record state before a mutating action. Clears the redo branch."""
        self._undo.append(snapshot)
        self._redo.clear()
        self._trim()

    def undo(self, current: SessionSnapshot) -> SessionSnapshot | None:
        """Pop previous state; `current` becomes available via redo."""
        if not self.can_undo:
            return None
        previous = self._undo.pop()
        self._redo.append(current)
        return previous

    def redo(self, current: SessionSnapshot) -> SessionSnapshot | None:
        """Pop redo state; `current` goes back onto the undo stack."""
        if not self.can_redo:
            return None
        nxt = self._redo.pop()
        self._undo.append(current)
        self._trim()
        return nxt

    def _trim(self) -> None:
        while len(self._undo) > self._max_steps:
            self._undo.pop(0)
