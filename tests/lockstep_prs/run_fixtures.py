#!/usr/bin/env python3
"""Fixtures for the two PR steps of addon-store-lockstep.yml.

"Open the store PR" — in a clone of a local bare repo standing in for this
store, with `gh` replaced by a stub on PATH:
    MUST-PASS  a changed entry is pushed to ci/sync-<slug>-<version> (never to
               main), a PR is opened with the agreed title and NOT merged; an
               open PR is reused; an entry already in sync opens nothing and
               verifies against main
    MUST-FAIL  no PR created or found -> hard error

After the store PR, the lockstep opens a PR on ha-operating-system that bumps
the add-on in buildroot-external/package/hassio/addon-images.json and
regenerates tests/ga_tests/os_integrity/expected.env. Those steps run only in a
real release, so this suite extracts their `run:` scripts from the LIVE
workflow (never a copy) and drives them offline:

  "Find this add-on's bake pin" — against pin files shaped like the real one:
    MUST-PASS  an entry is found by IMAGE, also where key != slug (mosquitto)
               a not-baked add-on with bake_pin: none is skipped quietly
               a not-baked add-on with bake_pin: auto is skipped with a WARNING
    MUST-FAIL  bake_pin: required and no entry; bake_pin: none but pinned;
               two entries with one image; unknown mode; unreadable file;
               an empty addons map (never read as "not baked")

  "Open the bake-pin PR (ha-operating-system)" — in a clone of a local bare
  repo standing in for the OS repo, with `gh` replaced by a stub on PATH and
  the OS generator replaced by a stub that writes expected.env from the pins
  (the real gen_expected.sh needs the full OS tree and the network; what is
  under test here is the step's own logic, not the generator):
    MUST-PASS  bumps the entry, commits pins + expected.env on
               ci/pin-<slug>-<version>, pushes it, opens a PR with the agreed
               title; an already-open PR is reused, not duplicated; a pin
               already at this version opens nothing
    MUST-FAIL  no PR created or found -> hard error

Mutants prove each group can go red. Exits 2 if a step is missing or fewer
checks ran than declared.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCKSTEP = ROOT / ".github" / "workflows" / "addon-store-lockstep.yml"
FIND = "Find this add-on's bake pin"
STORE = "Open the store PR"
OPEN = "Open the bake-pin PR (ha-operating-system)"


def die(msg):
    print(f"::error::{msg}")
    raise SystemExit(2)


if not LOCKSTEP.is_file():
    die(f"{LOCKSTEP} not found")
steps = yaml.safe_load(LOCKSTEP.read_text())["jobs"]["sync-downstream"]["steps"]
by_name = {s.get("name"): s for s in steps}
for n in (FIND, OPEN, STORE):
    if n not in by_name:
        die(f"step {n!r} not found in the lockstep workflow")
FIND_SH, OPEN_SH, STORE_SH = by_name[FIND]["run"], by_name[OPEN]["run"], by_name[STORE]["run"]
for n, sh in ((FIND, FIND_SH), (OPEN, OPEN_SH), (STORE, STORE_SH)):
    if "${{" in sh:
        die(f"step {n!r} has a ${{{{ }}}} expression in its script — it must read env only")
# The steps must be wired in the right order: find before open, open only on 'pin'.
names = [s.get("name") for s in steps]
if not names.index(FIND) < names.index(OPEN):
    die("the pin PR step runs before the pin is found")
if not names.index(STORE) < names.index(OPEN):
    die("the pin PR step runs before the store PR — its body links the store PR")

NS = "ghcr.io/greenautarky"
PINS = {"addons": {
    "mosquitto": {"image": f"{NS}/ga_mosquitto-{{arch}}", "version": "7.2.3"},
    "ga_influxdbv1": {"image": f"{NS}/ga_influxdbv1-{{arch}}", "version": "0.0.19"},
    "ga_manager": {"image": f"{NS}/ga_manager-{{arch}}", "version": "0.212.0"},
    "ga_default_addon": {"image": f"{NS}/ga_default_addon-{{arch}}", "version": "2.1.0"},
    "ga_hmvapp_addon": {"image": f"{NS}/ga_hmvapp_addon-{{arch}}", "version": "2.5.1"},
}}
DUP = json.loads(json.dumps(PINS))
DUP["addons"]["hmvapp_again"] = {"image": f"{NS}/ga_hmvapp_addon-{{arch}}", "version": "2.5.0"}


def find(script, slug, mode, pins=PINS):
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d, "addon-images.json")
        if pins is not None:
            f.write_text(pins if isinstance(pins, str) else json.dumps(pins))
        out = pathlib.Path(d, "out"); out.touch()
        env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(out), "PINS_FILE": str(f),
               "IMAGE": f"{NS}/{slug}-{{arch}}", "BAKE_PIN": mode}
        p = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
        o = dict(l.split("=", 1) for l in out.read_text().splitlines() if "=" in l)
        return {"rc": p.returncode, "log": p.stdout + p.stderr, **o}


FIND_CASES = [
    ("baked add-on found by image (auto)", ("ga_hmvapp_addon", "auto"),
     lambda r: r["rc"] == 0 and r.get("action") == "pin" and r.get("key") == "ga_hmvapp_addon" and r.get("current") == "2.5.1"),
    ("key differs from slug: ga_mosquitto -> 'mosquitto'", ("ga_mosquitto", "required"),
     lambda r: r["rc"] == 0 and r.get("action") == "pin" and r.get("key") == "mosquitto"),
    ("not baked + bake_pin: none -> skip, no warning", ("ga_watch_telemetry", "none"),
     lambda r: r["rc"] == 0 and r.get("action") == "skip" and "::warning::" not in r["log"]),
    ("not baked + auto -> skip WITH a warning naming the image", ("ga_watch_telemetry", "auto"),
     lambda r: r["rc"] == 0 and r.get("action") == "skip" and "::warning::" in r["log"] and "ga_watch_telemetry-{arch}" in r["log"]),
    ("not baked + required -> hard error", ("ga_watch_telemetry", "required"),
     lambda r: r["rc"] != 0 and "action" not in r),
    ("bake_pin: none but it IS pinned -> hard error (the pin would silently lag)", ("ga_hmvapp_addon", "none"),
     lambda r: r["rc"] != 0 and "action" not in r),
    ("two entries with one image -> hard error", ("ga_hmvapp_addon", "auto", DUP),
     lambda r: r["rc"] != 0 and "action" not in r),
    ("unknown bake_pin mode -> hard error", ("ga_hmvapp_addon", "yes"),
     lambda r: r["rc"] != 0),
    ("unreadable pin file -> hard error, not 'not baked'", ("ga_hmvapp_addon", "auto", None),
     lambda r: r["rc"] != 0 and "action" not in r),
    ("empty addons map -> hard error, not 'not baked'", ("ga_watch_telemetry", "auto", {"addons": {}}),
     lambda r: r["rc"] != 0 and "action" not in r),
]
FIND_MUTANTS = [
    ("match by key instead of image",
     lambda s: s.replace('(e or {}).get("image") == image', 'k == image.split("/")[-1].replace("-{arch}", "")')),
    ("'none' ignores an existing pin", lambda s: s.replace('if mode == "none":', 'if False:')),
    ("'auto' skips silently", lambda s: re.sub(r'print\(f"::warning::no addon-images', 'print(f"no addon-images', s)),
    ("empty map read as not baked", lambda s: s.replace("if not addons:", "if False:")),
]

# ── the PR step, against a local "OS repo" ──────────────────────────────────
GEN_STUB = """#!/usr/bin/env bash
# STUB of the OS generator: expected.env from the pins, nothing else.
set -euo pipefail
cd "$(dirname "$0")/../../.."
python3 - <<'PY'
import json
d = json.load(open("buildroot-external/package/hassio/addon-images.json"))["addons"]
line = " ".join(f"{k}={e['image'].replace('{arch}','armv7')}:{e['version']}" for k, e in sorted(d.items()))
open("tests/ga_tests/os_integrity/expected.env", "w").write(f'EXPECTED_ADDON_IMAGES="{line}"\\n')
PY
"""
# gh stub: state in $GH_STATE. `pr list` prints the URL once a PR exists (or
# when PRE_EXISTING is set); `pr create` records its args and creates one,
# unless CREATE_FAILS is set.
GH_STUB = """#!/usr/bin/env bash
st="$GH_STATE"
echo "gh $*" >> "$st/calls"
case "$1 $2" in
  "pr list") [ -f "$st/pr" ] && cat "$st/pr"; exit 0 ;;
  "pr create")
    [ -n "${CREATE_FAILS:-}" ] && { echo "HTTP 502" >&2; exit 1; }
    printf '%s\\n' "$@" > "$st/create_args"
    echo "${PR_URL_BASE:-https://github.com/greenautarky/ha-operating-system/pull}/9999" > "$st/pr"; exit 0 ;;
