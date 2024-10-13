// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Copyright (c) 2024 Google LLC. All rights reserved.
 * Author(s): Kalesh Singh <kaleshsingh@google.com>
 */

#ifndef PGSIZE_HELPER_H
#define PGSIZE_HELPER_H

#include <unistd.h>

#define MAX_PAGE_SIZE (64*1024)

#if defined(__x86_64__)
/*
 * Android emulates the userspace page size on some x86_64 emulators.
 * The kernel page size still remains 4KiB (0x1000).
 */
static inline size_t kernel_page_size(void)
{
    return 0x1000;
}
#else
static inline size_t kernel_page_size(void)
{
	return getpagesize();
}
#endif

/*
 * NOTE: For all cases except Android x86_64 page size emulators,
 * kernel_page_size == page_size, and the below macros are effectively
 * no-ops.
 */

/* The number of kernel pages covered by size */
static inline size_t nr_kernel_pages(size_t size)
{
    return size / kernel_page_size();
}

/* The number of kernel pages in a @nr_pages userspace pages */
static size_t nr_pgs_to_nr_kernel_pgs(size_t nr_pages)
{
    return nr_pages * nr_kernel_pages(getpagesize());
}

/* The number of userspace pages in a @nr_pages kernel pages */
static size_t nr_kernel_pgs_to_nr_pgs(size_t nr_pages)
{
    return nr_pages / nr_kernel_pages(getpagesize());
}

#endif /* PGSIZE_HELPER_H */
