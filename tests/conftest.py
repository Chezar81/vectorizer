from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.generate import generate_fixtures

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> dict[str, Path]:
    return generate_fixtures(FIXTURE_DIR)
