// SPDX-License-Identifier: GPL-2.0
/*
 * Copyright (c) 2014 SUSE.  All Rights Reserved.
 * Copyright (c) 2018 CTERA Networks.  All Rights Reserved.
 *
 * Started by Jan Kara <jack@suse.cz>
 * Forked from fanotify06.c by Amir Goldstein <amir73il@gmail.com>
 */

/*\
 * [Description]
 * Check that fanotify properly merges ignore mask of a mount mark
 * with a mask of an inode mark on the same group.  Unlike the
 * prototype test fanotify06, do not use FAN_MODIFY event for the
 * test mask, because it hides the bug.
 */

/*
 * This is a regression test for commit:
 *
 *     9bdda4e9cf2d fsnotify: fix ignore mask logic in fsnotify()
 *
 * Test case #16 is a regression test for commit:
 *
 *     2f02fd3fa13e fanotify: fix ignore mask logic for events on child...
 *
 * Test cases with 'ignored_onchild' are regression tests for commit
 * (from v5.9, unlikely to be backported thus not in .tags):
 *
 *     497b0c5a7c06 fsnotify: send event to parent and child with single...
 */

#define _GNU_SOURCE
#include "config.h"

#include <stdio.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <errno.h>
#include <string.h>
#include <stdlib.h>
#include <sys/mount.h>
#include <sys/syscall.h>
#include "tst_test.h"

#ifdef HAVE_SYS_FANOTIFY_H
#include "fanotify.h"

#define EVENT_MAX 1024
/* size of the event structure, not counting name */
#define EVENT_SIZE  (sizeof(struct fanotify_event_metadata))
/* reasonable guess as to size of 1024 events */
#define EVENT_BUF_LEN        (EVENT_MAX * EVENT_SIZE)

static unsigned int fanotify_class[] = {
	FAN_CLASS_PRE_CONTENT,
	FAN_CLASS_CONTENT,
	FAN_CLASS_NOTIF,
	/* Reporting dfid+name+fid merges events similar to reporting fd */
	FAN_REPORT_DFID_NAME_FID,
};
#define NUM_CLASSES ARRAY_SIZE(fanotify_class)
#define NUM_PRIORITIES 3

#define GROUPS_PER_PRIO 3

static int fd_notify[NUM_CLASSES][GROUPS_PER_PRIO];
static int fd_syncfs;

static char event_buf[EVENT_BUF_LEN];
static int exec_events_unsupported;
static int fan_report_dfid_unsupported;
static int filesystem_mark_unsupported;
static int evictable_mark_unsupported;
static int ignore_mark_unsupported;

#define MOUNT_PATH "fs_mnt"
#define MNT2_PATH "mntpoint"
#define DIR_NAME "testdir"
#define FILE_NAME "testfile"
#define FILE2_NAME "testfile2"
#define SUBDIR_NAME "testdir2"
#define TEST_APP "fanotify_child"
#define TEST_APP2 "fanotify_child2"
#define DIR_PATH MOUNT_PATH"/"DIR_NAME
#define FILE_PATH DIR_PATH"/"FILE_NAME
#define FILE2_PATH DIR_PATH"/"FILE2_NAME
#define SUBDIR_PATH DIR_PATH"/"SUBDIR_NAME
#define FILE_EXEC_PATH MOUNT_PATH"/"TEST_APP
#define FILE2_EXEC_PATH MOUNT_PATH"/"TEST_APP2
#define DIR_MNT2 MNT2_PATH"/"DIR_NAME
#define FILE_MNT2 DIR_MNT2"/"FILE_NAME
#define FILE2_MNT2 DIR_MNT2"/"FILE2_NAME
#define FILE_EXEC_PATH2 MNT2_PATH"/"TEST_APP
#define FILE2_EXEC_PATH2 MNT2_PATH"/"TEST_APP2

