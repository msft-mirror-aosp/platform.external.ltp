#!/bin/bash
# Entry point for external_updater post-update hook.
# Handles both git merge (no backup path) and archive update (with backup path).
#
# $1: new_project_path
# $2: old_project_path (optional, present in archive/tarball update mode)

NEW_PATH="$1"
OLD_PATH="$2"

if [ -z "$NEW_PATH" ]; then
  echo "Error: new_project_path is required."
  exit 1
fi

# 1. Restore AOSP-specific android/ directory and custom runlists if we are in archive update mode
if [ -n "$OLD_PATH" ]; then
  echo "Restoring android/ directory from $OLD_PATH to $NEW_PATH..."
  if [ -d "$OLD_PATH/android" ]; then
    # Copy the android directory recursively
    mkdir -p "$NEW_PATH"
    cp -r "$OLD_PATH/android" "$NEW_PATH/"
    echo "android/ directory restored."
  else
    echo "Error: Source android/ directory not found in $OLD_PATH"
    exit 1
  fi

  # Restore custom runlists
  CUSTOM_RUNLISTS=("fcntl-locktests_android" "sched_low_mem")
  for runlist in "${CUSTOM_RUNLISTS[@]}"; do
    src_runlist="$OLD_PATH/runtest/$runlist"
    dst_runlist="$NEW_PATH/runtest/$runlist"
    if [ -f "$src_runlist" ]; then
      echo "Restoring custom runlist: $runlist..."
      mkdir -p "$(dirname "$dst_runlist")"
      cp "$src_runlist" "$dst_runlist"
    fi
  done
else
  echo "Git merge mode detected. android/ directory and runlists should be preserved."
fi
