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
    d = tempfile.mkdtemp()
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
    global RENDER_RC
    RENDER_RC = subprocess.run(["bash", "-c", script], cwd=f"{d}/repo", env=env, capture_output=True).returncode
    txt = open(out).read() if os.path.exists(out) else ""  # zero-inspected exits before writing
    outs = dict(l.split("=", 1) for l in txt.splitlines() if "=" in l)
    g = subprocess.run(["bash", "-c", guard["run"]], env=dict(env, UNREADABLE=outs.get("unreadable", "")), capture_output=True, text=True)
    return g.returncode, outs.get("unreadable", "")

# Why the 3 private sources are NOT in the MAP (#1594, decided 2026-11-09):
# this token cannot read them; they push via lockstep at publish time instead.
# The sweep covers only the public sources, so 2/2 readable is the green state.
PRIVATE = ["ga_default_addon", "ga_hmvapp_addon", "ga_manager"]
PUBLIC = ["influxDBv1", "ga_tailscale"]
rc, u = run(PUBLIC); ok1 = rc == 0 and u == ""
print(f"2/2 public readable -> guard rc={rc} unreadable='{u}'", "OK" if ok1 else "FAIL")
rc, u = run(["influxDBv1"]); ok2 = rc != 0 and "ga_tailscale" in u
print(f"public source unreadable -> guard rc={rc} unreadable='{u.strip()}'", "OK" if ok2 else "FAIL")
run([]); ok3 = RENDER_RC != 0  # render step itself fails closed on zero inspected
print(f"nothing readable -> render rc={RENDER_RC}", "OK" if ok3 else "FAIL")
# private sources must stay out of the MAP (they would end the run RED again)
mapped = [r for r in PRIVATE if f":{r}:" in render["run"]]
ok4 = not mapped
print(f"private sources in MAP: {mapped}", "OK" if ok4 else "FAIL")
sys.exit(0 if ok1 and ok2 and ok3 and ok4 else 1)
