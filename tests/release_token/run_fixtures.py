#!/usr/bin/env python3
"""Fixtures for the release credential (.github/actions/release-token).

Every add-on release opens its downstream PRs (vibe_addons store, OS bake pin)
with the credential this action selects:

  App secrets (both)        -> the ga-release-bot App token, no fallback noise
  only one App secret       -> HARD ERROR (never a quiet fallback behind a
                               half-configured App)
  no App, DOWNSTREAM_SYNC_PAT -> the PAT, with a LOUD ::warning:: + summary line
  nothing                   -> HARD ERROR (a green run that opened nothing is
                               what 2026-08-19 looked like)
  App set, no token minted  -> HARD ERROR (App not installed on a repo)

The action only runs inside a release, never on a pull request, so this suite
extracts the `run:` scripts of its `select` and `resolve` steps from the LIVE
action.yml (never a copy) and executes them with fixture environments. The
mint step itself (actions/create-github-app-token) cannot run offline; its
result is injected as APP_TOKEN — minted or empty.

It also checks the wiring statically:
  - the mint action is pinned to a full commit SHA (it holds the private key);
  - addon-store-lockstep.yml uses this action (by full path) before any step
    that needs the credential, and reads secrets.DOWNSTREAM_SYNC_PAT ONLY as
    its `fallback-pat` — a step that read the PAT directly would bypass the App
    and the warning;
  - the lockstep is safe to hold a write credential in a PUBLIC repo:
    `contents: read` only, no pull_request_target, every third-party action
    pinned to a commit SHA.

And it proves it can go red: each MUTANT below breaks one rule in a copy of
the live scripts, and the suite fails unless the cases catch every mutant.

Exits 2 if a step cannot be found or fewer checks ran than declared: a checker
that inspects nothing must never report success.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github" / "actions" / "release-token" / "action.yml"
LOCKSTEP = ROOT / ".github" / "workflows" / "addon-store-lockstep.yml"


def die(msg: str) -> None:
    print(f"::error::{msg}")
    raise SystemExit(2)


for f in (ACTION, LOCKSTEP):
    if not f.is_file():
        die(f"{f} not found — cannot check the release credential")

action = yaml.safe_load(ACTION.read_text())
steps = {s.get("id"): s for s in action["runs"]["steps"]}
for sid in ("select", "app", "resolve"):
    if sid not in steps:
        die(f"step id {sid!r} not found in {ACTION}")
SELECT = steps["select"]["run"]
RESOLVE = steps["resolve"]["run"]
for name, script in (("select", SELECT), ("resolve", RESOLVE)):
    if "${{" in script:
        die(f"the {name} script contains a ${{{{ }}}} expression — it must take everything from env, or this suite cannot run it")

APP, PAT = "ghs_APPTOKENfixture", "github_pat_PATfixture"


def run(select: str, resolve: str, app_id="", app_key="", pat="", minted=APP):
    """Run select, then (as the action does) resolve. Returns a dict."""
    with tempfile.TemporaryDirectory() as d:
        out, summ = pathlib.Path(d, "out"), pathlib.Path(d, "summary")
        out.touch(); summ.touch()
        env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summ),
               "APP_ID": app_id, "APP_KEY": app_key, "PAT": pat}
        p = subprocess.run(["bash", "-c", select], env=env, capture_output=True, text=True)
        log = p.stdout + p.stderr
        outs = dict(l.split("=", 1) for l in out.read_text().splitlines() if "=" in l)
        r = {"rc": p.returncode, "log": log, "summary": summ.read_text(), "mode": outs.get("mode", ""), "token": ""}
        if p.returncode != 0:
            return r
        out.write_text("")
        env2 = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summ),
                "MODE": outs.get("mode", ""), "APP_TOKEN": minted if outs.get("mode") == "app" else "",
                "PAT_TOKEN": outs.get("pat", ""), "REPOS": "vibe_addons,ha-operating-system"}
        p2 = subprocess.run(["bash", "-c", resolve], env=env2, capture_output=True, text=True)
        outs2 = dict(l.split("=", 1) for l in out.read_text().splitlines() if "=" in l)
        r.update(rc=p2.returncode, log=log + p2.stdout + p2.stderr, summary=summ.read_text(),
                 token=outs2.get("token", ""))
        return r


def fallback_warned(r) -> bool:
    return ("::warning::FALLBACK" in r["log"] and "DOWNSTREAM_SYNC_PAT" in r["log"]
            and "FALLBACK" in r["summary"])


# (label, kwargs, predicate)
CASES = [
    # MUST-PASS — the App path, quiet
    ("App secrets set -> App token, no fallback warning",
     dict(app_id="123", app_key="-----BEGIN KEY-----"),
     lambda r: r["rc"] == 0 and r["mode"] == "app" and r["token"] == APP and "::warning::" not in r["log"]),
    ("App AND PAT set -> the App wins, PAT unused, no fallback warning",
     dict(app_id="123", app_key="-----BEGIN KEY-----", pat=PAT),
     lambda r: r["rc"] == 0 and r["mode"] == "app" and r["token"] == APP and not fallback_warned(r)),
    # MUST-PASS but LOUD — the transitional fallback
    ("only the PAT -> PAT used, with ::warning:: naming DOWNSTREAM_SYNC_PAT and a summary line",
     dict(pat=PAT),
     lambda r: r["rc"] == 0 and r["mode"] == "pat" and r["token"] == PAT and fallback_warned(r)),
    ("PAT with a pasted trailing newline -> trimmed value, whitespace warning, still loud",
     dict(pat=PAT + "\n"),
     lambda r: r["rc"] == 0 and r["token"] == PAT and "whitespace" in r["log"] and fallback_warned(r)),
    # MUST-FAIL
    ("no credential at all -> hard error",
     dict(),
     lambda r: r["rc"] != 0 and "::error::No release credential" in r["log"] and r["token"] == ""),
    ("PAT that is only whitespace, no App -> hard error",
     dict(pat=" \n"),
     lambda r: r["rc"] != 0 and "::error::" in r["log"]),
    ("App ID without key (PAT present) -> hard error naming the key, NO fallback",
     dict(app_id="123", pat=PAT),
     lambda r: r["rc"] != 0 and "GA_RELEASE_APP_PRIVATE_KEY" in r["log"] and r["token"] == "" and not fallback_warned(r)),
    ("key without App ID (PAT present) -> hard error naming the ID, NO fallback",
     dict(app_key="-----BEGIN KEY-----", pat=PAT),
     lambda r: r["rc"] != 0 and "GA_RELEASE_APP_ID" in r["log"] and r["token"] == ""),
    ("App set but no token minted (not installed) -> hard error, NO fallback to the PAT",
     dict(app_id="123", app_key="-----BEGIN KEY-----", pat=PAT, minted=""),
     lambda r: r["rc"] != 0 and "installed" in r["log"] and r["token"] == ""),
]

# Each mutant breaks one rule in a COPY of the live scripts; the cases above
# must catch every one, or the suite is not evidence.
MUTANTS = [
    ("fallback without the warning",
     lambda s, r: (re.sub(r'echo "::warning::FALLBACK[^\n]*\n', "", s), r)),
    ("PAT preferred over the App",
     lambda s, r: (s.replace('if [ "$have_id" = 1 ] && [ "$have_key" = 1 ]; then',
                             'if [ -z "${PAT:-}" ] && [ "$have_id" = 1 ] && [ "$have_key" = 1 ]; then'), r)),
    ("half-configured App falls back quietly",
     lambda s, r: (s.replace('if [ "$have_id" != "$have_key" ]; then', 'if false; then'), r)),
    ("nothing configured passes as a no-op",
     lambda s, r: (s.replace('if [ -z "$clean" ]; then\n', 'if [ -z "$clean" ]; then\n  echo mode=pat >> "$GITHUB_OUTPUT"; exit 0\n', 1), r)),
    ("empty minted token passes",
     lambda s, r: (s, r.replace('if [ -z "${APP_TOKEN:-}" ]; then', 'if false; then'))),
]

fails = ran = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global fails, ran
    ran += 1
    if ok:
        print(f"  ok    {label}")
    else:
        fails += 1
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


print("cases against the LIVE action.yml:")
for label, kw, pred in CASES:
    r = run(SELECT, RESOLVE, **kw)
    check(label, pred(r), f"rc={r['rc']} mode={r['mode']!r} log={r['log'].strip()[:300]!r}")

print("mutants (each must be caught by at least one case):")
for label, mutate in MUTANTS:
    s2, r2 = mutate(SELECT, RESOLVE)
    if (s2, r2) == (SELECT, RESOLVE):
        check(f"mutant applies: {label}", False, "the mutation did not change the script — update the mutant")
        continue
    caught = [c for c, kw, pred in CASES if not pred(run(s2, r2, **kw))]
    check(f"mutant caught: {label}", bool(caught), "no case failed")

print("static wiring:")
mint = steps["app"].get("uses", "")
check("create-github-app-token is pinned to a full commit SHA",
      bool(re.fullmatch(r"actions/create-github-app-token@[0-9a-f]{40}", mint)), mint)
check("the mint step asks only for contents + pull-requests write",
      {k for k in steps["app"].get("with", {}) if k.startswith("permission-")} == {"permission-contents", "permission-pull-requests"})

alive = [x for x in action["runs"]["steps"] if "/user" in (x.get("run") or "")]
check("a PAT fallback is asked once whether GitHub accepts it (and only on the PAT path)",
      len(alive) == 1 and alive[0].get("if") == "steps.select.outputs.mode == 'pat'"
      and "exit 1" in alive[0]["run"])

lock = LOCKSTEP.read_text()
wf = yaml.safe_load(lock)
job_steps = wf["jobs"]["sync-downstream"]["steps"]
tok = [i for i, s in enumerate(job_steps) if s.get("id") == "token"]
check("addon-store-lockstep uses THIS repo's release-token action as step 'token' (full path: './' would resolve to the caller)",
      len(tok) == 1 and job_steps[tok[0]].get("uses", "").startswith("greenautarky/vibe_addons/.github/actions/release-token@"))
users = [i for i, s in enumerate(job_steps) if "steps.token.outputs" in yaml.safe_dump(s)]
check("... and no step reads the credential before it is settled",
      bool(tok) and bool(users) and min(users) > tok[0], f"token at {tok}, users at {users}")
pat_refs = [l.strip() for l in lock.splitlines() if "secrets.DOWNSTREAM_SYNC_PAT" in l and not l.strip().startswith("#")]
check("secrets.DOWNSTREAM_SYNC_PAT is read ONLY as the action's fallback-pat",
      pat_refs == ["fallback-pat: ${{ secrets.DOWNSTREAM_SYNC_PAT }}"], repr(pat_refs))
on = wf.get("on") or wf.get(True)
for sec in ("GA_RELEASE_APP_ID", "GA_RELEASE_APP_PRIVATE_KEY", "DOWNSTREAM_SYNC_PAT"):
    check(f"{sec} is declared as a workflow_call secret", sec in on["workflow_call"].get("secrets", {}))

# Public-repo safety of the lockstep itself (it holds a write credential).
check("the lockstep asks for contents: read and nothing else (callers grant no more)",
      wf.get("permissions") == {"contents": "read"}
      and all("permissions" not in j for j in wf["jobs"].values()), repr(wf.get("permissions")))
check("the lockstep has no pull_request_target trigger", "pull_request_target" not in on)
ext = [s["uses"] for s in job_steps if "uses" in s and not s["uses"].startswith("greenautarky/")]
ext += [s["uses"] for s in action["runs"]["steps"] if "uses" in s]
unpinned = [u for u in ext if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u)]
check(f"every third-party action is pinned to a full commit SHA ({len(ext)} checked)", bool(ext) and not unpinned, repr(unpinned))

EXPECTED = len(CASES) + len(MUTANTS) + 3 + 3 + 3 + 3
if ran < EXPECTED:
    print(f"::error::only {ran} of {EXPECTED} checks ran")
    raise SystemExit(2)
print(f"{ran} checks, {fails} failed")
raise SystemExit(1 if fails else 0)
