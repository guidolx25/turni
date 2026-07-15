"""Phase 0 gate: the fixed stack is importable, not just declared."""

import sys


def test_python_312_or_newer() -> None:
    assert sys.version_info >= (3, 12)


def test_fixed_stack_imports() -> None:
    import apscheduler  # noqa: F401
    import argon2  # noqa: F401
    import fastapi  # noqa: F401
    import sqlalchemy  # noqa: F401
    from ortools.sat.python import cp_model  # noqa: F401


def test_cp_sat_solves_a_trivial_model() -> None:
    """OR-Tools is the load-bearing dependency for Phase 2; prove it runs here."""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    x = model.new_bool_var("x")
    model.add(x == 1)
    solver = cp_model.CpSolver()
    assert solver.solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.value(x) == 1
