#!/usr/bin/env python3
"""Offline regressions for replacing the broken vendor links safely."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from restore_vendor_sources import restore, SOURCES


class RestoreVendorTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="vendor-restore-test-", dir=Path.cwd())
        self.addCleanup(self.work.cleanup)
        self.base = Path(self.work.name).resolve()
        self.root = self.base / "kernel"
        self.modules = self.root / ".build-deps/modules"
        self.modules.mkdir(parents=True)
        source, target = SOURCES["audio"]
        self.audio_source = self.modules / source
        self.audio = self.root / target
        self.audio_source.mkdir(parents=True)
        (self.audio_source / "Makefile").write_bytes(b"obj-y += real_driver.o\r\n")
        (self.audio_source / "real_driver.c").write_bytes(b"int real_driver(void) { return 7; }\n")
        self.audio.parent.mkdir(parents=True)

    def test_broken_link_is_backed_up_and_real_sources_installed(self):
        self.audio.symlink_to("../../../../vendor/missing/audio", target_is_directory=True)
        restore(self.root, self.modules, "audio")
        self.assertFalse(self.audio.is_symlink())
        self.assertEqual((self.audio / "Makefile").read_bytes(), (self.audio_source / "Makefile").read_bytes())
        self.assertEqual((self.audio / "real_driver.c").read_bytes(), (self.audio_source / "real_driver.c").read_bytes())
        previous = list((self.root / ".build-deps").glob("restore-audio-*/previous"))
        self.assertEqual(len(previous), 1)
        self.assertTrue(previous[0].is_symlink())

    def test_existing_tree_preserved_without_stale_files_in_replacement(self):
        self.audio.mkdir()
        (self.audio / "old-stub.c").write_text("old content")
        restore(self.root, self.modules, "audio")
        self.assertFalse((self.audio / "old-stub.c").exists())
        previous = next((self.root / ".build-deps").glob("restore-audio-*/previous"))
        self.assertEqual((previous / "old-stub.c").read_text(), "old content")

    def test_failed_install_rolls_back_original(self):
        self.audio.mkdir()
        (self.audio / "old-stub.c").write_text("old content")
        replace = os.replace

        def fail_staged(source, dest):
            if Path(source).name == "audio" and Path(source).parent.name.startswith("restore-audio-"):
                raise OSError("simulated interrupted installation")
            return replace(source, dest)

        with patch("restore_vendor_sources.os.replace", side_effect=fail_staged):
            with self.assertRaisesRegex(OSError, "interrupted"):
                restore(self.root, self.modules, "audio")
        self.assertEqual((self.audio / "old-stub.c").read_text(), "old content")

    def test_feedback_rejects_parent_symlink_outside_checkout(self):
        source, target = SOURCES["feedback"]
        header = self.modules / source
        header.parent.mkdir(parents=True)
        header.write_bytes(b"official feedback header\r\n")
        dest = self.root / target
        dest.parent.parent.mkdir(parents=True)
        outside = self.base / "outside"
        outside.mkdir()
        dest.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            restore(self.root, self.modules, "feedback")
        self.assertFalse((outside / dest.name).exists())


if __name__ == "__main__":
    unittest.main()