#define DROP_CACHES_FILE "/proc/sys/vm/drop_caches"
#define CACHE_PRESSURE_FILE "/proc/sys/vm/vfs_cache_pressure"

static int old_cache_pressure;
static pid_t child_pid;
static int bind_mount_created;
static unsigned int num_classes = NUM_CLASSES;

enum {
	FANOTIFY_INODE,
	FANOTIFY_PARENT,
	FANOTIFY_SUBDIR,
	FANOTIFY_MOUNT,
	FANOTIFY_FILESYSTEM,
	FANOTIFY_EVICTABLE,
};

static struct fanotify_mark_type fanotify_mark_types[] = {
	INIT_FANOTIFY_MARK_TYPE(INODE),
	INIT_FANOTIFY_MARK_TYPE(PARENT),
	INIT_FANOTIFY_MARK_TYPE(SUBDIR),
	INIT_FANOTIFY_MARK_TYPE(MOUNT),
	INIT_FANOTIFY_MARK_TYPE(FILESYSTEM),
	INIT_FANOTIFY_MARK_TYPE(EVICTABLE),
};

static struct tcase {
	const char *tname;
	const char *mark_path;
	int mark_type;
	const char *ignore_path;
	int ignore_mark_type;
	unsigned int ignored_flags;
	const char *event_path;
	unsigned long long expected_mask_with_ignore;
	unsigned long long expected_mask_without_ignore;
} tcases[] = {
	{
		"ignore mount events created on a specific file",
		MOUNT_PATH, FANOTIFY_MOUNT,
		FILE_MNT2, FANOTIFY_INODE,
		0,
		FILE_PATH, 0, FAN_OPEN
	},
	{
		"ignore exec mount events created on a specific file",
		MOUNT_PATH, FANOTIFY_MOUNT,
		FILE_EXEC_PATH2, FANOTIFY_INODE,
		0,
		FILE_EXEC_PATH, FAN_OPEN_EXEC, FAN_OPEN | FAN_OPEN_EXEC
	},
	{
		"don't ignore mount events created on another file",
		MOUNT_PATH, FANOTIFY_MOUNT,
		FILE_PATH, FANOTIFY_INODE,
		0,
		FILE2_PATH, FAN_OPEN, FAN_OPEN
	},
	{
		"don't ignore exec mount events created on another file",
		MOUNT_PATH, FANOTIFY_MOUNT,
		FILE_EXEC_PATH, FANOTIFY_INODE,
		0,
		FILE2_EXEC_PATH, FAN_OPEN | FAN_OPEN_EXEC,
		FAN_OPEN | FAN_OPEN_EXEC
	},
	{
		"ignore inode events created on a specific mount point",
		FILE_PATH, FANOTIFY_INODE,
		MNT2_PATH, FANOTIFY_MOUNT,
		0,
		FILE_MNT2, 0, FAN_OPEN
	},
	{
		"ignore exec inode events created on a specific mount point",
		FILE_EXEC_PATH, FANOTIFY_INODE,
		MNT2_PATH, FANOTIFY_MOUNT,
		0,
		FILE_EXEC_PATH2, FAN_OPEN_EXEC, FAN_OPEN | FAN_OPEN_EXEC
	},
	{
		"don't ignore inode events created on another mount point",
		FILE_MNT2, FANOTIFY_INODE,
		MNT2_PATH, FANOTIFY_MOUNT,
		0,
		FILE_PATH, FAN_OPEN, FAN_OPEN
	},
	{
		"don't ignore exec inode events created on another mount point",
		FILE_EXEC_PATH2, FANOTIFY_INODE,
		MNT2_PATH, FANOTIFY_MOUNT,
		0,
		FILE_EXEC_PATH, FAN_OPEN | FAN_OPEN_EXEC,
		FAN_OPEN | FAN_OPEN_EXEC
	},
	{
		"ignore fs events created on a specific file",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		FILE_PATH, FANOTIFY_INODE,
		0,
		FILE_PATH, 0, FAN_OPEN
	},
	{
		"ignore exec fs events created on a specific file",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		FILE_EXEC_PATH, FANOTIFY_INODE,
		0,
		FILE_EXEC_PATH, FAN_OPEN_EXEC, FAN_OPEN | FAN_OPEN_EXEC
	},
	{
		"don't ignore mount events created on another file",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		FILE_PATH, FANOTIFY_INODE,
		0,
		FILE2_PATH, FAN_OPEN, FAN_OPEN
	},
	{
		"don't ignore exec mount events created on another file",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		FILE_EXEC_PATH, FANOTIFY_INODE,
		0,
		FILE2_EXEC_PATH, FAN_OPEN | FAN_OPEN_EXEC,
		FAN_OPEN | FAN_OPEN_EXEC
	},
	{
		"ignore fs events created on a specific mount point",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		MNT2_PATH, FANOTIFY_MOUNT,
		0,
		FILE_MNT2, 0, FAN_OPEN
	},
	{
		"ignore exec fs events created on a specific mount point",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		MNT2_PATH, FANOTIFY_MOUNT,
		0,
		FILE_EXEC_PATH2, FAN_OPEN_EXEC, FAN_OPEN | FAN_OPEN_EXEC
	},
	{
		"don't ignore fs events created on another mount point",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		MNT2_PATH, FANOTIFY_MOUNT,
		0,
		FILE_PATH, FAN_OPEN, FAN_OPEN
	},
	{
		"don't ignore exec fs events created on another mount point",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		MNT2_PATH, FANOTIFY_MOUNT,
		0,
		FILE_EXEC_PATH, FAN_OPEN | FAN_OPEN_EXEC,
		FAN_OPEN | FAN_OPEN_EXEC
	},
	{
		"ignore child exec events created on a specific mount point",
		MOUNT_PATH, FANOTIFY_PARENT,
		MOUNT_PATH, FANOTIFY_MOUNT,
		0,
		FILE_EXEC_PATH, FAN_OPEN_EXEC, FAN_OPEN | FAN_OPEN_EXEC
	},
	{
		"ignore events on children of directory created on a specific file",
		DIR_PATH, FANOTIFY_PARENT,
		DIR_PATH, FANOTIFY_PARENT,
		FAN_EVENT_ON_CHILD,
		FILE_PATH, 0, FAN_OPEN
	},
	{
		"ignore events on file created inside a parent watching children",
		FILE_PATH, FANOTIFY_INODE,
		DIR_PATH, FANOTIFY_PARENT,
		FAN_EVENT_ON_CHILD,
		FILE_PATH, 0, FAN_OPEN
	},
	{
		"don't ignore events on file created inside a parent not watching children",
		FILE_PATH, FANOTIFY_INODE,
		DIR_PATH, FANOTIFY_PARENT,
		0,
		FILE_PATH, FAN_OPEN, FAN_OPEN
	},
	{
		"ignore mount events created inside a parent watching children",
		FILE_PATH, FANOTIFY_MOUNT,
		DIR_PATH, FANOTIFY_PARENT,
		FAN_EVENT_ON_CHILD,
		FILE_PATH, 0, FAN_OPEN
	},
	{
		"don't ignore mount events created inside a parent not watching children",
		FILE_PATH, FANOTIFY_MOUNT,
		DIR_PATH, FANOTIFY_PARENT,
		0,
		FILE_PATH, FAN_OPEN, FAN_OPEN
	},
	{
		"ignore fs events created inside a parent watching children",
		FILE_PATH, FANOTIFY_FILESYSTEM,
		DIR_PATH, FANOTIFY_PARENT,
		FAN_EVENT_ON_CHILD,
		FILE_PATH, 0, FAN_OPEN
	},
	{
		"don't ignore fs events created inside a parent not watching children",
		FILE_PATH, FANOTIFY_FILESYSTEM,
		DIR_PATH, FANOTIFY_PARENT,
		0,
		FILE_PATH, FAN_OPEN, FAN_OPEN
	},
	/* Evictable ignore mark test cases */
	{
		"don't ignore mount events created on file with evicted ignore mark",
		MOUNT_PATH, FANOTIFY_MOUNT,
		FILE_PATH, FANOTIFY_EVICTABLE,
		0,
		FILE_PATH, FAN_OPEN, FAN_OPEN
	},
	{
		"don't ignore fs events created on a file with evicted ignore mark",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		FILE_PATH, FANOTIFY_EVICTABLE,
		0,
		FILE_PATH, FAN_OPEN, FAN_OPEN
	},
	{
		"don't ignore mount events created inside a parent with evicted ignore mark",
		MOUNT_PATH, FANOTIFY_MOUNT,
		DIR_PATH, FANOTIFY_EVICTABLE,
		FAN_EVENT_ON_CHILD,
		FILE_PATH, FAN_OPEN, FAN_OPEN
	},
	{
		"don't ignore fs events created inside a parent with evicted ignore mark",
		MOUNT_PATH, FANOTIFY_FILESYSTEM,
		DIR_PATH, FANOTIFY_EVICTABLE,
		FAN_EVENT_ON_CHILD,
		FILE_PATH, FAN_OPEN, FAN_OPEN
	},
	/* FAN_MARK_IGNORE specific test cases */
	{
		"ignore events on subdir inside a parent watching subdirs",
		SUBDIR_PATH, FANOTIFY_SUBDIR,
		DIR_PATH, FANOTIFY_PARENT,
		FAN_EVENT_ON_CHILD | FAN_ONDIR,
		SUBDIR_PATH, 0, FAN_OPEN | FAN_ONDIR
	},
	{
		"don't ignore events on subdir inside a parent not watching children",
		SUBDIR_PATH, FANOTIFY_SUBDIR,
		DIR_PATH, FANOTIFY_PARENT,
		FAN_ONDIR,
		SUBDIR_PATH, FAN_OPEN | FAN_ONDIR, FAN_OPEN | FAN_ONDIR
	},
	{
		"don't ignore events on subdir inside a parent watching non-dir children",
		SUBDIR_PATH, FANOTIFY_SUBDIR,
		DIR_PATH, FANOTIFY_PARENT,
		FAN_EVENT_ON_CHILD,
		SUBDIR_PATH, FAN_OPEN | FAN_ONDIR, FAN_OPEN | FAN_ONDIR
	},
};

