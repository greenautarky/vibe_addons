#!/usr/bin/env python3
"""Fixtures for scripts/check_store_images.py — must_fail and must_pass.

Imports the LIVE gate from scripts/ (never a copy) and fails, not skips, if it
cannot. Each case is a tiny store tree written to a temp directory.
"""
import importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "..", "scripts", "check_store_images.py")
if not os.path.isfile(GATE):
    sys.exit(f"FAIL: live gate not found at {GATE}")
spec = importlib.util.spec_from_file_location("check_store_images", GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

OK = "ghcr.io/greenautarky/ga_x-{arch}"

MUST_FAIL = {
    "foreign registry": {"a/config.yaml": "slug: a\nimage: docker.io/evil/a-{arch}\n"},
    "other ghcr owner": {"a/config.yaml": "slug: a\nimage: ghcr.io/evil/a-{arch}\n"},
    "look-alike owner": {"a/config.yaml": "slug: a\nimage: ghcr.io/greenautarky-evil/a-{arch}\n"},
    "owner as prefix of path": {"a/config.yaml": "slug: a\nimage: ghcr.io/greenautarky/../evil/a\n"},
    "nested repository path": {"a/config.yaml": "slug: a\nimage: ghcr.io/greenautarky/x/evil\n"},
    "registry host look-alike": {"a/config.yaml": "slug: a\nimage: ghcr.io.evil.com/greenautarky/a\n"},
    "no image key": {"a/config.yaml": "slug: a\nversion: 1.0.0\n"},
    "empty image": {"a/config.yaml": "slug: a\nimage: ''\n"},
    "json config, foreign image": {"a/config.json": '{"slug": "a", "image": "quay.io/evil/a"}'},
    "ships a Dockerfile": {"a/config.yaml": f"slug: a\nimage: {OK}\n", "a/Dockerfile": "FROM scratch\n"},
    "ships build.yaml": {"a/config.yaml": f"slug: a\nimage: {OK}\n", "a/build.yaml": "build_from: {}\n"},
    "one good, one bad": {"a/config.yaml": f"slug: a\nimage: {OK}\n",
                          "b/config.yaml": "slug: b\nimage: docker.io/evil/b\n"},
    "unparseable config": {"a/config.yaml": "slug: [unclosed\n"},
    "empty store": {"README.md": "nothing here\n"},
}
MUST_PASS = {
    "yaml with arch": {"a/config.yaml": f"slug: a\nimage: {OK}\n"},
    "json with arch": {"a/config.json": '{"slug": "a", "image": "ghcr.io/greenautarky/ga_zigbee2mqtt-{arch}"}'},
    "tag pinned": {"a/config.yaml": "slug: a\nimage: ghcr.io/greenautarky/ga_x:1.2.3\n"},
    "digest pinned": {"a/config.yaml": "slug: a\nimage: ghcr.io/greenautarky/ga_x@sha256:" + "0" * 64 + "\n"},
    "tests/scripts/tools ignored": {"a/config.yaml": f"slug: a\nimage: {OK}\n",
                                    "tests/f/config.yaml": "image: docker.io/evil/x\n",
                                    "scripts/Dockerfile": "FROM scratch\n"},
}


def build(tree):
    d = tempfile.mkdtemp(prefix="store-image-gate-")
    for rel, body in tree.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf8") as fh:
            fh.write(body)
    return d


bad = 0
for name, tree in MUST_FAIL.items():
    seen, errors = gate.check(build(tree))
    ok = bool(errors)
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'} must_fail  {name}: {errors[:1]}")
for name, tree in MUST_PASS.items():
    seen, errors = gate.check(build(tree))
    ok = not errors and seen >= 1
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'} must_pass  {name}: seen={seen} {errors[:1]}")
print(f"store image gate fixtures: {len(MUST_FAIL)} must_fail, {len(MUST_PASS)} must_pass, {bad} failures")
sys.exit(1 if bad else 0)
