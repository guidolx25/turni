"""The lexicographic objective weights (§2.2) and their separation proof.

§2.2 orders the soft objectives S1 >> {S2 band} >> S3 and mandates well-separated
weights so that no combination of lower-tier penalties can ever outweigh a single
unit of a higher tier. This module is the *one* place the constants live, with the
arithmetic that proves the separation against worst-case penalty counts.

The objective CP-SAT minimizes (§8) is::

    W1·soft + W2·(alt breaks + fairness) + W2_SPREAD·spread + W3·jolly

where ``W2`` and ``W2_SPREAD`` both sit in the S2 band (``W2_SPREAD`` above a
single ``W2`` alternation unit but far below ``W1``).

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

* ``Smax`` — max S2 ``spread_shared_pairs`` = C(|F|, 2), where F is the set of
  full-weekend workers (prior state FULL_DAY: the two full-day spiaggini). Each
  core has exactly one free day (H3), so a pair "shares" iff their single free
  days coincide — at most one shared day per pair. With |F| = 2 that is
  C(2, 2) = 1.

Separation.

(a) Split-forcing (W2_SPREAD must beat what co-locating an F-pair buys). Placing
    the two full-weekend workers on the SAME free day can save at most:
      - 1 alternation break: only one of them can take the boundary-avoiding
        Monday rest when split; co-locating lets both rest the same (Monday) day
        so the other dodges its cross-week boundary break -> W2·1 = 100, and
      - ≤ 1 jolly day: co-locating pairs the gap so the jolly may work one fewer
        day -> W3·1 = 1.
    So the pull toward sharing is ≤ W2·1 + W3·1 = 101. We need
      W2_SPREAD > 101  ->  pick W2_SPREAD = 200  (200 > 101), = 2·W2.

(b) W1 still dominates the whole lower sum:
      W1 > W2·Bmax + W2_SPREAD·Smax + W3·Cmax
         = 100·71 + 200·1 + 1·5 = 7305  <  10000.
    So one unit of S1 (W1 = 10000) outweighs any feasible combination of the
    entire S2 band plus S3.

The spec's example 10000 / 100 / 200 / 1 (§2.2) satisfies both inequalities with
margin, so we adopt it verbatim.
"""

from __future__ import annotations

from app.solver.types import Weights

# §2.2 lexicographic separation — see module docstring for the Bmax/Cmax/Smax proof.
# W1 = 10000 > W2*Bmax + W2_SPREAD*Smax + W3*Cmax = 7305; W2_SPREAD = 200 > 101
# (the max S2+S3 pull toward co-locating an F-pair); W2 = 100 > W3*Cmax = 5.
W1: int = 10_000  # S1 — soft personal requests (highest priority).
W2: int = 100  # S2 — alternation breaks + AM/PM fairness deviation.
# S2 (rest spread) — full-weekend worker pairs sharing a free day (§2.2). Lives
# in the S2 band, sized to dispreference co-locating an F-pair over the single
# alternation break that splitting them costs (200 = 2·W2 > 101).
W2_SPREAD: int = 200
# S3 — Mattia (jolly) free-day clustering. This tier is EXPECTED TO CHANGE
# (§2.2/§13: the clustering preference — and the S2-band spread tuning above —
# are the most likely knobs to be retuned).
W3: int = 1

DEFAULT_WEIGHTS: Weights = Weights(w1=W1, w2=W2, w3=W3, w2_spread=W2_SPREAD)
