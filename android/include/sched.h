/*
 * Wrapper around Bionic's <sched.h>.
 *
 * The test binaries built from this tree are also run on older platforms,
 * e.g. the Android 14 system images used by
 * kernel/tests/tools/mixed_build_test_runner. Bionic declares
 * sched_setattr() and sched_getattr() since API 37, and calling them makes
 * the binaries depend on sched_{set,get}attr@LIBC_37, which older libc.so do
 * not provide ("CANNOT LINK EXECUTABLE").
 *
 * Hide the Bionic declarations so that include/lapi/sched.h provides its
 * syscall() based fallbacks instead (HAVE_SCHED_{SET,GET}ATTR are left
 * undefined in config.h).
 */
#ifndef LTP_ANDROID_SCHED_H
#define LTP_ANDROID_SCHED_H

#define sched_setattr ltp_hidden_bionic_sched_setattr
#define sched_getattr ltp_hidden_bionic_sched_getattr
#include_next <sched.h>
#undef sched_setattr
#undef sched_getattr

#endif /* LTP_ANDROID_SCHED_H */
