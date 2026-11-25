# bench: candidates for bench devices

`candidates.json` declares add-on versions that bench devices may install before
the field store (main) carries them. `scripts/bench_store.py build` produces the
tree of branch `bench` = main + these candidates; a workflow keeps the branch
current. A bench device is seeded with a clone of that branch (same repository
URL, so the same slugs); see ga-ihost-docs RELEASE-ARTIFACTS-AND-CANDIDATES.md.

- Never edit branch `bench` by hand, never point a field device at it.
- A candidate needs: version (newer than main), reason, until (at most 30 days),
  the published digest per architecture.
- `<store dir>.candidate.yaml` (full store entry) only if the entry changes beyond
  its version; then `config_change` must say why. No file here may be named
  `config.*`: the Supervisor would read it as an add-on.
- Releasing = the version moves on main; the candidate is then stale and must go.
