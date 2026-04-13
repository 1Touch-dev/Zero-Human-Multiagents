#!/usr/bin/env bash
# Used by paperclip-uimodifi-preview.service — fails fast if repo is not on the preview branch.
set -euo pipefail
REPO_ROOT="${PAPERCLIP_PREVIEW_REPO:-/home/ubuntu/Zero-Human-Multiagents-Dev-worktrees/paperclipuimodifi}"
EXPECTED_BRANCH="${PAPERCLIP_PREVIEW_BRANCH:-PaperclipUimodifi}"
if [[ "${PAPERCLIP_PREVIEW_SKIP_BRANCH_CHECK:-0}" == "1" ]]; then
  exit 0
fi
cd "$REPO_ROOT"
cur="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
if [[ "$cur" != "$EXPECTED_BRANCH" ]]; then
  echo "paperclip-uimodifi-preview: git branch is '${cur}', expected '${EXPECTED_BRANCH}'. Checkout the branch or set PAPERCLIP_PREVIEW_SKIP_BRANCH_CHECK=1 on the service." >&2
  exit 1
fi
