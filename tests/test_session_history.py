from __future__ import annotations

from vectorizer.domain.document import VectorDocument
from vectorizer.domain.settings import TraceSettings, WorkflowMode
from vectorizer.gui.session_history import SessionHistory, SessionSnapshot
from vectorizer.vectorize.backend import TraceResult


def _result(name: str) -> TraceResult:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><!--{name}--></svg>'
    doc = VectorDocument(
        width=10,
        height=10,
        view_box=(0, 0, 10, 10),
        groups=(),
        raw_svg=svg,
        backend_name="test",
        path_count=0,
    )
    return TraceResult(
        document=doc,
        elapsed_seconds=0.1,
        settings=TraceSettings(),
        backend_name="test",
    )


def test_undo_redo_step_by_step() -> None:
    history = SessionHistory(max_steps=10)
    empty = SessionSnapshot("Vectorize", None, TraceSettings())
    first = SessionSnapshot("Vectorize", _result("a"), TraceSettings(workflow=WorkflowMode.BASIC))
    second = SessionSnapshot("Recolor", _result("b"), TraceSettings(workflow=WorkflowMode.ADVANCED))

    history.push(empty)
    assert history.can_undo
    assert history.undo_label == "Vectorize"

    history.push(first)
    assert history.depth == 2

    restored = history.undo(second)
    assert restored is first
    assert history.can_redo
    assert history.redo_label == "Recolor"

    restored = history.undo(first)
    assert restored is empty
    assert not history.can_undo

    restored = history.redo(empty)
    assert restored is first
    restored = history.redo(first)
    assert restored is second
    assert not history.can_redo


def test_push_clears_redo_and_trims() -> None:
    history = SessionHistory(max_steps=3)
    for i in range(5):
        history.push(SessionSnapshot(f"step{i}", None, TraceSettings()))
    assert history.depth == 3
    current = SessionSnapshot("now", None, TraceSettings())
    history.undo(current)
    assert history.can_redo
    history.push(SessionSnapshot("new", None, TraceSettings()))
    assert not history.can_redo
