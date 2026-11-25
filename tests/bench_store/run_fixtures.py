#!/usr/bin/env python3
"""Drives the LIVE scripts/bench_store.py on copies of the LIVE store."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
W = pathlib.Path(tempfile.mkdtemp(prefix="bench-fx-"))
n = fails = 0
G = {"armv7": "sha256:" + "a" * 64, "aarch64": "sha256:" + "b" * 64}
GOOD = {"version": "99.0.1", "reason": "proof on a bench device", "until": "2026-12-10", "digests": G}


def check(ok, msg, detail=""):
    global n, fails
    n += 1
    fails += not ok
    print(("  ok    " if ok else "  FAIL  ") + msg + ("" if ok else "\n" + detail))


def tree(cands, extra=None, raw=None):
    t = W / f"t{n}-{len(os.listdir(W))}"
    shutil.copytree(ROOT, t, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    for p in (t / "bench").glob("*.candidate.yaml"):
        p.unlink()
    (t / "bench/candidates.json").write_text(raw if raw is not None else json.dumps({"candidates": cands}))
    for name, text in (extra or {}).items():
        (t / name).write_text(text)
    return t


def run(*a):
    r = subprocess.run([sys.executable, str(ROOT / "scripts/bench_store.py"), *map(str, a)], capture_output=True, text=True, env=dict(os.environ, BENCH_TODAY="2026-11-25"))
    return r.returncode, r.stdout + r.stderr


def val(cands, **k):
    return run("validate", "--root", tree(cands, **k))


def flag(msg, cand, needle, d="ga_manager", **k):
    rc, out = val({d: cand}, **k)
    check(rc == 1 and needle in out, "MUST-FLAG " + msg, out)


main = (ROOT / "ga_manager/config.yaml").read_text()
rc, out = val({})
check(rc == 0, "MUST-PASS no candidate", out)
for d in ("ga_manager", "influxdb", "mosquitto"):
    rc, out = val({d: GOOD})
    check(rc == 0, f"MUST-PASS a valid candidate ({d})", out)
flag("no reason", dict(GOOD, reason=" "), "no reason")
flag("expired", dict(GOOD, until="2026-11-24"), "expired")
flag("more than 30 days", dict(GOOD, until="2027-02-01"), "more than 30")
flag("no date", dict(GOOD, until="10.12.2026"), "not a date")
flag("older than main (released or stale)", dict(GOOD, version="0.0.1"), "stale")
flag("prerelease string", dict(GOOD, version="99.0.1-rc.1"), "not a release version")
flag("no digest", dict(GOOD, digests={"armv7": G["armv7"]}), "no full digest for aarch64")
flag("short digest", dict(GOOD, digests=dict(G, armv7="sha256:abc")), "no full digest for armv7")
flag("unknown add-on", GOOD, "no such store entry", d="nope")
flag("a path", GOOD, "no such store entry", d="../x")
flag("config.* under bench", GOOD, "read as an add-on", extra={"bench/config.yaml": "x: 1"})
flag("orphan candidate file", GOOD, "no declared candidate", extra={"bench/influxdb.candidate.yaml": "x: 1"})
cur = [ln for ln in main.split("\n") if ln.startswith("version:")][0]
cand = main.replace(cur, 'version: "99.0.1"')
flag("a full file that changes nothing else", dict(GOOD, config_change="x"), "remove the file", extra={"bench/ga_manager.candidate.yaml": cand})
more = cand + "\nwatchdog: http://x\n"
flag("a config change without its reason", GOOD, "without config_change", extra={"bench/ga_manager.candidate.yaml": more})
rc, out = val({"ga_manager": dict(GOOD, config_change="new watchdog")}, extra={"bench/ga_manager.candidate.yaml": more})
check(rc == 0, "MUST-PASS a declared config change", out)
img = [ln for ln in main.split("\n") if ln.startswith("image:")][0]
flag("another image", dict(GOOD, config_change="x"), "another add-on", extra={"bench/ga_manager.candidate.yaml": cand.replace(img, "image: ghcr.io/greenautarky/other-{arch}")})
flag("file and declaration disagree", dict(GOOD, version="99.0.2", config_change="x"), "says version", extra={"bench/ga_manager.candidate.yaml": more})
rc, out = val({}, raw="{")
check(rc == 2, "MUST-FAIL-CLOSED unreadable declarations", out)
rc, out = run("validate", "--root", W / "none")
check(rc == 2, "MUST-FAIL-CLOSED no store", out)
t = tree({"ga_manager": GOOD})
b = W / "bench"
rc, out = run("build", "--root", t, "--out", b)
check(rc == 0, "build", out)
d = subprocess.run(["diff", "-rq", str(t), str(b)], capture_output=True, text=True).stdout
check(d.count("\n") == 1 and "ga_manager/config.yaml" in d, "the built tree differs from main in one file", d)
d = subprocess.run(["diff", str(t / "ga_manager/config.yaml"), str(b / "ga_manager/config.yaml")], capture_output=True, text=True).stdout
changed = [ln for ln in d.split("\n") if ln[:2] in ("< ", "> ")]
check(len(changed) == 2 and changed[0].startswith("< version:") and "99.0.1" in changed[1], "and that file in its version line only", d)
check(run("check", "--root", t, "--bench", b)[0] == 0, "MUST-PASS check of the generated tree")
(b / "influxdb/config.yaml").write_text((b / "influxdb/config.yaml").read_text() + "\n# x\n")
rc, out = run("check", "--root", t, "--bench", b)
check(rc == 1 and "influxdb/config.yaml" in out, "MUST-FLAG a hand edit of another add-on", out)
shutil.rmtree(b); run("build", "--root", t, "--out", b); (b / "extra").mkdir(); (b / "extra/config.yaml").write_text("slug: x")
check(run("check", "--root", t, "--bench", b)[0] == 1, "MUST-FLAG an added add-on")
shutil.rmtree(b); run("build", "--root", t, "--out", b); shutil.rmtree(b / "mosquitto")
check(run("check", "--root", t, "--bench", b)[0] == 1, "MUST-FLAG a removed add-on")
check(run("check", "--root", t, "--bench", t)[0] == 1, "MUST-FLAG bench that is only main although a candidate is declared")
print(f"bench_store: {n} checks, {fails} failed")
sys.exit(2 if n < 31 else 1 if fails else 0)
