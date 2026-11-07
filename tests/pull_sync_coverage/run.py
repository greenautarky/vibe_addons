#!/usr/bin/env python3
"""store-pull-sync must end RED when a source is unreadable (#1594).

Runs the LIVE workflow's render step and guard step (extracted from the YAML,
never a copy) with a fake `gh`. Fails if either step cannot be found.
"""
import os, shutil, subprocess, sys, tempfile, yaml
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
wf = yaml.safe_load(open(f"{ROOT}/.github/workflows/store-pull-sync.yml"))
steps = wf["jobs"]["pull-sync"]["steps"]
def step(name_part):
    m = [s for s in steps if name_part in s.get("name", "")]
    if len(m) != 1:
        sys.exit(f"FAIL: step '{name_part}' not found exactly once")
    return m[0]
render, guard = step("Render each add-on"), step("Fail if any add-on")
CFG = "name: x\nversion: 1.0.0\nslug: x\n"

def run(readable):
    d = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "."))
    os.makedirs(f"{d}/bin"); out = f"{d}/out"
    open(f"{d}/bin/gh", "w").write(
        '#!/bin/bash\ncase "$*" in\n' +
        "".join(f'*/{r}/contents/*) printf %s {__import__("base64").b64encode(CFG.encode()).decode()};;\n' for r in readable) +
        '*) exit 1;;\nesac\n')
    os.chmod(f"{d}/bin/gh", 0o755)
    env = dict(os.environ, PATH=f"{d}/bin:{os.environ['PATH']}", GITHUB_OUTPUT=out,
               ONLY="", OWNER="o", GH_TOKEN="x")
    script = render["run"].replace("/tmp/", d + "/")
    # renderer + store dirs come from the repo checkout
    shutil.copytree(ROOT, f"{d}/repo", ignore=shutil.ignore_patterns(".git"))
    subprocess.run(["bash", "-c", script], cwd=f"{d}/repo", env=env, capture_output=True)
    outs = dict(l.split("=", 1) for l in open(out).read().splitlines() if "=" in l)
    g = subprocess.run(["bash", "-c", guard["run"]], env=dict(env, UNREADABLE=outs.get("unreadable", "")), capture_output=True, text=True)
    return g.returncode, outs.get("unreadable", "")

allsrc = ["ga_default_addon", "ga_hmvapp_addon", "ga_manager", "influxDBv1", "ga_tailscale"]
rc, u = run(allsrc);                    ok1 = rc == 0 and u == ""
print(f"all 5 readable -> guard rc={rc} unreadable='{u}'", "OK" if ok1 else "FAIL")
rc, u = run(["influxDBv1", "ga_tailscale"]); ok2 = rc != 0 and "ga_manager" in u
print(f"2 of 5 readable -> guard rc={rc} unreadable='{u.strip()}'", "OK" if ok2 else "FAIL")
sys.exit(0 if ok1 and ok2 else 1)
