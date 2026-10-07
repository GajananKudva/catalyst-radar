#!/usr/bin/env bash
# Publish ./data as a single-commit `data` branch (force-push, so the repo never bloats).
set -euo pipefail
DATA_DIR="${DATA_DIR:-data}"
BRANCH="${DATA_BRANCH:-data}"
REMOTE="${PUBLISH_REMOTE:-}"
if [ -z "$REMOTE" ]; then
  : "${GITHUB_TOKEN:?GITHUB_TOKEN is required}"
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  REMOTE="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
fi

cd "$DATA_DIR"
find . -name "*.tmp" -delete
rm -rf .git
git init -q
git checkout -q -b "$BRANCH"
git config user.name "radar-bot"
git config user.email "radar-bot@users.noreply.github.com"
git add -A
git commit -q -m "data: $(date -u +'%Y-%m-%dT%H:%MZ')"
git push -q -f "$REMOTE" "$BRANCH:$BRANCH"
rm -rf .git
echo "published $(find . -type f | wc -l) files to branch '$BRANCH'"
