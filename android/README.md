VTS LTP Workflow
================

A Guide to Developing LTP for VTS/Android

What is LTP?
------------

[Github](https://github.com/linux-test-project/ltp) (upstream)

LTP (Linux Test Project) is a suite of tests that covers both kernel interfaces
and userspace functionality (glibc, commonly used binaries, etc).  For the
purposes of Android the userspace functionality testing is of less importance
and in fact much of it must be disabled, given the functionality is not
available in Android.

As of mid-2018 there are on the order of 900 tests executed in VTS. Most tests
are run in both 32-bit and 64-bit mode. Many more are available but currently
disabled due to either being broken or not applicable on Android.

How is LTP Run in VTS?
----------------------

The LTP source is located at external/ltp in the Android tree. This is not an
exact mirror of upstream, there are outstanding changes to LTP for it to work
on Android which have not yet been pushed upstream. In addition to the LTP
source there is also the VTS wrapper around it. This is located at
test/vts-testcase/kernel/ltp. Some noteworthy directories/files:

* `external/ltp/android/`: Contains Android-specific files, aside from Android.[bp, mk] at top level.
* `external/ltp/android/Android.ltp.mk`: Lists build rules for the LTP modules built under make. This file gets auto-generated by android/tools/gen_android_build.sh.
* `external/ltp/gen.bp`: Lists build rules for the LTP modules built under Soong. This file gets auto-generated by android/tools/gen_android_build.sh.
* `external/ltp/android/ltp_package_list.mk`: Lists all tests that will get pulled into VTS - VTS depends on this list. This file gets auto-generated by android/tools/gen_android_build.sh.
* `external/ltp/android/tools/disabled_tests.txt`: Lists tests which cannot or should not be compiled for Android. This file is read by gen_android_build.sh during LTP upgrades to produce *.mk files required to build LTP for Android.
* `external/ltp/testcases`: Source for LTP tests. Among the most important for the purposes of Treble are those in external/ltp/testcases/kernel/syscalls.
* `test/vts-testcase/kernel/ltp/testcase/tools/configs/disabled_tests.py`: Any test listed here will not be run in VTS, despite being compiled.
* `test/vts-testcase/kernel/ltp/testcase/tools/configs/stable_tests.py`: Any test listed here will run as part of the vts_ltp_test_arm/vts_ltp_test_arm_64 modules.

Running LTP through atest
-------------------------
You can run LTP tests with atest, which handles all the setup and build steps.

To run all 32 bit LTP tests:
* `atest vts_ltp_test_arm`

To run all 64 bit LTP tests:
* `atest vts_ltp_test_arm_64`

To run a single test:
* `atest vts_ltp_test_arm:dio.dio13_32bit`

Running LTP through VTS
-----------------------
To run VTS LTP it must first be built. VTS is not device specific, you need not
compile it specifically for the device you wish to run it on, assuming it is
the same architecture.

* `. build/envsetup.sh`
* `lunch`
* `make -j vts`

Then open vts-tradefed and run the VTS stable set:
* `vts-tradefed`
* `vts-tf > run vts-kernel -m vts_ltp_test_arm`

If you regularly work with multiple devices it may be useful to specify the
specific device you wish to run VTS on via the serial number:
* `vts-tf > run vts-kernel -m vts_ltp_test_arm -s 000123456789`

Or a specific test within the stable set:
* `vts-tf > run vts-kernel -m vts_ltp_test_arm -t dio.dio13_32bit`

Running LTP Directly
--------------------

Running LTP tests within VTS can be quite cumbersome, especially if you are
iterating a lot trying to debug something. Build and run LTP tests faster by
doing

* `external/ltp$ mma`
* `external/ltp$ adb sync data`

The test cases will be located at /data/nativetest{64,}/ltp/testcases/bin.

Sometimes you need to perform this step after syncing:
* `external/ltp$ git clean -x -f -d`
Otherwise, build will fail.

In order to simulate the exact environment that VTS will be creating for each
of these tests, you can set the following environment variables before you run
the test. This is very useful if the test itself depends on some of these
variables to be set appropriately.

* `adb root && adb shell`

In the root shell on device:
* `mkdir -p /data/local/tmp/ltp/tmp/ltptemp`
* `mkdir -p /data/local/tmp/ltp/tmp/tmpbase`
* `mkdir -p /data/local/tmp/ltp/tmp/tmpdir`
* `restorecon -F -R /data/local/tmp/ltp`
* `export TMP=/data/local/tmp/ltp/tmp`
* `export LTPTMP=/data/local/tmp/ltp/tmp/ltptemp`
* `export LTP_DEV_FS_TYPE=ext4`
* `export TMPBASE=/data/local/tmp/ltp/tmp/tmpbase`
* `export TMPDIR=/data/local/tmp/ltp/tmp/tmpdir`
* `export LTPROOT=/data/local/tmp/ltp`

For running 64-bit tests:
* `export PATH=/data/nativetest64/ltp/testcases/bin:$PATH`

Or For running 32-bit tests:
* `export PATH=/data/nativetest/ltp/testcases/bin:$PATH`

How do I enable or disable tests from the LTP build?
----------------------------------------------------

Tests are disabled from the LTP build by adding them to
external/ltp/android/tools/disabled_tests.txt. Many tests have been added to
this file over time. Some of them are not applicable to Android and therefore
should not be built. Others were disabled here because they were failing at one
point in time for reasons unknown.

To make a change to what is built in LTP, add or remove an entry in this file,
and then update the Android-specific build files for LTP, mentioned above:

* `external/ltp/android/Android.ltp.mk`, for LTP modules built in make
* `external/ltp/gen.bp`, for LTP modules built in soong
* `external/ltp/android/ltp_package_list.mk`, which lists all LTP modules that get pulled into VTS

Update these files by running the script located at
external/ltp/android/tools/gen_android_build.sh. Instructions for the script
are in external/ltp/android/how-to-update.txt.


How do I enable or disable tests from VTS LTP?
----------------------------------------------

In addition to whether modules are built in external/ltp, it is also necessary
to configure the VTS harness for LTP to determine which tests are in the stable
set, the staging set, or disabled. Note that being disabled in VTS does not
affect whether the test is built, but rather determines whether it is run at
all as part of the stable or staging sets.

The file test/vts-testcase/kernel/ltp/testcase/tools/configs/stable_tests.py
lists tests that will run as part of VTS (vts_ltp_test_arm/vts_ltp_test_arm_64).

When a test is enabled for the first time in VTS it should be in the staging
set. The behavior of the test will be observed over a period of time and ensure
the test is reliable. After a period of time (a week or two) it will be moved
to the stable set.

Tests that will never be relevant to Android should be disabled from the build
in external/ltp. Tests that are (hopefully) temporarily broken should be
runtime disabled in VTS. The staging and stable sets should normally all be
passing. If something is failing there it should either be fixed with priority
or disabled until it can be fixed.

If the runtime of LTP changes significantly be sure to update the runtime-hint
and test-timeout parameters to VTS in
`test/vts-testcase/kernel/ltp/stable/AndroidTest.xml`.


How do I see recent VTS LTP results?
----------------------------------------------------------

The internal portal at go/vts11-dashboard shows results for the continuous VTS testing
done on internal devices.

Test results are also gathered by Linaro and may be seen
[here](https://qa-reports.linaro.org/android-lkft/).


Help! The external/ltp build is failing!
----------------------------------------

Try doing a make distclean inside of external/ltp. If an upgrade to LTP has
recently merged or the build files were recently updated, stale files in
external/ltp can cause build failures.


What outstanding issues exist?
------------------------------

The hotlist for LTP bugs is [ltp-todo](https://buganizer.corp.google.com/hotlists/733268).

When you begin working on an LTP bug please assign the bug to yourself so that
others know it is being worked on.


Testing x86_64
--------------

It is not advisable to run LTP tests directly on your host unless you are fully
aware of what the tests will do and are okay with it. These tests may
destabilize your box or cause data loss. If you need to run tests on an x86
platform and are unsure if they are safe you should run them in emulation, in a
virtualized environment, or on a dedicated development x86 platform.

To run LTP tests for x86 platform, you can do:
* `atest vts_ltp_test_x86`
* `atest vts_ltp_test_x86_64`


Sending Fixes Upstream
----------------------

The mailing list for LTP is located
[here](https://lists.linux.it/listinfo/ltp). Some standard kernel guidelines
apply to sending patches; they should be checkpatch (scripts/checkpatch.pl in
the kernel repository) clean and sent in plain text in canonical patch format.
One easy way to do this is by using git format-patch and git send-email.

There is an #LTP channel on freenode. The maintainer Cyril Hrubis is there (his
nick is metan).


Merging Fixes
------------------------

When possible please merge fixes upstream first. Then cherrypick the change
onto aosp/master in external/ltp.


Upgrade LTP to the latest upstream release
-------------------------------------------

LTP has three releases per year. Keeping the current project aligned with the
upstream development is important to get additional tests and bug-fixes.

### Merge the changes

AOSP external projects have a branch that track the changes to the upstream
repository, called `aosp/upstream-master`.
That branch is automatically updated with:

`repo sync .`

Create a new branch to work on the merge, that will contain the merge commit
itself and conflicts resolutions:

`repo start mymerge .`

Find the commit for the latest LTP release, for example

```
$ git log --oneline aosp/upstream-master
c00f96994 (aosp/upstream-master) openposix/Makefile: Use tabs instead of spaces
a90664f8d Makefile: Use SPDX in Makefile
0fb171f2b LTP 20210524
```

Force the creation of a merge commit (no fast-forward).

`git merge <release commit> --no-ff`

Fix all the merge conflicts ensuring that the project still builds, by
periodically running:

`git clean -dfx && make autotools && ./configure && make -j`

### Update the Android build targets

Building LTP with the Android build system requires the additional Android
build configuration files mentioned above.
A new LTP release may have disabled existing tests or enabled new ones, so the
Android build configurations must be updated accordingly.
This is done by the script `android/tools/gen_android_build.sh`:

`git clean -dfx && android/tools/gen_android_build.sh && git clean -dfx && mma .`

This command will possibly update the files `android/Android.ltp.mk`,
`android/ltp_package_list.mk` and `gen.bp`.

It's a good practice to create an explanatory commit message that presents the
differences in the test suite.
`android/tools/compare_ltp_projects.py` is a script that helps comparing the tests available in two different LTP folders.

LTP_NEW=$ANDROID_BUILD_TOP/external/ltp
LTP_OLD=/tmp/ltp-base
git archive aosp/master | tar -x -C $LTP_OLD
android/tools/compare_ltp_projects.py --ltp-new $LTP_NEW --ltp-old $LTP_OLD