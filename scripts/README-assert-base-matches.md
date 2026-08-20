# Wiring `assert_base_matches.py` into a publish workflow

Two scripts, one defect class, two halves:

| script | answers |
|---|---|
| `resolve_addon_base.py` | *which base did the add-on declare?* — makes the pipeline READ `build.yaml` instead of constructing a name |
| `assert_base_matches.py` | *did the image that came out actually derive from it?* — the half a resolver cannot cover |

The second exists because on 2026-08-20 a workflow declared one base and built
on another, and every guard in the chain reported a number instead of a
contradiction. Reading the declaration is not the same as proving it was used.

## Where it goes

**After the build, before the push.** Its whole value is refusing to publish an
image that was built on something nobody declared; run after the push and it
documents an accident instead of preventing one.

```yaml
      - name: Build (armv7)
        run: |
          BUILD_FROM="$(python3 scripts/resolve_addon_base.py \
                          --addon-dir "${{ matrix.addon }}" \
                          --arch armv7 --legacy-tag "${LEGACY_TAG}")"
          docker build --platform linux/arm/v7 \
            --build-arg "BUILD_FROM=${BUILD_FROM}" \
            -t "${IMAGE}:${VERSION}" "${{ matrix.addon }}"

      - name: Assert the image derives from what build.yaml declares
        run: |
          python3 scripts/assert_base_matches.py \
            --addon-dir "${{ matrix.addon }}" \
            --arch armv7 \
            --image "${IMAGE}:${VERSION}"

      - name: Push
        run: docker push "${IMAGE}:${VERSION}"
```

Do not compute `BUILD_FROM` twice with different expressions — resolve once,
build with it, assert against the declaration. The assertion deliberately
re-derives its expectation from `build.yaml` through the live resolver rather
than accepting a value handed to it by the build step, because an audit that
takes its expected value from the artifact under test is green by construction.

## What it costs per run

One `docker pull` of the declared base (tens of MB) and two `docker create` +
`docker cp` pairs. The images are never RUN — `docker create` materialises a
container filesystem without executing anything, so an armv7 image needs no
qemu/binfmt on an amd64 runner.

## Exit codes

| code | meaning | CI |
|---|---|---|
| 0 | declared and built agree | pass |
| 1 | they disagree — the defect this exists to catch | fail |
| 2 | could not check (no docker, image missing, no identity readable) | fail |

`2` is a failure on purpose. "Could not check" must never render as "checked and
fine".

## Flags worth knowing

- `--allow-point-drift` — downgrades a point-release disagreement (13.6 vs 13.1)
  to a warning. Do not reach for it to silence a red build; the default is strict
  because the real 2026-08-20 case is a point-release difference between two
  bases that agree on `/etc/os-release` down to the codename. Legitimate use:
  asserting against an image built well before the base tag last moved.
- `--check-lineage` — additionally requires the built image's `RootFS.Layers` to
  start with the declared base's. Exact derivation proof; misfires on squashed
  and multi-stage builds, so it is opt-in. Use it on add-ons with a plain
  single-stage Dockerfile, **and on any repo whose workflow pins the base by a
  different tag than `build.yaml` names** — see the blind spot below.

## Known blind spot: a dated pin vs. a floating tag

The default comparison asks *"is this the right OS?"*. It cannot see a divergence
where two different tags still resolve to the same OS version.

Measured example, 2026-08-20: one repo's `build.yaml` declared
`armv7-base-python:3.13-alpine3.22-2025.11.1` while its workflow pinned the
floating `3.13-alpine3.22`. Both tags resolved to the same digest that day, so
the identity comparison passes — correctly, today. It stops passing only once
upstream republishes the floating tag *and* the Alpine version changes with it.

A dated pin and a floating tag are two sources that happen to agree, which is not
the same as one source. Where the workflow names a tag `build.yaml` does not,
`--check-lineage` is the comparison that actually answers the question: identity
answers "the right OS", lineage answers "the right image".

The durable fix is not a flag — it is having one resolver and one declaration, so
there is no second source to compare against.
- `--no-pull` — do not refresh the declared base from its registry. Offline and
  debugging only; it makes the expectation as old as your local copy.

## Fixtures

`tests/assert_base_matches/run_fixtures.py`, run by the `store-sync-gate`
workflow on every change. It imports the live script by path and fails rather
than skips if it cannot find it. Both directions are mandatory — must-pass is
not padding, because an assertion that flags correct builds gets overridden by
reflex, which is a slower way of having no assertion at all.

The fixtures need no docker: the docker half reads bytes, the pure half decides,
and it is the deciding that has to be right. The file contents they compare were
read out of the real images, so the headline must-fail case is the actual
incident rather than an approximation of it.
