"""The three lexicographic objective weights (§2.2) and their separation proof.

§2.2 orders the soft objectives S1 >> S2 >> S3 and mandates well-separated
weights so that no combination of lower-tier penalties can ever outweigh a
single unit of a higher tier. This module is the *one* place the constants live,
with the arithmetic that proves the separation against worst-case penalty counts.

Worst-case bounds (this week's model has 4 core workers + 1 jolly = 5 workers,
Mon–Fri, two slots):

* ``Cmax`` — max S3 ``jolly_days`` = 5 (the jolly can work on every one of the
  five weekdays).

* ``Bmax`` — max S2 ``alternation_breaks + fairness_deviation``:
    - alternation_breaks: one break var per (worker, adjacent-day-pair, slot).
      Adjacent Mon–Fri pairs = 4 (Mon-Tue, Tue-Wed, Wed-Thu, Thu-Fri), 2 slots,
      5 workers -> 5*4*2 = 40 internal break vars, each ≤ 1. Plus the cross-week
      Monday boundary: ≤ 2 slots per worker (the FULL_DAY prior collides on both)
      -> 5*2 = 10. So alternation_breaks ≤ 40 + 10 = 50.
    - fairness_deviation: |#AM − #PM| per worker. A core worker works exactly one
      slot on each of 4 worked days -> ≤ 4; the jolly works ≤ 5 AM + ≤ 5 PM ->
      ≤ 5. Sum over workers ≤ 4*4 + 5 = 21.
    - Bmax = 50 + 21 = 71.

Separation (choose W3 = 1, then climb):
    W3 = 1
    W2 > W3 * Cmax      = 1 * 5   = 5     -> pick W2 = 100   (100 > 5)
    W1 > W2 * Bmax + W3 * Cmax = 100*71 + 1*5 = 7105
                                          -> pick W1 = 10000 (10000 > 7105)

The spec's example 10000 / 100 / 1 (§2.2) satisfies both inequalities with
margin, so we adopt it verbatim.
"""

from __future__ import annotations

from app.solver.types import Weights

# §2.2 lexicographic separation — see module docstring for the Bmax/Cmax proof.
# W1 = 10000 > W2*Bmax + W3*Cmax = 7105; W2 = 100 > W3*Cmax = 5.
W1: int = 10_000  # S1 — soft personal requests (highest priority).
W2: int = 100  # S2 — alternation breaks + AM/PM fairness deviation.
# S3 — Mattia (jolly) free-day clustering. This tier is EXPECTED TO CHANGE
# (§2.2/§13: the clustering preference is the most likely knob to be retuned).
W3: int = 1

DEFAULT_WEIGHTS: Weights = Weights(w1=W1, w2=W2, w3=W3)