static void show_fanotify_ignore_marks(int fd, int expected)
{
	unsigned int mflags, mask, ignored_mask;
	char procfdinfo[100];

	sprintf(procfdinfo, "/proc/%d/fdinfo/%d", (int)getpid(), fd);
	if (FILE_LINES_SCANF(procfdinfo, "fanotify ino:%*x sdev:%*x mflags: %x mask:%x ignored_mask:%x",
				&mflags, &mask, &ignored_mask) || !ignored_mask) {
		tst_res(!expected ? TPASS : TFAIL,
			"No fanotify inode ignore marks %sexpected",
			!expected ? "as " : "is un");
	} else {
		tst_res(expected ? TPASS : TFAIL,
			"Found %sexpected inode ignore mark (mflags=%x, mask=%x ignored_mask=%x)",
			expected ? "" : "un", mflags, mask, ignored_mask);
	}
}

static void drop_caches(void)
{
	if (syncfs(fd_syncfs) < 0)
		tst_brk(TBROK | TERRNO, "Unexpected error when syncing filesystem");

	SAFE_FILE_PRINTF(DROP_CACHES_FILE, "3");
}

static int create_fanotify_groups(unsigned int n)
{
	struct tcase *tc = &tcases[n];
	struct fanotify_mark_type *mark, *ignore_mark;
	unsigned int mark_ignored, mask;
	unsigned int p, i;
	int evictable_ignored = (tc->ignore_mark_type == FANOTIFY_EVICTABLE);
	int ignore_mark_type;
	int ignored_onchild = tc->ignored_flags & FAN_EVENT_ON_CHILD;

	mark = &fanotify_mark_types[tc->mark_type];
	ignore_mark = &fanotify_mark_types[tc->ignore_mark_type];
	ignore_mark_type = ignore_mark->flag & FAN_MARK_TYPES;

	/* Open fd for syncfs before creating groups to avoid the FAN_OPEN event */
	fd_syncfs = SAFE_OPEN(MOUNT_PATH, O_RDONLY);

	for (p = 0; p < num_classes; p++) {
		for (i = 0; i < GROUPS_PER_PRIO; i++) {
			fd_notify[p][i] = SAFE_FANOTIFY_INIT(fanotify_class[p] |
							     FAN_NONBLOCK, O_RDONLY);

			/*
			 * Add mark for each group.
			 *
			 * FAN_EVENT_ON_CHILD has no effect on filesystem/mount
			 * or inode mark on non-directory.
			 */
			SAFE_FANOTIFY_MARK(fd_notify[p][i],
					    FAN_MARK_ADD | mark->flag,
					    tc->expected_mask_without_ignore |
					    FAN_EVENT_ON_CHILD | FAN_ONDIR,
					    AT_FDCWD, tc->mark_path);

			/* Do not add ignore mark for first priority groups */
			if (p == 0)
				continue;

			/*
			 * Run tests in two variants:
			 * 1. Legacy FAN_MARK_IGNORED_MASK
			 * 2. FAN_MARK_IGNORE
			 */
			mark_ignored = tst_variant ? FAN_MARK_IGNORE_SURV : FAN_MARK_IGNORED_SURV;
			mask = FAN_OPEN | tc->ignored_flags;
add_mark:
			SAFE_FANOTIFY_MARK(fd_notify[p][i],
					    FAN_MARK_ADD | ignore_mark->flag | mark_ignored,
					    mask, AT_FDCWD, tc->ignore_path);

			/*
			 * FAN_MARK_IGNORE respects FAN_EVENT_ON_CHILD flag, but legacy
			 * FAN_MARK_IGNORED_MASK does not. When using legacy ignore mask,
			 * if ignored mask is on a parent watching children, we need to
			 * also set the event and flag FAN_EVENT_ON_CHILD in mark mask.
			 * This is needed to indicate that parent ignored mask
			 * should be applied to events on children.
			 */
			if (ignored_onchild && mark_ignored & FAN_MARK_IGNORED_MASK) {
				mark_ignored = 0;
				goto add_mark;
			}

			/*
			 * When using FAN_MARK_IGNORE, verify that the FAN_EVENT_ON_CHILD
			 * flag in mark mask does not affect the ignore mask.
			 *
			 * If parent does not want to ignore FAN_OPEN events on children,
			 * set a mark mask to watch FAN_CLOSE_WRITE events on children
			 * to make sure we do not ignore FAN_OPEN events from children.
			 *
			 * If parent wants to ignore FAN_OPEN events on childern,
			 * set a mark mask to watch FAN_CLOSE events only on parent itself
			 * to make sure we do not get FAN_CLOSE events from children.
			 *
			 * If we had already set the FAN_EVENT_ON_CHILD in the parent
			 * mark mask (mark_type == FANOTIFY_PARENT), then FAN_CLOSE mask
			 * will apply also to childern, so we skip this verification.
			 */
			if (mark_ignored & FAN_MARK_IGNORE &&
			    tc->ignore_mark_type == FANOTIFY_PARENT) {
				if (!ignored_onchild)
					mask = FAN_CLOSE_WRITE | FAN_EVENT_ON_CHILD | FAN_ONDIR;
				else if (tc->mark_type == FANOTIFY_PARENT)
					continue;
				else if (tc->ignored_flags & FAN_ONDIR)
					mask = FAN_CLOSE | ignored_onchild;
				else
					mask = FAN_CLOSE | FAN_ONDIR;
				mark_ignored = 0;
				goto add_mark;
			}
		}
	}

	/*
	 * Verify that first priority groups have no ignore inode marks and that
	 * drop_caches evicted the evictable ignore marks of other groups.
	 */
	if (evictable_ignored)
		drop_caches();

	if (ignore_mark_type == FAN_MARK_INODE) {
		for (p = 0; p < num_classes; p++) {
			for (i = 0; i < GROUPS_PER_PRIO; i++) {
				if (fd_notify[p][i] > 0)
					show_fanotify_ignore_marks(fd_notify[p][i],
								   p > 0 && !evictable_ignored);
			}
		}
	}

	return 0;
}

