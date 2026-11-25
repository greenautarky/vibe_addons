#!/usr/bin/env python3
"""Branch `bench` = main + declared candidates. Build it, and check it.

  bench_store.py validate [--root DIR]               the declarations are valid against this main tree
  bench_store.py build --out DIR [--root DIR]        write the bench tree
  bench_store.py check --bench DIR [--root DIR]      DIR is exactly what build would write

Exit 0 ok, 1 finding, 2 could not judge. BENCH_TODAY overrides today (tests).
Zero candidates is valid: bench is then main.
"""
import argparse
import datetime
import filecmp
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile

import yaml

MAX_DAYS = 30
ARCHES = {"armv7", "aarch64"}
VERSION = re.compile(r"^(\s*version:\s*)([\"']?)([^\"'#\s]+)([\"']?)(.*)$")
IGNORE = {".git"}


def key(v):
    return [(0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"[.-]", str(v))]


def load(p):
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def validate(root):
    """-> (findings, {store dir: new config text})"""
    bad, out = [], {}
    try:
        decl = json.loads((root / "bench/candidates.json").read_text())["candidates"]
    except (OSError, ValueError, KeyError) as e:
        raise SystemExit(f"cannot read bench/candidates.json: {e}")
    today = datetime.date.fromisoformat(os.environ.get("BENCH_TODAY") or datetime.date.today().isoformat())
    for p in (root / "bench").rglob("config.*"):
        bad.append(f"{p.relative_to(root)}: a config.* file under bench/ would be read as an add-on")
    used = set()
    for d, c in decl.items():
        cfg = root / d / "config.yaml"
        say = lambda m, d=d: bad.append(f"{d}: {m}")
        if "/" in d or not cfg.is_file():
            say("no such store entry")
            continue
        main = load(cfg)
        ver, reason, until = str(c.get("version") or ""), str(c.get("reason") or "").strip(), str(c.get("until") or "")
        if not re.fullmatch(r"\d+(\.\d+)+(-\d+)?", ver):
            say(f"version {ver!r} is not a release version")
            continue
        if key(ver) <= key(main["version"]):
            say(f"stale: candidate {ver} is not newer than main {main['version']}; remove it")
        if not reason:
            say("no reason")
        try:
            u = datetime.date.fromisoformat(until) if re.fullmatch(r"\d{4}-\d\d-\d\d", until) else None
        except ValueError:
            u = None
        if u is None:
            say(f"until {until!r} is not a date YYYY-MM-DD")
        elif u < today:
            say(f"expired on {until}")
        elif u > today + datetime.timedelta(days=MAX_DAYS):
            say(f"until {until} is more than {MAX_DAYS} days ahead")
        dig = c.get("digests") or {}
        need = ARCHES & set(main.get("arch") or [])
        for a in sorted(need):
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(dig.get(a) or "")):
                say(f"no full digest for {a}")
        if not need or set(dig) - set(main.get("arch") or []):
            say(f"digests {sorted(dig)} do not fit arch {main.get('arch')}")
        full = root / "bench" / f"{d}.candidate.yaml"
        if full.is_file():
            used.add(full.name)
            text = full.read_text(encoding="utf-8")
            new = load(full)
            if str(new.get("version")) != ver:
                say(f"{full.name} says version {new.get('version')}, declared {ver}")
            changed = {k for k in set(main) | set(new) if main.get(k) != new.get(k)} - {"version"}
            if changed & {"slug", "image", "name"}:
                say(f"{full.name} changes {sorted(changed & {'slug', 'image', 'name'})}: that is another add-on")
            if changed and not str(c.get("config_change") or "").strip():
                say(f"{full.name} changes {sorted(changed)} without config_change")
            if not changed:
                say(f"{full.name} changes nothing but the version: remove the file")
        else:
            if c.get("config_change"):
                say(f"config_change is declared but bench/{d}.candidate.yaml is missing")
            lines = cfg.read_text(encoding="utf-8").split("\n")
            hits = [i for i, ln in enumerate(lines) if re.match(r"version:", ln)]
            if len(hits) != 1:
                say(f"{len(hits)} top-level version lines")
                continue
            lines[hits[0]] = VERSION.sub(lambda m: f"{m[1]}{m[2]}{ver}{m[4]}{m[5]}", lines[hits[0]])
            text = "\n".join(lines)
            new = yaml.safe_load(text)
            if str(new["version"]) != ver or {k: v for k, v in new.items() if k != "version"} != {k: v for k, v in main.items() if k != "version"}:
                say("the version line could not be replaced cleanly")
        out[d] = text
    for p in (root / "bench").glob("*.candidate.yaml"):
        if p.name not in used:
            bad.append(f"bench/{p.name}: belongs to no declared candidate")
    return bad, out


def build(root, out):
    bad, new = validate(root)
    if bad:
        return bad
    if out.exists() and any(p.name not in IGNORE for p in out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    shutil.copytree(root, out, ignore=shutil.ignore_patterns(".git", "__pycache__"), dirs_exist_ok=True, symlinks=True)
    for d, text in new.items():
        (out / d / "config.yaml").write_text(text, encoding="utf-8")
    return []


def diff(a, b):
    """Paths whose presence, type, mode or bytes differ."""
    def walk(r):
        return {str(p.relative_to(r)): p for p in r.rglob("*") if not (set(p.relative_to(r).parts) & (IGNORE | {"__pycache__"})) and (p.is_symlink() or p.is_file())}
    x, y = walk(a), walk(b)
    res = sorted(set(x) ^ set(y))
    for k in set(x) & set(y):
        if x[k].is_symlink() != y[k].is_symlink() or (os.stat(x[k]).st_mode ^ os.stat(y[k]).st_mode) & 0o111 or not filecmp.cmp(x[k], y[k], shallow=False):
            res.append(k)
    return sorted(res), len(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["validate", "build", "check"])
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    ap.add_argument("--out")
    ap.add_argument("--bench")
    a = ap.parse_args()
    root = pathlib.Path(a.root)
    try:
        entries = [p for p in root.glob("*/config.yaml")]
        if len(entries) < 5:
            raise SystemExit(f"only {len(entries)} store entries under {root}")
        if a.cmd == "validate":
            bad, new = validate(root)
        elif a.cmd == "build":
            bad, new = build(root, pathlib.Path(a.out)), validate(root)[1]
        else:
            new = validate(root)[1]
            with tempfile.TemporaryDirectory() as t:
                bad = build(root, pathlib.Path(t))
                if not bad:
                    d, n = diff(pathlib.Path(t), pathlib.Path(a.bench))
                    bad = [f"{k}: bench differs from main + candidates" for k in d]
                    if n < 20:
                        raise SystemExit(f"compared only {n} files")
    except SystemExit as e:
        print(f"bench_store: CANNOT JUDGE: {e}")
        return 2
    for b in bad:
        print(f"  FAIL  {b}")
    print(f"bench_store {a.cmd}: {len(new)} candidate(s) {sorted(new)}, {len(bad)} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
