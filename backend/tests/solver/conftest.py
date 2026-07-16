"""Local fixtures for the Phase 2 solver suite (§8).

These tests are PURE: they construct `SolverInput` directly and call `solve()`.
No DB session, no HTTP client, no time-of-day dependence — the only "time" is a
fixed week Monday supplied per input (see `tests.solver.fixtures.WEEK_MONDAY`).

Every test collected under `tests/solver/` is tagged with the ``phase2`` marker
so the Phase 2 gate can run its exact suite with ``-m phase2``. The marker is
registered here rather than in `pyproject.toml` to keep the gate wiring local to
the suite that owns it.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``phase2`` gate marker (§12 phase-gated build)."""
    config.addinivalue_line(
        "markers",
        "phase2: Phase 2 solver-core gate suite (§8/§12) — golden test, "
        "hard-constraint, infeasibility, alternation, and clustering tests.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tag every solver-suite test ``phase2`` so ``-m phase2`` selects them all."""
    marker = pytest.mark.phase2
    for item in items:
        if "tests/solver/" in item.nodeid or item.nodeid.startswith("solver/"):
            item.add_marker(marker)
