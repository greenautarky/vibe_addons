#!/usr/bin/env bash
# ==============================================================================
# Pin-drift detector — "built but never wired".
#
# For every add-on pinned to a greenautarky self-build image
# (image: ghcr.io/greenautarky/<name>-{arch}), compare the version pinned in
# <addon>/config.yaml against the newest version tag actually PUBLISHED on ghcr.
# If ghcr has a newer tag than the pin, a fix/build was published but never
# wired into the pin — exactly what happened with ga_mosquitto 7.1.2 (built +
# pushed 2026-07-17, pin left at 7.1.1 for 6 days → the K31 subscribe-deny
# incident).
#
# Read-only: ghcr pull token + the registry v2 tags API (paginated). Uses
# GHCR_TOKEN (basic-auth to the token endpoint) for private packages when set —
# in CI pass the workflow's GITHUB_TOKEN. Falls back to an anonymous token for
# public packages. Exit non-zero if any pin lags its published image.
# ==============================================================================
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="${DRIFT_ARCH:-armv7}"   # the constraining fleet arch; all self-builds ship it
drift=0
errors=0

# A ghcr pull token for <repo> (basic-auth with GHCR_TOKEN when present so
# private packages resolve; anonymous otherwise). Empty on failure.
ghcr_token() {
  local repo="$1"
  local url="https://ghcr.io/token?scope=repository:${repo}:pull&service=ghcr.io"
  if [ -n "${GHCR_TOKEN:-}" ]; then
    curl -fsS -m 20 -u "${GHCR_USER:-token}:${GHCR_TOKEN}" "$url" 2>/dev/null
  else
    curl -fsS -m 20 "$url" 2>/dev/null
  fi | sed -E 's/.*"token":"([^"]+)".*/\1/'
}

# All tags for <repo>, following registry v2 pagination (Link: rel="next").
# Prints one tag per line. Non-zero on hard error.
ghcr_tags() {
  local repo="$1" token="$2"
  local url="https://ghcr.io/v2/${repo}/tags/list?n=100"
  local hdr body next
  hdr="$(mktemp)"; body="$(mktemp)"
  while [ -n "$url" ]; do
    if ! curl -fsS -m 20 -D "$hdr" -o "$body" \
        -H "Authorization: Bearer ${token}" "$url" 2>/dev/null; then
      rm -f "$hdr" "$body"; return 1
    fi
    grep -oE '"[^"]+"' "$body" | tr -d '"' | grep -vxE 'tags|name'
    # follow Link: <https://ghcr.io/v2/.../tags/list?last=X&n=100>; rel="next"
    next="$(grep -i '^link:' "$hdr" | sed -nE 's/.*<([^>]+)>;[[:space:]]*rel="next".*/\1/p')"
    if [ -n "$next" ]; then
      case "$next" in http*) url="$next" ;; *) url="https://ghcr.io${next}" ;; esac
    else
      url=""
    fi
  done
  rm -f "$hdr" "$body"
}

# Newest version-like tag (starts with a digit, dotted), semver-sorted.
latest_published_tag() {
  local repo="$1" token
  token="$(ghcr_token "$repo")" || return 1
  [ -n "$token" ] || return 1
  ghcr_tags "$repo" "$token" \
    | grep -vxE 'latest' \
    | grep -E '^[0-9]+([.][0-9]+)+' \
    | sort -V | tail -1
}

printf '%-26s %-12s %-12s %s\n' "ADDON" "PINNED" "PUBLISHED" "STATUS"
printf '%-26s %-12s %-12s %s\n' "-----" "------" "---------" "------"

for cfg in "${root}"/*/config.yaml; do
  [ -f "$cfg" ] || continue
  image="$(sed -nE 's/^image:[[:space:]]*//p' "$cfg" | head -1)"
  case "$image" in *ghcr.io/greenautarky/*) : ;; *) continue ;; esac

  addon="$(basename "$(dirname "$cfg")")"
  pinned="$(sed -nE 's/^version:[[:space:]]*//p' "$cfg" | head -1 | tr -d '"')"
  repo="$(printf '%s' "$image" | sed -E 's#^ghcr.io/##; s/\{arch\}/'"${ARCH}"'/')"

  published="$(latest_published_tag "$repo" || true)"
  if [ -z "$published" ]; then
    printf '%-26s %-12s %-12s %s\n' "$addon" "$pinned" "?" "WARN: no tags via ghcr ($repo)"
    errors=$((errors+1)); continue
  fi

  if [ "$pinned" = "$published" ]; then
    printf '%-26s %-12s %-12s %s\n' "$addon" "$pinned" "$published" "ok"
  elif [ "$(printf '%s\n%s\n' "$pinned" "$published" | sort -V | tail -1)" = "$published" ]; then
    printf '%-26s %-12s %-12s %s\n' "$addon" "$pinned" "$published" "DRIFT: newer image published but not pinned"
    drift=$((drift+1))
  else
    printf '%-26s %-12s %-12s %s\n' "$addon" "$pinned" "$published" "WARN: pinned ahead of published (image missing?)"
    errors=$((errors+1))
  fi
done

echo
if [ "$errors" -gt 0 ]; then
  # Non-fatal by default: a package we can't list is usually an auth/naming/ghcr
  # hiccup, not drift — don't make the gate flaky. DRIFT_STRICT=1 promotes to fail.
  echo "WARN: ${errors} add-on(s) could not be reconciled (see WARN rows) — check image name / packages:read." >&2
  [ "${DRIFT_STRICT:-0}" = "1" ] && { echo "FAIL (strict): unreconciled add-ons." >&2; exit 1; }
fi
if [ "$drift" -gt 0 ]; then
  echo "FAIL: ${drift} add-on(s) pinned behind a published image (built-but-never-wired)." >&2
  echo "      Bump the pin in <addon>/config.yaml to the published tag, or yank the stale image." >&2
  exit 1
fi
echo "PASS: every self-build pin matches its newest published ghcr image."