esac
exit 0
"""


def make_os(d: pathlib.Path, pins) -> pathlib.Path:
    src = d / "src"
    (src / "buildroot-external/package/hassio").mkdir(parents=True)
    (src / "tests/ga_tests/os_integrity").mkdir(parents=True)
    (src / "buildroot-external/package/hassio/addon-images.json").write_text(json.dumps(pins, indent=2) + "\n")
    g = src / "tests/ga_tests/os_integrity/gen_expected.sh"
    g.write_text(GEN_STUB); g.chmod(0o755)
    subprocess.run(["bash", g], check=True, capture_output=True)
    git = lambda *a, cwd=src: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    git("init", "-q", "-b", "master"); git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    bare = d / "os.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(d / "work" / ".os")], check=True)
    return bare


def open_pin(script, slug="ga_hmvapp_addon", key="ga_hmvapp_addon", cur="2.5.1", ver="2.6.0",
             pre_existing=False, create_fails=False):
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        bare = make_os(d, PINS)
        st = d / "gh"; st.mkdir()
        bindir = d / "bin"; bindir.mkdir()
        (bindir / "gh").write_text(GH_STUB); (bindir / "gh").chmod(0o755)
        if pre_existing:
            (st / "pr").write_text("https://github.com/greenautarky/ha-operating-system/pull/1234\n")
        out = d / "out"; out.touch()
        env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": td, "GITHUB_OUTPUT": str(out),
               "GH_STATE": str(st), "GH_TOKEN": "x", "CRED": "app", "VER": ver, "KEY": key, "CUR": cur,
               "SLUG": slug, "SRC": slug, "STORE_URL": "https://github.com/greenautarky/vibe_addons/pull/1",
               "RUN_URL": "https://example.invalid/run", "GIT_CONFIG_NOSYSTEM": "1"}
        if create_fails:
            env["CREATE_FAILS"] = "1"
        # the step sleeps between retries; keep the suite fast
        sh = script.replace("sleep $((attempt * 10))", "sleep 0")
        p = subprocess.run(["bash", "-c", sh], cwd=d / "work", env=env, capture_output=True, text=True)
        o = dict(l.split("=", 1) for l in out.read_text().splitlines() if "=" in l)
        r = {"rc": p.returncode, "log": p.stdout + p.stderr, **o,
             "calls": (st / "calls").read_text() if (st / "calls").exists() else "",
             "create_args": (st / "create_args").read_text() if (st / "create_args").exists() else ""}
        br = f"ci/pin-{slug}-{ver}"
        ls = subprocess.run(["git", "--git-dir", str(bare), "rev-parse", "--verify", "-q", f"refs/heads/{br}"],
                            capture_output=True, text=True)
        r["pushed"] = ls.returncode == 0
        if r["pushed"]:
            show = lambda path: subprocess.run(["git", "--git-dir", str(bare), "show", f"{br}:{path}"],
                                               capture_output=True, text=True).stdout
            r["pinned"] = json.loads(show("buildroot-external/package/hassio/addon-images.json"))["addons"][key]["version"]
            r["expected"] = show("tests/ga_tests/os_integrity/expected.env")
            r["files"] = subprocess.run(["git", "--git-dir", str(bare), "diff", "--name-only", "master", br],
                                        capture_output=True, text=True).stdout.split()
        return r


URL = "https://github.com/greenautarky/ha-operating-system/pull/"
OPEN_CASES = [
    ("bump -> branch ci/pin-<slug>-<ver> pushed with pins + expected.env, PR opened with the agreed title",
     {}, lambda r: r["rc"] == 0 and r["pushed"] and r.get("pinned") == "2.6.0"
     and "ga_hmvapp_addon=ghcr.io/greenautarky/ga_hmvapp_addon-armv7:2.6.0" in r.get("expected", "")
     and sorted(r.get("files", [])) == ["buildroot-external/package/hassio/addon-images.json", "tests/ga_tests/os_integrity/expected.env"]
     and "chore(bake): pin ga_hmvapp_addon addon image to 2.6.0" in r["create_args"]
     and r.get("url", "").startswith(URL) and r.get("verify_ref") == "origin/ci/pin-ga_hmvapp_addon-2.6.0"),
    ("key != slug: ga_mosquitto bumps 'mosquitto', branch named by slug",
     dict(slug="ga_mosquitto", key="mosquitto", cur="7.2.3", ver="7.2.4"),
     lambda r: r["rc"] == 0 and r["pushed"] and r.get("pinned") == "7.2.4"),
    ("an open PR for the branch is reused, not duplicated",
     dict(pre_existing=True), lambda r: r["rc"] == 0 and r["pushed"] and "pr create" not in r["calls"]
     and r.get("url", "").endswith("/1234")),
    ("already pinned at this version -> no branch, no PR, verify against master",
     dict(cur="2.6.0"), lambda r: r["rc"] == 0 and not r["pushed"] and "pr " not in r["calls"]
     and r.get("verify_ref") == "origin/master"),
    ("no PR created or found -> hard error",
     dict(create_fails=True), lambda r: r["rc"] != 0 and "::error::" in r["log"] and "url" not in r),
]
OPEN_MUTANTS = [
    ("expected.env not regenerated", lambda s: s.replace("bash tests/ga_tests/os_integrity/gen_expected.sh >/dev/null", ":")),
    ("missing PR is not an error", lambda s: s.replace('if [ -z "$url" ]; then', 'if false; then')),
    ("always creates a new PR", lambda s: s.replace('if [ -n "$url" ]; then', 'if false; then')),
]


# ── the store PR step, against a local "vibe_addons" ─────────────────────────
STORE_BEFORE = "name: ga_hmvapp_addon\nversion: 2.5.1\nimage: ghcr.io/greenautarky/ga_hmvapp_addon-{arch}\n"
STORE_AFTER = "name: ga_hmvapp_addon\nversion: 2.6.0\nimage: ghcr.io/greenautarky/ga_hmvapp_addon-{arch}\n"
STORE_URL = "https://github.com/greenautarky/vibe_addons/pull/"


def open_store(script, rendered=STORE_AFTER, ver="2.6.0", pre_existing=False, create_fails=False):
    """Run the LIVE store-PR script in <tmp>/work with .store cloned from a
    local bare repo, the add-on source as the workspace, and a stub gh."""
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        git = lambda *a, cwd: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
        src = d / "store-src"; (src / "ga_hmvapp_addon").mkdir(parents=True)
        (src / "ga_hmvapp_addon/config.yaml").write_text(STORE_BEFORE)
        git("init", "-q", "-b", "main", cwd=src); git("add", "-A", cwd=src)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=src)
        bare = d / "store.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(bare)], check=True)
        work = d / "work"; work.mkdir()
        subprocess.run(["git", "clone", "-q", str(bare), str(work / ".store")], check=True)
        git("init", "-q", cwd=work); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                                         "--allow-empty", "-m", "addon source", cwd=work)
        tmp = d / "tmp"; tmp.mkdir()
        (tmp / "store-rendered.yaml").write_text(rendered)
        st = d / "gh"; st.mkdir()
        bindir = d / "bin"; bindir.mkdir()
        (bindir / "gh").write_text(GH_STUB); (bindir / "gh").chmod(0o755)
        if pre_existing:
            (st / "pr").write_text(STORE_URL + "1234\n")
        out = d / "out"; out.touch()
        env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": td, "GITHUB_OUTPUT": str(out),
               "GITHUB_WORKSPACE": str(work), "GH_STATE": str(st), "GH_TOKEN": "x", "CRED": "app",
               "VER": ver, "STORE_DIR": "ga_hmvapp_addon", "SLUG": "ga_hmvapp_addon", "SRC": "ga_hmvapp_addon",
               "RUN_URL": "https://example.invalid/run", "GIT_CONFIG_NOSYSTEM": "1",
               "PR_URL_BASE": STORE_URL.rstrip("/")}
        if create_fails:
            env["CREATE_FAILS"] = "1"
        sh = script.replace("sleep $((attempt * 10))", "sleep 0").replace("/tmp/", f"{tmp}/")
        p = subprocess.run(["bash", "-c", sh], cwd=work, env=env, capture_output=True, text=True)
        o = dict(l.split("=", 1) for l in out.read_text().splitlines() if "=" in l)
        r = {"rc": p.returncode, "log": p.stdout + p.stderr, **o,
             "calls": (st / "calls").read_text() if (st / "calls").exists() else "",
             "create_args": (st / "create_args").read_text() if (st / "create_args").exists() else ""}
        br = f"ci/sync-ga_hmvapp_addon-{ver}"
        r["pushed"] = subprocess.run(["git", "--git-dir", str(bare), "rev-parse", "--verify", "-q",
                                      f"refs/heads/{br}"], capture_output=True).returncode == 0
        r["main_moved"] = subprocess.run(["git", "--git-dir", str(bare), "show", "main:ga_hmvapp_addon/config.yaml"],
                                         capture_output=True, text=True).stdout != STORE_BEFORE
        if r["pushed"]:
            r["on_branch"] = subprocess.run(["git", "--git-dir", str(bare), "show", f"{br}:ga_hmvapp_addon/config.yaml"],
                                            capture_output=True, text=True).stdout
        return r


STORE_CASES = [
    ("changed entry -> branch ci/sync-<slug>-<ver> pushed with the rendered file, PR opened, main untouched",
     {}, lambda r: r["rc"] == 0 and r["pushed"] and r.get("on_branch") == STORE_AFTER and not r["main_moved"]
     and "pr merge" not in r["calls"]
     and "chore(ga_hmvapp_addon): store config sync to 2.6.0" in r["create_args"]
     and r.get("url", "").startswith(STORE_URL) and r.get("verify_ref") == "origin/ci/sync-ga_hmvapp_addon-2.6.0"),
    ("store already in sync -> no branch, no PR, verify against main",
     dict(rendered=STORE_BEFORE, ver="2.5.1"),
     lambda r: r["rc"] == 0 and not r["pushed"] and "pr " not in r["calls"] and r.get("verify_ref") == "origin/main"),
    ("an open PR for the branch is reused, not duplicated",
     dict(pre_existing=True), lambda r: r["rc"] == 0 and r["pushed"] and "pr create" not in r["calls"]
     and r.get("url", "").endswith("/1234")),
    ("no PR created or found -> hard error, no url output",
     dict(create_fails=True), lambda r: r["rc"] != 0 and "::error::" in r["log"] and "url" not in r),
]
STORE_MUTANTS = [
    ("pushes to main instead of a PR branch",
     lambda s: s.replace('git push -q -f origin "HEAD:refs/heads/${br}"', 'git push -q -f origin "HEAD:refs/heads/main"')),
    ("missing PR is not an error", lambda s: s.replace('if [ -z "$url" ]; then', 'if false; then')),
    ("always creates a new PR", lambda s: s.replace('if [ -n "$url" ]; then', 'if false; then')),
    ("no-change path reports nothing to verify", lambda s: s.replace('echo "verify_ref=origin/main" >> "$GITHUB_OUTPUT"', ':')),
    ("automation merges the PR", lambda s: s.replace('echo "url=${url}" >> "$GITHUB_OUTPUT"',
                                                      'gh pr merge "$url" --squash; echo "url=${url}" >> "$GITHUB_OUTPUT"')),
]

fails = ran = 0


def check(label, ok, detail=""):
    global fails, ran
    ran += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{'' if ok or not detail else ' — ' + detail}")
    if not ok:
        fails += 1


def fargs(a):
    return (a[0], a[1], a[2]) if len(a) == 3 else (a[0], a[1], PINS)


print("Find this add-on's bake pin (LIVE script):")
for label, a, pred in FIND_CASES:
    r = find(FIND_SH, *fargs(a))
    check(label, pred(r), f"{ {k: v for k, v in r.items() if k != 'log'} } {r['log'].strip()[:200]!r}")
for label, m in FIND_MUTANTS:
    s2 = m(FIND_SH)
    if s2 == FIND_SH:
        check(f"mutant applies: {label}", False, "mutation did not change the script"); continue
    check(f"mutant caught: {label}", any(not pred(find(s2, *fargs(a))) for _, a, pred in FIND_CASES))

print("Open the bake-pin PR (LIVE script, local bare repo, stub gh + stub generator):")
for label, kw, pred in OPEN_CASES:
    r = open_pin(OPEN_SH, **kw)
    check(label, pred(r), f"rc={r['rc']} pushed={r['pushed']} {r['log'].strip()[-300:]!r}")
for label, m in OPEN_MUTANTS:
    s2 = m(OPEN_SH)
    if s2 == OPEN_SH:
        check(f"mutant applies: {label}", False, "mutation did not change the script"); continue
    check(f"mutant caught: {label}", any(not pred(open_pin(s2, **kw)) for _, kw, pred in OPEN_CASES))

print("Open the store PR (LIVE script, local bare repo, stub gh):")
for label, kw, pred in STORE_CASES:
    r = open_store(STORE_SH, **kw)
    check(label, pred(r), f"rc={r['rc']} pushed={r['pushed']} {r['log'].strip()[-300:]!r}")
for label, m in STORE_MUTANTS:
    s2 = m(STORE_SH)
    if s2 == STORE_SH:
        check(f"mutant applies: {label}", False, "mutation did not change the script"); continue
    check(f"mutant caught: {label}", any(not pred(open_store(s2, **kw)) for _, kw, pred in STORE_CASES))

print("wiring:")
check("the PR step runs only when the pin was found", by_name[OPEN].get("if") == "steps.pinkey.outputs.action == 'pin'")
check("the store PR step uses the release-token credential",
      by_name[STORE].get("env", {}).get("GH_TOKEN") == "${{ steps.token.outputs.token }}")
check("no step anywhere in the lockstep merges a PR",
      not any("pr merge" in (s.get("run") or "") for s in steps))
check("the PR step uses the release-token credential",
      by_name[OPEN].get("env", {}).get("GH_TOKEN") == "${{ steps.token.outputs.token }}")

EXPECTED = (len(FIND_CASES) + len(FIND_MUTANTS) + len(OPEN_CASES) + len(OPEN_MUTANTS)
            + len(STORE_CASES) + len(STORE_MUTANTS) + 4)
if ran < EXPECTED:
    print(f"::error::only {ran} of {EXPECTED} checks ran")
    raise SystemExit(2)
print(f"{ran} checks, {fails} failed")
raise SystemExit(1 if fails else 0)
