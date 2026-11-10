#!/usr/bin/env python3
"""Journal state/bounds regressions using tiny synthetic volume headers."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('hfs-journal-replay.py')
spec = importlib.util.spec_from_file_location('journal', SCRIPT)
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)


class JournalStates(unittest.TestCase):
    def image(self, flags=5, initialized=False, offset=8192):
        data = bytearray(65536)
        header = bytearray(512)
        struct.pack_into('>2sHI4sI', header, 0, b'HX', 5, 0x2100, b'H+Lx', 1)
        struct.pack_into('>II', header, 40, 4096, 16)
        data[1024:1536] = header
        data[-1024:-512] = header
        struct.pack_into('>I', data, 4096, flags)
        struct.pack_into('>QQ', data, 4096 + 36, offset, 4096)
        if initialized:
            raw = bytearray(512)
            struct.pack_into('<IIQQQIII', raw, 0, journal.JH_MAGIC, journal.ENDIAN_MAGIC,
                             512, 512, 4096, 512, 0, 512)
            struct.pack_into('<I', raw, 36, journal.checksum(raw[:44]))
            data[offset:offset + 512] = raw
        return data

    def run_image(self, data, *args):
        with tempfile.TemporaryDirectory(prefix='fuxi-journal-test-') as folder:
            image = Path(folder) / 'volume.img'
            image.write_bytes(data)
            result = subprocess.run([sys.executable, str(SCRIPT), str(image), *args],
                                    capture_output=True, text=True)
            self.assertEqual(image.read_bytes(), data, 'inspection/replay changed an empty or invalid image')
            return result

    def test_new_journal_needs_first_mount_initialization(self):
        result = self.run_image(self.image())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('JOURNAL_NEEDS_INIT', result.stdout)

    def test_apply_does_not_fabricate_a_new_journal(self):
        result = self.run_image(self.image(), '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('JOURNAL_NEEDS_INIT', result.stdout)

    def test_initialized_empty_journal(self):
        result = self.run_image(self.image(flags=1, initialized=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('JOURNAL_EMPTY', result.stdout)

    def test_uninitialized_bytes_without_init_flag_are_rejected(self):
        result = self.run_image(self.image(flags=1))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('bad journal magic', result.stderr)

    def test_external_journal_is_rejected(self):
        result = self.run_image(self.image(flags=3))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not inside the volume', result.stderr)

    def test_out_of_volume_journal_is_rejected_even_when_new(self):
        result = self.run_image(self.image(offset=65536))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('outside the volume', result.stderr)

    def test_bad_initialized_checksum_is_rejected(self):
        data = self.image(flags=1, initialized=True)
        data[8192 + 36] ^= 1
        result = self.run_image(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)


if __name__ == '__main__':
    unittest.main()
