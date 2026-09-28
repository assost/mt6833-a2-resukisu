#!/usr/bin/env python3
"""Insert sus_map skips and AVC tcontext spoofing into the A2 4.19 tree."""
from pathlib import Path

ROOT = Path(".").resolve()


def must_replace(rel, old, new):
    path = ROOT / rel
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"anchor missing in {rel}")
    path.write_text(text.replace(old, new, 1))


header = ROOT / "include/linux/susfs_def.h"
body = header.read_text()
original_body = body
command_ids = {
    "CMD_SUSFS_ADD_SUS_PATH_LOOP": "0x55553",
    "CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS": "0x55561",
    "CMD_SUSFS_ADD_SUS_MAP": "0x60020",
    "CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING": "0x60010",
}
# Userspace command ABI from the Android 12 / 5.10 SUSFS definitions.
footer = "#endif // #ifndef KSU_SUSFS_DEF_H"
if body.count(footer) != 1:
    raise SystemExit("SUSFS definition header guard footer missing or ambiguous")
for name, value in command_ids.items():
    block = f"#ifndef {name}\n#define {name} {value}\n#endif\n"
    if block not in body:
        body = body.replace(footer, block + footer, 1)
if "AS_FLAGS_SUS_MAP" not in body:
    body = body.replace(
        "#endif // #ifndef KSU_SUSFS_DEF_H",
        """
#include <linux/bitops.h>
#define AS_FLAGS_SUS_MAP 39
struct st_susfs_sus_map {
	char target_pathname[SUSFS_MAX_LEN_PATHNAME];
	int err;
};
#define SUSFS_IS_INODE_SUS_MAP(inode) \\
	((inode) && (inode)->i_mapping && \\
	 test_bit(AS_FLAGS_SUS_MAP, &(inode)->i_mapping->flags) && \\
	 susfs_is_current_proc_umounted_app())
#endif // #ifndef KSU_SUSFS_DEF_H
""",
    )
if body != original_body:
    header.write_text(body)

must_replace(
    "fs/proc/task_mmu.c",
    """	if (file) {
		struct inode *inode = file_inode(vma->vm_file);""",
    """	if (file) {
		struct inode *inode = file_inode(vma->vm_file);
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
		if (SUSFS_IS_INODE_SUS_MAP(inode))
			return;
#endif""",
)

must_replace(
    "fs/proc/task_mmu.c",
    """static int show_smap(struct seq_file *m, void *v)
{
	struct vm_area_struct *vma = v;
	struct mem_size_stats mss;

	memset(&mss, 0, sizeof(mss));""",
    """static int show_smap(struct seq_file *m, void *v)
{
	struct vm_area_struct *vma = v;
	struct mem_size_stats mss;

#ifdef CONFIG_KSU_SUSFS_SUS_MAP
	if (vma->vm_file && SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))
		return 0;
#endif
	memset(&mss, 0, sizeof(mss));""",
)

must_replace(
    "fs/proc/task_mmu.c",
    """	for (vma = priv->mm->mmap; vma;) {
		smap_gather_stats(vma, &mss);""",
    """	for (vma = priv->mm->mmap; vma;) {
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
		if (vma->vm_file && SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))) {
			vma = vma->vm_next;
			continue;
		}
#endif
		smap_gather_stats(vma, &mss);""",
)

must_replace(
    "fs/proc/task_mmu.c",
    """static ssize_t pagemap_read(struct file *file, char __user *buf,""",
    """#ifdef CONFIG_KSU_SUSFS_SUS_MAP
/* Keep one entry per virtual page; mmap_sem protects every VMA access. */
static void pagemap_hide_sus_map(struct mm_struct *mm, unsigned long addr,
				 struct pagemapread *pm)
{
	struct vm_area_struct *vma = find_vma(mm, addr);
	int i;

	for (i = 0; i < pm->pos; i++, addr += PAGE_SIZE) {
		while (vma && addr >= vma->vm_end)
			vma = vma->vm_next;
		if (vma && vma->vm_start <= addr && vma->vm_file &&
		    SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))
			pm->buffer[i] = make_pme(0, 0);
	}
}
#endif

static ssize_t pagemap_read(struct file *file, char __user *buf,""",
)

