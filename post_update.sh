#!/bin/bash
# Entry point for external_updater post-update hook.
# Handles both git merge (no backup path) and archive update (with backup path).

if [ -z "$2" ]; then
  python3 "$1/android/tools/post_update.py" "$1"
else
  python3 "$2/android/tools/post_update.py" "$1" "$2"
fi
