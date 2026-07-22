# Release preflight — symbiotica

Read this before bumping anything. This repo does not release the way the
generic flow assumes, and two of the differences will ship something you did not
intend.

## The version line is the shipped artifact, not the tag

`.github/workflows/publish_action.yml` fires on **any push to `main` that
touches `pyproject.toml`** and publishes to the public ComfyUI Registry as
publisher `razvan-symbiotica`. Consequences:

- Editing `version` in `pyproject.toml` and merging is a **publish to every
  ComfyUI user who installs this pack**. It is not bookkeeping.
- A version bump on a branch publishes nothing. If a release has to actually
  ship, the commit has to reach `main`.
- Tags are documentation here. The repo had none at all through v2.40.0.

Before bumping, confirm the release is meant to reach the registry. If it is
not, stop — commit the work without touching `version`.

## Check no open PR already claims a version

The registry rejects a version it has already seen, and two branches bumping to
the same number means whichever merges second publishes nothing.

```bash
gh pr list --state open --json number,title,headRefName
for br in $(gh pr list --state open --json headRefName --jq '.[].headRefName'); do
  printf '%s: ' "$br"
  git show "origin/$br:pyproject.toml" 2>/dev/null | grep '^version' || echo '(no bump)'
done
```

If an open PR holds a higher version than the one about to be released, decide
the merge order deliberately — see the ordering hazard below.

## Versioning: calver, with a caveat that matters

The scheme is `calver-build` — `YYYY.M.BUILD`, unpadded month, build resets each
month (`2026.7.1`, `2026.7.2`, … then `2026.8.1`).

It is the **only** calver format the registry accepts. The registry requires a
three-part semantic version, and semver forbids leading zeros, so `2026.07.1`,
`2026.07`, and `2026.07.22` are all invalid. Do not switch to a padded or
two-part form.

**What calver costs here:** the registry treats a major-version bump as the
signal that an update contains breaking changes — changed node inputs, changed
outputs, renamed node ids. Under calver the major is the year. It bumps every
January whether or not anything broke, and it will never bump for a breaking
change in June. That signal is gone.

So when a release changes node inputs, outputs, or ids, **say so at the top of
the release notes in plain language**. Nothing in the version number will.

### Ordering hazard when migrating off semver

The last semver release was `2.40.0`. Every calver version outranks it
(`2026.7.1` > `2.43.0`), so once a calver version ships, **any later semver
release is a downgrade the registry will treat as older**. Before the first
calver release, either land every in-flight semver bump first, or convert those
branches to calver.

## Tests

Both suites must pass. `test` in `release.config.json` runs them, and skips the
JS half automatically on branches predating it.

- `pytest tests/` — **not** `python -m pytest`. The repo has a top-level `py/`
  directory that shadows the `py` module pytest itself imports; `python -m`
  fails with `AttributeError: module 'py' has no attribute 'path'` and looks
  like a broken suite when it is a name collision.
- `node --import ./tests/js/register_hooks.mjs --test 'tests/js/*.test.mjs'` —
  the directory form (`--test tests/js/`) fails on Node 25.

## Node registration still works

`__init__.py` imports every module under `py/` and catches failures per module,
so a broken file drops its nodes silently with only a console traceback. A
release can lose nodes without failing a single test. Check the count did not
drop:

```bash
python3 -c "
import importlib, sys; sys.path.insert(0, '..')
m = importlib.import_module('<this-dir-name>')
print(len(m.NODE_CLASS_MAPPINGS), 'nodes registered')"
```

Run it from the parent of the checkout. Outside a real ComfyUI the modules that
import `folder_paths` fail by design — compare against the previous release's
count rather than expecting them all to load.

## Docs

`README.md` lists every node by display name. A release adding or renaming a
node has to update it, or users get a pack whose contents do not match its
documentation.
