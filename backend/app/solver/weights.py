"""The lexicographic objective weights (§2.2) and their separation proof.

§2.2 orders the soft objectives S1 >> S2 and mandates well-separated weights so
that no combination of lower-tier penalties can ever outweigh a single unit of a
higher tier. This module is the *one* place the constants live, with the arithmetic
that proves the separation against worst-case penalty counts.

The objective CP-SAT minimizes (§8) is::

    W1·soft_unmet + W2·(alternation_breaks + fairness_deviation)

**Two tiers, and only two (v1.12).** The former S2-band ``W2_SPREAD`` coefficient
is gone from this module, but the behaviour it bought is not: it was PROMOTED into
§2.1 H3(c), where "two workers sharing a role never share a free day" is a *hard*
constraint covering both role pairs, rather than a soft penalty covering only the
full-weekend spiaggini. There is nothing left to weigh because there is nothing
left to trade — a shared same-role free day is now infeasible, not merely dear.
Likewise the former ``W3`` (S3, Mattia clustering) is gone because H3(a)+(b)+(c)
leave exactly four legal free-day layouts and all four produce the identical jolly
load (Mon 1 / Tue 2 / Wed 1 / Thu 0 / Fri 0), so that tier had no remaining degree
of freedom to optimize over. Both disappearances *removed* objective terms; neither
removed a scheduling preference.

Worst-case bound (this week's model has 4 core workers + 1 jolly = 5 workers,
Mon–Fri, two slots). Only ``Bmax`` survives — the old ``Cmax`` (jolly worked days)
and ``Smax`` (shared-free-day pairs) bounded terms that no longer exist.

* ``Bmax`` — max S2 ``alternation_breaks + fairness_deviation``:

    - ``alternation_breaks``: one break var per (worker, adjacent-day-pair, slot).
      Adjacent Mon–Fri pairs = 4 (Mon-Tue, Tue-Wed, Wed-Thu, Thu-Fri), 2 slots,
      5 workers -> 5·4·2 = 40 internal break vars, each ≤ 1. Plus the cross-week
      Monday boundary: ≤ 2 slots per worker (the FULL_DAY prior collides on both)
      -> 5·2 = 10. So ``alternation_breaks`` ≤ 40 + 10 = 50.
    - ``fairness_deviation``: |#AM − #PM| per worker. A core worker works exactly
      one slot on each of 4 worked days (5 weekdays minus its single H3 free day)
      -> ≤ 4; the jolly works ≤ 5 AM and ≤ 5 PM -> ≤ 5. Sum over workers
      ≤ 4·4 + 5 = 21.
    - ``Bmax`` = 50 + 21 = 71.

**Validity under the H3(b) role domains and a §2.3 grant.** ``Bmax`` is re-derived,
not inherited: it must hold for the v1.12 domains ({Mon, Tue} for a spiaggino,
{Tue, Wed} for a bagnino) and for the widened ``role-domain ∪ {g}`` of a granted
worker. It does, and for the same reason in both cases — every part of it counts
workers, days and slots, never free-day positions:

* the alternation part is fixed by (workers × adjacent-day-pairs × slots) +
  boundary, with no dependence on the free-day domain at all;
* the fairness part rests on "a core worker works exactly 4 of the 5 weekdays",
  which still holds verbatim: exactly one free day inside D(u) by H3(a), every day
  outside D(u) forced worked by H4, so 5 − 1 = 4 under any domain. Only *which* 4
  changes, and |#AM − #PM| ≤ 4 regardless of which.

Narrowing the default domain from Mon–Thu to two days therefore does not lower the
bound, and a grant widening it back does not raise it. ``Bmax`` = 71 either way.

Separation. One unit of S1 must outweigh every feasible S2 combination:

    W1 > W2·Bmax = 100·71 = 7100

We adopt the spec's §2.2 example pair, W1 = 10 000 and W2 = 100, which satisfies it
with a margin of 2 900 — i.e. S1 stays dominant even if the S2 count were to grow by
another 29 units beyond its proven maximum. (The four legal H3 layouts realize an
S2 count in the single digits, so the real margin is far larger; 7 100 is the honest
worst case, not the expected one.)
"""

from __future__ import annotations

from app.solver.types import Weights

# §2.2 lexicographic separation — see the module docstring for the Bmax proof.
# W1 = 10000 > W2*Bmax = 100*71 = 7100.
W1: int = 10_000  # S1 — soft personal requests (highest priority).
W2: int = 100  # S2 — alternation breaks + AM/PM fairness deviation.

DEFAULT_WEIGHTS: Weights = Weights(w1=W1, w2=W2)