static void cleanup_fanotify_groups(void)
{
	unsigned int i, p;

	for (p = 0; p < num_classes; p++) {
		for (i = 0; i < GROUPS_PER_PRIO; i++) {
			if (fd_notify[p][i] > 0)
				SAFE_CLOSE(fd_notify[p][i]);
		}
	}
	if (fd_syncfs > 0)
		SAFE_CLOSE(fd_syncfs);
}

/* Flush out all pending dirty inodes and destructing marks */
static void mount_cycle(void)
{
	if (bind_mount_created)
		SAFE_UMOUNT(MNT2_PATH);
	SAFE_UMOUNT(MOUNT_PATH);
	SAFE_MOUNT(tst_device->dev, MOUNT_PATH, tst_device->fs_type, 0, NULL);
	SAFE_MOUNT(MOUNT_PATH, MNT2_PATH, "none", MS_BIND, NULL);
	bind_mount_created = 1;
}

static void verify_event(int p, int group, struct fanotify_event_metadata *event,
			 unsigned long long expected_mask)
{
	/* Only FAN_REPORT_FID reports the FAN_ONDIR flag in events on dirs */
	if (!(fanotify_class[p] & FAN_REPORT_FID))
		expected_mask &= ~FAN_ONDIR;

	if (event->mask != expected_mask) {
		tst_res(TFAIL, "group %d (%x) got event: mask %llx (expected %llx) "
			"pid=%u fd=%u", group, fanotify_class[p],
			(unsigned long long) event->mask,
			(unsigned long long) expected_mask,
			(unsigned int)event->pid, event->fd);
	} else if (event->pid != child_pid) {
		tst_res(TFAIL, "group %d (%x) got event: mask %llx pid=%u "
			"(expected %u) fd=%u", group, fanotify_class[p],
			(unsigned long long)event->mask, (unsigned int)event->pid,
			(unsigned int)child_pid, event->fd);
	} else {
		tst_res(TPASS, "group %d (%x) got event: mask %llx pid=%u fd=%u",
			group, fanotify_class[p], (unsigned long long)event->mask,
			(unsigned int)event->pid, event->fd);
	}
}