must_replace(
    "fs/proc/task_mmu.c",
    """		ret = walk_page_range(start_vaddr, end, &pagemap_walk);
		up_read(&mm->mmap_sem);""",
    """		ret = walk_page_range(start_vaddr, end, &pagemap_walk);
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
		pagemap_hide_sus_map(mm, start_vaddr, &pm);
#endif
		up_read(&mm->mmap_sem);""",
)

must_replace(
    "mm/memory.c",
    """	/* ignore errors, just check how much was successfully transferred */
	while (len) {
		int bytes, ret, offset;
		void *maddr;
		struct page *page = NULL;

		ret = get_user_pages_remote(tsk, mm, addr, 1,""",
    """	/* ignore errors, just check how much was successfully transferred */
	while (len) {
		int bytes, ret, offset;
		void *maddr;
		struct page *page = NULL;

#ifdef CONFIG_KSU_SUSFS_SUS_MAP
		vma = find_vma(mm, addr);
		if (vma && vma->vm_start <= addr && vma->vm_file &&
		    SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))
			break;
#endif
		ret = get_user_pages_remote(tsk, mm, addr, 1,""",
)

def ensure_susfs_include(rel):
    path = ROOT / rel
    text = path.read_text()
    if "linux/susfs_def.h" in text:
        return
    block = """#ifdef CONFIG_KSU_SUSFS_SUS_MAP
#include <linux/susfs_def.h>
#endif
"""
    needle = "#include <linux/ptrace.h>\n"
    if needle in text:
        text = text.replace(needle, needle + block, 1)
    else:
        first = text.find("#include ")
        if first < 0:
            raise SystemExit(f"no include in {rel}")
        line_end = text.find("\n", first)
        text = text[: line_end + 1] + block + text[line_end + 1 :]
    path.write_text(text)


ensure_susfs_include("mm/memory.c")
ensure_susfs_include("fs/proc/task_mmu.c")

must_replace(
    "security/selinux/avc.c",
    """	rc = security_sid_to_context(state, tsid, &scontext, &scontext_len);
	if (rc)
		audit_log_format(ab, " tsid=%d", tsid);
	else {
		audit_log_format(ab, " tcontext=%s", scontext);
		kfree(scontext);
	}""",
    """	rc = security_sid_to_context(state, tsid, &scontext, &scontext_len);
#ifdef CONFIG_KSU_SUSFS
	if (static_branch_unlikely(&susfs_is_avc_log_spoofing_enabled) &&
	    tsid == susfs_ksu_sid) {
		if (rc)
			audit_log_format(ab, " tsid=%d", susfs_priv_app_sid);
		else {
			audit_log_format(ab, " tcontext=%s",
					 "u:r:priv_app:s0:c512,c768");
			kfree(scontext);
		}
	} else
#endif
	if (rc)
		audit_log_format(ab, " tsid=%d", tsid);
	else {
		audit_log_format(ab, " tcontext=%s", scontext);
		kfree(scontext);
	}""",
)

avc = (ROOT / "security/selinux/avc.c").read_text()
if "susfs_is_avc_log_spoofing_enabled" not in avc.split("avc_dump_query", 1)[0]:
    needle = "#include <linux/audit.h>\n"
    insert = needle + """#ifdef CONFIG_KSU_SUSFS
#include <linux/static_key.h>
extern u32 susfs_ksu_sid;
extern u32 susfs_priv_app_sid;
extern struct static_key_false susfs_is_avc_log_spoofing_enabled;
#endif
"""
    if needle not in avc:
        first = avc.find("#include ")
        if first < 0:
            raise SystemExit("no include in security/selinux/avc.c")
        line_end = avc.find("\n", first)
        avc = avc[: line_end + 1] + insert[len(needle):] + avc[line_end + 1 :]
    else:
        avc = avc.replace(needle, insert, 1)
    (ROOT / "security/selinux/avc.c").write_text(avc)

print("port_susfs_full.py done")
