# LTP Local Patches

This directory contains local patches applied to the Android LTP repository on top of the upstream base version.

## Base Commit
These patches are based on the upstream LTP commit: **8cd7644a52e348393d453d0ec5bf9424ea31a4cc** (merged on May 17, 2026).

## Naming Convention
Patches are organized by theme and numbered sequentially:
- `16K-XXXX.patch`: Modifications related to 16KB page size emulation on x86_64.
- `EAS-XXXX.patch`: Energy Aware Scheduling tests (local additions).
- `LAPI-XXXX.patch`: Linux API compatibility and fallback definitions.
- `LIB-XXXX.patch`: LTP library and helper function modifications.
- `SYS-XXXX.patch`: Specific syscall and controller test fixes.

## AOSP-Specific Files and Diffs with Upstream
When comparing the AOSP LTP repository with clean upstream, several differences exist due to Android-specific packaging and platform requirements.

### Untracked/Android-Only Files
These files are kept in the AOSP repository but do not exist in the upstream LTP repository:
1.  **`Android.bp`, `testcases/Android.bp`, `gen.bp`**: Soong build configuration files. `gen.bp` is auto-generated to compile LTP modules.
2.  **`android/`**: Contains Android-specific scripts, tools, skip lists (e.g., `skipped-tests.txt`), and Docker environment definitions.
3.  **`METADATA`, `OWNERS`, `TEST_MAPPING`**: AOSP meta-configuration files. `TEST_MAPPING` defines presubmit/postsubmit tests for VTS.
4.  **`LICENSE`, `NOTICE`, `MODULE_LICENSE_GPL`**: Compliance and legal notices.
5.  **`runtest/fcntl-locktests_android`, `runtest/sched_low_mem`**: Custom Android-specific test run lists (Runlists) defining exactly which test commands to execute in VTS testing.
6.  **`m4/ltp-pwritev2.m4`, `m4/ltp-syncfs.m4`**: Custom autoconf macros.

### Deleted Submodules
Upstream LTP uses git submodules for some external tools. Since AOSP repository does not support git submodules, the following directories are deleted in AOSP:
- `testcases/kernel/mce-test`
- `tools/kirk/kirk-src`
- `tools/ltx/ltx-src`
- `tools/sparse/sparse-src`

## Purpose
These patches are maintained to allow automated synchronization with upstream releases using `go/external-updater` while preserving necessary Android-specific modifications.