static int generate_event(const char *event_path,
			  unsigned long long expected_mask)
{
	int fd, status;

	child_pid = SAFE_FORK();

	if (child_pid == 0) {
		if (expected_mask & FAN_OPEN_EXEC) {
			SAFE_EXECL(event_path, event_path, NULL);
		} else {
			fd = SAFE_OPEN(event_path, O_RDONLY);

			if (fd > 0)
				SAFE_CLOSE(fd);
		}

		exit(0);
	}

	SAFE_WAITPID(child_pid, &status, 0);

	if (WIFEXITED(status) && WEXITSTATUS(status) == 0)
		return 1;
	return 0;
}

static void test_fanotify(unsigned int n)
{
	struct tcase *tc = &tcases[n];
	struct fanotify_mark_type *mark, *ignore_mark;
	int ret;
	unsigned int p, i;
	struct fanotify_event_metadata *event;

	tst_res(TINFO, "Test #%d: %s", n, tc->tname);

	if (exec_events_unsupported && tc->expected_mask_with_ignore & FAN_OPEN_EXEC) {
		tst_res(TCONF, "FAN_OPEN_EXEC not supported in kernel?");
		return;
	}

	if (filesystem_mark_unsupported && tc->mark_type == FANOTIFY_FILESYSTEM) {
		tst_res(TCONF, "FAN_MARK_FILESYSTEM not supported in kernel?");
		return;
	}

	if (evictable_mark_unsupported && tc->ignore_mark_type == FANOTIFY_EVICTABLE) {
		tst_res(TCONF, "FAN_MARK_EVICTABLE not supported in kernel?");
		return;
	}

	if (ignore_mark_unsupported && tst_variant) {
		tst_res(TCONF, "FAN_MARK_IGNORE not supported in kernel?");
		return;
	}

	if (tc->ignored_flags & FAN_EVENT_ON_CHILD && tst_kvercmp(5, 9, 0) < 0) {
		tst_res(TCONF, "ignored mask in combination with flag FAN_EVENT_ON_CHILD"
				" has undefined behavior on kernel < 5.9");
		return;
	}

	if (tc->ignored_flags && tc->ignore_mark_type == FANOTIFY_PARENT &&
			!tst_variant && tc->mark_type == FANOTIFY_SUBDIR) {
		tst_res(TCONF, "flags FAN_EVENT_ON_CHILD and FAN_ONDIR do not take effect"
				" with legacy FAN_MARK_IGNORED_MASK");
		return;
	}

	if (create_fanotify_groups(n) != 0)
		goto cleanup;

	mark = &fanotify_mark_types[tc->mark_type];
	ignore_mark = &fanotify_mark_types[tc->ignore_mark_type];

	/* Generate event in child process */
	if (!generate_event(tc->event_path, tc->expected_mask_with_ignore))
		tst_brk(TBROK, "Child process terminated incorrectly");

	/* First verify all groups without matching ignore mask got the event */
	for (p = 0; p < num_classes; p++) {
		if (p > 0 && !tc->expected_mask_with_ignore)
			break;

		for (i = 0; i < GROUPS_PER_PRIO; i++) {
			ret = read(fd_notify[p][i], event_buf, EVENT_BUF_LEN);
			if (ret < 0) {
				if (errno == EAGAIN) {
					tst_res(TFAIL, "group %d (%x) "
						"with %s did not get event",
						i, fanotify_class[p], mark->name);
					continue;
				}
				tst_brk(TBROK | TERRNO,
					"reading fanotify events failed");
			}
			if (ret < (int)FAN_EVENT_METADATA_LEN) {
				tst_brk(TBROK,
					"short read when reading fanotify "
					"events (%d < %d)", ret,
					(int)EVENT_BUF_LEN);
			}
			event = (struct fanotify_event_metadata *)event_buf;
			if (ret > (int)event->event_len) {
				tst_res(TFAIL, "group %d (%x) with %s "
					"got more than one event (%d > %d)",
					i, fanotify_class[p], mark->name, ret,
					event->event_len);
			} else {
				verify_event(p, i, event, p == 0 ?
						tc->expected_mask_without_ignore :
						tc->expected_mask_with_ignore);
			}
			if (event->fd != FAN_NOFD)
				SAFE_CLOSE(event->fd);
		}
	}
	/* Then verify all groups with matching ignore mask did got the event */
	for (p = 1; p < num_classes && !tc->expected_mask_with_ignore; p++) {
		for (i = 0; i < GROUPS_PER_PRIO; i++) {
			ret = read(fd_notify[p][i], event_buf, EVENT_BUF_LEN);
			if (ret >= 0 && ret < (int)FAN_EVENT_METADATA_LEN) {
				tst_brk(TBROK,
					"short read when reading fanotify "
					"events (%d < %d)", ret,
					(int)EVENT_BUF_LEN);
			}
			event = (struct fanotify_event_metadata *)event_buf;
			if (ret > 0) {
				tst_res(TFAIL, "group %d (%x) with %s and "
					"%s ignore mask got unexpected event (mask %llx)",
					i, fanotify_class[p], mark->name, ignore_mark->name,
					event->mask);
				if (event->fd != FAN_NOFD)
					SAFE_CLOSE(event->fd);
			} else if (errno == EAGAIN) {
				tst_res(TPASS, "group %d (%x) with %s and "
					"%s ignore mask got no event",
					i, fanotify_class[p], mark->name, ignore_mark->name);
			} else {
				tst_brk(TBROK | TERRNO,
					"reading fanotify events failed");
			}
		}
	}
cleanup:
	cleanup_fanotify_groups();
	mount_cycle();
}

