"""Local fixtures for the solver suite (§8).

These tests are PURE: they construct `SolverInput` directly and call `solve()`.
No DB session, no HTTP client, no time-of-day dependence — the only "time" is a
fixed week Monday supplied per input (see `tests.solver.fixtures.WEEK_MONDAY`).

Phase markers are per-module `pytestmark` lines (registered in `pyproject.toml`),
not a directory-wide stamp: three modules here originated in Phase 3
(`test_h3_free_day_domain`, `test_sacrifice_grant`, `test_rest_spread_first_week`)
and a blanket ``phase2`` would misattribute them to the earlier gate.
"""

from __future__ import annotations
