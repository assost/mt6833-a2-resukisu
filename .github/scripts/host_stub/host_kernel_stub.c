#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "linux/bitops.h"
#include "linux/fs.h"
#include "linux/kernel.h"
#include "linux/uaccess.h"

int susfs_test_log_sets;
int susfs_test_log_value = -1;
int susfs_test_kern_calls;
int susfs_test_path_puts;
int susfs_test_set_bits;
int susfs_test_last_bit = -1;
int susfs_test_kern_result;
int susfs_test_null_inode;
int susfs_test_null_mapping;
int susfs_test_copy_from_fail;
int susfs_test_copy_to_fail;
int susfs_test_alloc_fail;
unsigned long susfs_test_last_copy_from_n;
char susfs_test_messages[8192];

static struct address_space susfs_test_mapping;
static struct inode susfs_test_inode;
static struct dentry susfs_test_dentry;
static struct vfsmount susfs_test_mnt;

void susfs_test_reset(void)
{
	susfs_test_log_sets = 0;
	susfs_test_log_value = -1;
	susfs_test_kern_calls = 0;
	susfs_test_path_puts = 0;
	susfs_test_set_bits = 0;
	susfs_test_last_bit = -1;
	susfs_test_kern_result = 0;
	susfs_test_null_inode = 0;
	susfs_test_null_mapping = 0;
	susfs_test_copy_from_fail = 0;
	susfs_test_copy_to_fail = 0;
	susfs_test_alloc_fail = 0;
	susfs_test_last_copy_from_n = 0;
	susfs_test_messages[0] = '\0';
	memset(&susfs_test_mapping, 0, sizeof(susfs_test_mapping));
}

void susfs_test_pr(const char *fmt, ...)
{
	va_list ap;
	size_t used = strlen(susfs_test_messages);

	va_start(ap, fmt);
	vsnprintf(susfs_test_messages + used,
		  sizeof(susfs_test_messages) - used, fmt, ap);
	va_end(ap);
}

void *kzalloc(size_t size, int flags)
{
	(void)flags;
	if (susfs_test_alloc_fail)
		return NULL;
	return calloc(1, size);
}

void kfree(void *ptr)
{
	free(ptr);
}

unsigned long copy_from_user(void *to, const void *from, unsigned long n)
{
	susfs_test_last_copy_from_n = n;
	if (susfs_test_copy_from_fail)
		return (unsigned long)susfs_test_copy_from_fail;
	memcpy(to, from, n);
	return 0;
}

unsigned long copy_to_user(void *to, const void *from, unsigned long n)
{
	if (susfs_test_copy_to_fail)
		return (unsigned long)susfs_test_copy_to_fail;
	memcpy(to, from, n);
	return 0;
}

void susfs_set_log(bool enabled)
{
	susfs_test_log_sets++;
	susfs_test_log_value = enabled ? 1 : 0;
}

int kern_path(const char *name, unsigned int flags, struct path *path)
{
	(void)flags;
	susfs_test_kern_calls++;
	if (susfs_test_kern_result)
		return susfs_test_kern_result;
	path->dentry = &susfs_test_dentry;
	path->mnt = &susfs_test_mnt;
	(void)name;
	return 0;
}

void path_put(struct path *path)
{
	(void)path;
	susfs_test_path_puts++;
}

struct inode *d_backing_inode(struct dentry *dentry)
{
	(void)dentry;
	if (susfs_test_null_inode)
		return NULL;
	susfs_test_inode.i_mapping = susfs_test_null_mapping ? NULL : &susfs_test_mapping;
	return &susfs_test_inode;
}

void set_bit(int nr, unsigned long *addr)
{
	susfs_test_set_bits++;
	susfs_test_last_bit = nr;
	if (nr >= 0 && nr < (int)(sizeof(*addr) * 8))
		*addr |= 1UL << nr;
}
