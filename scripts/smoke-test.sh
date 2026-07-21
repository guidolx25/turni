#!/usr/bin/env bash
# Production smoke test (spec §12 Phase 6 gate: "production URL live").
#
# Read-only and safe to re-run: it authenticates, reads, and asserts the two
# invariants that would be catastrophic to get wrong in production — root is
# invisible to a non-root caller (§5), and no response leaks `is_root` or a
# calendar token. It deliberately does NOT solve, publish, or write anything.
#
# Usage:
#   scripts/smoke-test.sh https://turni.example.northflank.app worker_username 'password'
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
# Outside /api on purpose (§7 v1.11): it is infrastructure, and the host's probe
# points at it. Asserted as JSON so a fallback regression that served the SPA
# shell here — a 200 that means nothing — cannot pass.
read -r code ct <<<"$(curl -sS -o /dev/null -w '%{http_code} %{content_type}' "$BASE/healthz")"
[ "$code" = "200" ] || fail "/healthz returned $code"
case "$ct" in
  application/json*) pass "/healthz is a JSON 200" ;;
  *) fail "/healthz returned content-type $ct, expected application/json" ;;
esac

# --- 2. the frontend is served by the same origin (§9 single deployable) ----
html="$(curl -sS "$BASE/")"
grep -qi '<div id="root"' <<<"$html" || fail "/ did not serve the SPA shell"
# §9 + the Phase 0 carry-forward: a bilingual app must not hardcode the wrong
# language. The served shell defaults to Italian; the client then follows the
# user's setting.
grep -qi '<html lang="it"' <<<"$html" || fail "/ did not serve lang=\"it\""
pass "/ serves the SPA with the expected default language"

# §7 v1.11: the API is under /api, so a client route and an endpoint can no
# longer be the same URL. These three assertions are that split, end to end on
# the deployed instance — the halves are checked with no Accept header at all,
# because routing must not depend on one.

# Deep links / refreshes. Each of these was ambiguous before the prefix: a client
# route sharing a name with a real endpoint.
for route in /swaps /constraints /notifications; do
  deep="$(curl -sS "$BASE$route")"
  grep -qi '<div id="root"' <<<"$deep" || fail "$route did not serve the SPA shell"
done
pass "deep links to /swaps, /constraints and /notifications serve the SPA shell"

# The endpoint of the same name, now unambiguously under /api. 401 (no session)
# rather than 200: it reached the API's auth, not the static handler.
ct="$(curl -sS -o /dev/null -w '%{content_type}' "$BASE/api/swaps")"
case "$ct" in
  application/json*) pass "/api/swaps reaches the API" ;;
  *) fail "/api/swaps returned content-type $ct, expected application/json" ;;
esac

# An unknown path under /api keeps the API's JSON error shape. HTML here shows up
# in a client as a parse error, not as the 404 it is.
read -r code ct <<<"$(curl -sS -o /dev/null -w '%{http_code} %{content_type}' "$BASE/api/nonexistent")"
[ "$code" = "404" ] || fail "/api/nonexistent returned $code, expected 404"
case "$ct" in
  application/json*) pass "an unknown /api path is a JSON 404" ;;
  *) fail "/api/nonexistent returned content-type $ct, expected application/json" ;;
esac

# --- 3. unauthenticated access is refused (§5/§7) --------------------------
code="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/api/me")"
[ "$code" = "401" ] || fail "/me without a session returned $code, expected 401"
pass "/me refuses an anonymous caller"

# --- 4. login works (§7 session cookie) ------------------------------------
code="$(curl -sS -o /dev/null -w '%{http_code}' -c "$JAR" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" \
  "$BASE/api/auth/login")"
[ "$code" = "200" ] || fail "login returned $code"
grep -q 'turni_session' "$JAR" || fail "login set no session cookie"
pass "login succeeds and sets a session cookie"

me="$(curl -sS -b "$JAR" "$BASE/api/me")"

# --- 5. §5/§6: the two things that must never leak -------------------------
grep -q '"is_root"' <<<"$me" && fail "/me leaked is_root (§5)"
pass "/me does not serialize is_root"

# /me is the ONE place the caller's own feed token may appear (§6 v1.7).
grep -q '"ics_token"' <<<"$me" || fail "/me is missing the caller's own ics_token"
pass "/me carries the caller's own ics_token"

weeks="$(curl -sS -b "$JAR" "$BASE/api/weeks")"
grep -q '"is_root"' <<<"$weeks" && fail "/weeks leaked is_root (§5)"
pass "/weeks does not leak is_root"

# --- 6. §5: root is invisible to a non-root caller -------------------------
# A plain worker must be refused outright by the root surface — not shown a
# filtered list, refused.
code="$(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE/api/root/users")"
if [ "$code" = "200" ]; then
  # The caller IS root (a legitimate way to run this). Then the listing is
  # allowed, but must still never serialize the flag itself.
  users="$(curl -sS -b "$JAR" "$BASE/api/root/users")"
  grep -q '"is_root"' <<<"$users" && fail "/root/users leaked is_root (§5)"
  grep -q '"ics_token"' <<<"$users" && fail "/root/users leaked another user's ics_token"
  pass "/root/users (as root) leaks neither is_root nor a feed token"
else
  [ "$code" = "403" ] || fail "/root/users returned $code, expected 403 for a worker"
  pass "/root/users is 403 for a non-root worker"
fi

# --- 7. the calendar feed rejects a bad credential (§7) --------------------
code="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/api/export/ics?token=definitely-not-a-real-token")"
[ "$code" = "404" ] || fail "/export/ics with a bad token returned $code, expected 404"
pass "/export/ics refuses an unknown token"

# --- 8. logout ends the session --------------------------------------------
curl -sS -o /dev/null -b "$JAR" -c "$JAR" -X POST "$BASE/api/auth/logout"
code="$(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE/api/me")"
[ "$code" = "401" ] || fail "/me after logout returned $code, expected 401"
pass "logout invalidates the session"

printf '\nSMOKE TEST GREEN\n'