static void setup(void)
{
	exec_events_unsupported = fanotify_events_supported_by_kernel(FAN_OPEN_EXEC,
								      FAN_CLASS_CONTENT, 0);
	filesystem_mark_unsupported = fanotify_mark_supported_by_kernel(FAN_MARK_FILESYSTEM);
	evictable_mark_unsupported = fanotify_mark_supported_by_kernel(FAN_MARK_EVICTABLE);
	ignore_mark_unsupported = fanotify_mark_supported_by_kernel(FAN_MARK_IGNORE_SURV);
	fan_report_dfid_unsupported = fanotify_init_flags_supported_on_fs(FAN_REPORT_DFID_NAME,
									  MOUNT_PATH);
	if (fan_report_dfid_unsupported) {
		FANOTIFY_INIT_FLAGS_ERR_MSG(FAN_REPORT_DFID_NAME, fan_report_dfid_unsupported);
		/* Limit tests to legacy priority classes */
		num_classes = NUM_PRIORITIES;
	}

	SAFE_MKDIR(DIR_PATH, 0755);
	SAFE_MKDIR(SUBDIR_PATH, 0755);
	SAFE_FILE_PRINTF(FILE_PATH, "1");
	SAFE_FILE_PRINTF(FILE2_PATH, "1");

	SAFE_CP(TEST_APP, FILE_EXEC_PATH);
	SAFE_CP(TEST_APP, FILE2_EXEC_PATH);

	/* Create another bind mount at another path for generating events */
	SAFE_MKDIR(MNT2_PATH, 0755);
	mount_cycle();

	SAFE_FILE_SCANF(CACHE_PRESSURE_FILE, "%d", &old_cache_pressure);
	/* Set high priority for evicting inodes */
	SAFE_FILE_PRINTF(CACHE_PRESSURE_FILE, "500");
}

static void cleanup(void)
{
	cleanup_fanotify_groups();

	if (bind_mount_created)
		SAFE_UMOUNT(MNT2_PATH);

	SAFE_FILE_PRINTF(CACHE_PRESSURE_FILE, "%d", old_cache_pressure);

	SAFE_UNLINK(FILE_PATH);
	SAFE_UNLINK(FILE2_PATH);
	SAFE_RMDIR(SUBDIR_PATH);
	SAFE_RMDIR(DIR_PATH);
	SAFE_RMDIR(MNT2_PATH);
}

static struct tst_test test = {
	.test = test_fanotify,
	.tcnt = ARRAY_SIZE(tcases),
	.test_variants = 2,
	.setup = setup,
	.cleanup = cleanup,
	.mount_device = 1,
	.mntpoint = MOUNT_PATH,
	.needs_root = 1,
	.forks_child = 1,
	.resource_files = (const char *const []) {
		TEST_APP,
		NULL
	},
	.tags = (const struct tst_tag[]) {
		{"linux-git", "9bdda4e9cf2d"},
		{"linux-git", "2f02fd3fa13e"},
		{}
	}
};

#else
	TST_TEST_TCONF("system doesn't have required fanotify support");
#endif
