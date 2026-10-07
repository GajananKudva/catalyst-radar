#!/usr/bin/env bash
# Copy the current contents of the `data` branch into ./data (if the branch exists).
set -euo pipefail
DATA_DIR="${DATA_DIR:-data}"
BRANCH="${DATA_BRANCH:-data}"
mkdir -p "$DATA_DIR"
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  git fetch -q --depth=1 origin "$BRANCH"
  git archive FETCH_HEAD | tar -x -C "$DATA_DIR"
  echo "restored $(find "$DATA_DIR" -type f | wc -l) files from branch '$BRANCH'"
else
  echo "branch '$BRANCH' does not exist yet - starting with empty data/"
fi
