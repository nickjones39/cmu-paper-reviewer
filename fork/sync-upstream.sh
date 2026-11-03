#!/usr/bin/env bash
# Merge the latest prometheus-eval/cmu-paper-reviewer into this fork's main.
#
#   fork/sync-upstream.sh          # merge upstream/main into main, run the fork's tests
#   fork/sync-upstream.sh --push   # ...and push main to origin if the tests pass
#
# Merge (not rebase) keeps the fork's history stable and means each conflict is
# resolved once; `git rerere` replays that resolution if it ever recurs.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

UPSTREAM_URL="https://github.com/prometheus-eval/cmu-paper-reviewer.git"
PUSH=0
[[ "${1:-}" == "--push" ]] && PUSH=1

if ! git remote get-url upstream >/dev/null 2>&1; then
  git remote add upstream "$UPSTREAM_URL"
  git remote set-url --push upstream DISABLED-push-to-fork-only
fi
git config rerere.enabled true
git config rerere.autoupdate true

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Working tree has uncommitted changes; commit or stash them first." >&2
  exit 1
fi

git fetch upstream
git checkout main
git pull --ff-only origin main 2>/dev/null || true

BEHIND=$(git rev-list --count main..upstream/main)
if [[ "$BEHIND" == 0 ]]; then
  echo "Already up to date with upstream/main."
  exit 0
fi
echo "Merging $BEHIND upstream commit(s)…"
git log --oneline main..upstream/main | head -20

if ! git merge --no-edit upstream/main; then
  echo
  echo "Merge conflicts. The fork's changes to upstream files are only the lines"
  echo "tagged '# [local-models fork]' (see LOCAL_MODELS.md → Hook points)."
  echo "Keep upstream's version of each conflicted hunk, re-add the tagged lines, then:"
  echo "  git add -A && git commit --no-edit && python -m pytest tests/localmodels -q"
  exit 1
fi

PY=python
[[ -x .venv/bin/python ]] && PY=.venv/bin/python
if ! "$PY" -m pytest tests/localmodels -q; then
  echo
  echo "Merged, but the fork's tests fail: upstream moved code a hook depends on."
  echo "Fix it (LOCAL_MODELS.md → Hook points), commit, then push. Not pushed."
  exit 1
fi

if [[ "$PUSH" == 1 ]]; then
  git push origin main
else
  echo "Merged and tested. Push with: git push origin main"
fi
