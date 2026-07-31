# Release preflight — symbiotica

Read this before bumping anything. This repo does not release the way the
generic flow assumes, and two of the differences will ship something you did not
intend.

## Publishing the GitHub release is what ships it

`.github/workflows/publish_action.yml` fires when a **GitHub release is
published**, and publishes to the public ComfyUI Registry as publisher
`razvan-symbiotica`. Consequences:

- Merging a version bump publishes nothing on its own. The version line says
  what the next release will be called; publishing the release is what sends it.
- So the release page is not documentation any more — creating it is the act
  that reaches every user who installs this pack.
- `workflow_dispatch` also publishes, on whatever `main` currently holds.

Whatever version sits in `pyproject.toml` at the moment the release is published
is the version the registry receives — the release notes and tag are not
consulted. Check they agree before publishing.

Through `2.43.0` this fired on any push to `main` touching `pyproject.toml`, so
editing that line *was* the publish. Older notes and habits assume that.

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

## Check what merged since the last release, and whether anyone read it

Reviewing the release diff itself is close to useless here: code reaches `main`
through PRs, so by the time a release runs the only pending change is the
version line. The code that is about to be published merged earlier, possibly
weeks earlier, possibly unread. That is the gap to close.

List the PRs this release will publish and how each was reviewed:

```bash
PREV=$(git tag --list 'v*' --sort=-version:refname | head -1)
BOUNDARY=${PREV:-$(git log --format=%H -G'^version = ' -- pyproject.toml | head -1)}
for n in $(git log "$BOUNDARY"..HEAD --oneline | grep -oE '#[0-9]+' | tr -d '#' | sort -u); do
  gh pr view "$n" --json number,title,author,reviewDecision --jq '
    (.reviewDecision // "") as $r
    | "  #\(.number) by \(.author.login)  [\(if $r == "" then "UNREVIEWED" else $r end)]  \(.title[0:40])"'
done
```

Every commit, not just merge commits: a squash merge leaves no merge commit, so
`--merges` reports an empty list for a branch that squashed. That reads exactly
like "nothing to review" and hides the case this check exists to catch.

`BOUNDARY` is the previous release tag; before tags existed it falls back to the
last commit that changed the version line.

Anything marked `UNREVIEWED` is code about to reach every user of the pack that
no second person has read. That is not automatically a stop — a one-line fix
from a maintainer is different from a first contribution from outside. Judge it
on what the PR actually contains:

- **From outside the org, or large, or touching node inputs/outputs/ids** — run
  `/code-review` over it (`gh pr diff <n>`) before continuing, and fix or drop
  anything confirmed. Do not publish an unread contribution.
- **Small, from a maintainer, already covered by tests** — note it in the
  release notes and carry on.

`CHANGES_REQUESTED` is a stop regardless: the release would ship a change
someone objected to.

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

### The semver boundary is behind us

The last semver release was `2.43.0`; the first calendar release was
`2026.7.1`. Every calendar version outranks every semver one
(`2026.7.1` > `2.43.0`), so **a semver-numbered release now would register as
older than what is already out** and would not reach anyone.

If a branch predating the switch still carries a semver bump, renumber it to the
current calendar version before merging. Do not "finish the 2.x line".

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
