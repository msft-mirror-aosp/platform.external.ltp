#!/usr/bin/env python3
#
# Copyright 2026 - The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import sys
import os
import shutil
import subprocess

def has_docker():
    # Check if docker executable exists in system PATH
    if not shutil.which("docker"):
        return False
    # Check if we can run docker ps without issues (either natively or via sudo fallback)
    try:
        if subprocess.run(["docker", "ps"], capture_output=True, timeout=5).returncode == 0:
            return True
    except Exception:
        pass
    try:
        if subprocess.run(["sudo", "docker", "ps"], capture_output=True, timeout=5).returncode == 0:
            return True
    except Exception:
        pass
    return False

def main():
    if len(sys.argv) < 2:
        print("Usage: post_update.py <new_project_path> [old_project_path]")
        sys.exit(1)

    new_path = sys.argv[1]
    old_path = sys.argv[2] if len(sys.argv) > 2 else ""

    dst_android = os.path.join(new_path, "android")

    if old_path:
        print(f"Restoring android/ directory from {old_path} to {new_path}...")
        src_android = os.path.join(old_path, "android")
        if not os.path.exists(src_android):
            print(f"Error: Source android/ directory {src_android} does not exist.")
            sys.exit(1)
        # Copy the directory recursively
        shutil.copytree(src_android, dst_android, dirs_exist_ok=True)
        print("android/ directory successfully restored.")
    else:
        print("Git merge mode detected. android/ directory is preserved, skipping restore.")

    # Run gen_android_build.py to regenerate blueprint files
    gen_build_script = os.path.join(dst_android, "tools", "gen_android_build.py")
    if os.path.exists(gen_build_script):
        if has_docker():
            print("Triggering Android build blueprint regeneration...")
            subprocess.run(["python3", gen_build_script, "--update"], check=True)
        else:
            print("Warning: Docker is not available on this host. "
                  "Skipping Soong blueprint regeneration (this is expected on restricted automated update runners).")
    else:
        print(f"Warning: Unified build script not found at {gen_build_script}. Skipping regeneration.")

if __name__ == "__main__":
    main()
