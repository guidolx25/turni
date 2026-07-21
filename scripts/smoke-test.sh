#!/usr/bin/env bash
# Production smoke test (spec §12 Phase 6 gate: "production URL live").
#
# Read-only and safe to re-run: it authenticates, reads, and asserts the two
# invariants that would be catastrophic to get wrong in production — root is
# invisible to a non-root caller (§5), and no response leaks `is_root` or a
# calendar token. It deliberately does NOT solve, publish, or write anything.
#
# Usage:
#   scripts/smoke-test.sh https://turni.fly.dev worker_username 'password'
#
# Exit 0 = green. Any failure exits non-zero with the reason.
set -euo pipefail

BASE="${1:?usage: smoke-test.sh BASE_URL USERNAME PASSWORD}"
USERNAME="${2:?missing username}"
PASSWORD="${3:?missing password}"

JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1" >&2; exit 1; }

printf 'Smoke test against %s\n' "$BASE"

# --- 1. the app is up (§11 health endpoint) --------------------------------
code="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/healthz")"
[ "$code" = "200" ] || fail "/healthz returned $code"
pass "/healthz is 200"

# --- 2. the frontend is served by the same origin (§9 single deployable) ----
html="$(curl -sS "$BASE/")"
grep -qi '<div id="root"' <<<"$html" || fail "/ did not serve the SPA shell"
# §9 + the Phase 0 carry-forward: a bilingual app must not hardcode the wrong
# language. The served shell defaults to Italian; the client then follows the
# user's setting.
grep -qi '<html lang="it"' <<<"$html" || fail "/ did not serve lang=\"it\""
pass "/ serves the SPA with the expected default language"

# --- 3. unauthenticated access is refused (§5/§7) --------------------------
code="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/me")"
[ "$code" = "401" ] || fail "/me without a session returned $code, expected 401"
pass "/me refuses an anonymous caller"

# --- 4. login works (§7 session cookie) ------------------------------------
code="$(curl -sS -o /dev/null -w '%{http_code}' -c "$JAR" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" \
  "$BASE/auth/login")"
[ "$code" = "200" ] || fail "login returned $code"
grep -q 'turni_session' "$JAR" || fail "login set no session cookie"
pass "login succeeds and sets a session cookie"

me="$(curl -sS -b "$JAR" "$BASE/me")"

# --- 5. §5/§6: the two things that must never leak -------------------------
grep -q '"is_root"' <<<"$me" && fail "/me leaked is_root (§5)"
pass "/me does not serialize is_root"

# /me is the ONE place the caller's own feed token may appear (§6 v1.7).
grep -q '"ics_token"' <<<"$me" || fail "/me is missing the caller's own ics_token"
pass "/me carries the caller's own ics_token"

weeks="$(curl -sS -b "$JAR" "$BASE/weeks")"
grep -q '"is_root"' <<<"$weeks" && fail "/weeks leaked is_root (§5)"
pass "/weeks does not leak is_root"

# --- 6. §5: root is invisible to a non-root caller -------------------------
# A plain worker must be refused outright by the root surface — not shown a
# filtered list, refused.
code="$(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE/root/users")"
if [ "$code" = "200" ]; then
  # The caller IS root (a legitimate way to run this). Then the listing is
  # allowed, but must still never serialize the flag itself.
  users="$(curl -sS -b "$JAR" "$BASE/root/users")"
  grep -q '"is_root"' <<<"$users" && fail "/root/users leaked is_root (§5)"
  grep -q '"ics_token"' <<<"$users" && fail "/root/users leaked another user's ics_token"
  pass "/root/users (as root) leaks neither is_root nor a feed token"
else
  [ "$code" = "403" ] || fail "/root/users returned $code, expected 403 for a worker"
  pass "/root/users is 403 for a non-root worker"
fi

# --- 7. the calendar feed rejects a bad credential (§7) --------------------
code="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/export/ics?token=definitely-not-a-real-token")"
[ "$code" = "404" ] || fail "/export/ics with a bad token returned $code, expected 404"
pass "/export/ics refuses an unknown token"

# --- 8. logout ends the session --------------------------------------------
curl -sS -o /dev/null -b "$JAR" -c "$JAR" -X POST "$BASE/auth/logout"
code="$(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE/me")"
[ "$code" = "401" ] || fail "/me after logout returned $code, expected 401"
pass "logout invalidates the session"

printf '\nSMOKE TEST GREEN\n'
