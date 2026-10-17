#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
                                                                                        
import importlib.util
import errno
import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('policy', Path(__file__).resolve().parents[2] / 'tools/check-policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class ImagePaths(unittest.TestCase):
    def test_absolute_link_stays_inside_image_and_missing_target_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / 'base'
            ext = Path(temp) / 'extension'
            (base / 'usr/bin').mkdir(parents=True)
            (ext / 'usr/bin').mkdir(parents=True)
            (base / 'bin').symlink_to('usr/bin')
            binary = ext / 'usr/bin/coreutils'
            binary.write_text('image binary')
            (ext / 'usr/bin/true').symlink_to('/usr/bin/coreutils')
            self.assertEqual(policy.image_path((str(ext), str(base)), '/bin/true'), str(binary))
            binary.unlink()
            self.assertIsNone(policy.image_path((str(ext), str(base)), '/bin/true'))
            (ext / 'usr/bin/host').symlink_to('/usr/bin/true')
            self.assertIsNone(policy.image_path((str(ext), str(base)), '/usr/bin/host'))

    def test_removed_base_command_does_not_satisfy_extension_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / 'base'
            ext = root / 'extension'
            (base / 'usr/bin').mkdir(parents=True)
            ext.mkdir()
            listing = root / 'utilities'
            listing.write_text('both command awk mandatory\n')
            self.assertTrue(any('missing executable POSIX utility awk' in p for p in
                                policy.check_posix(str(ext), str(base), str(listing), 'posix')))
            (base / 'usr/bin/awk').write_text('library package tool')
            (base / 'usr/bin/awk').chmod(0o755)
            self.assertFalse(any('missing executable POSIX utility awk' in p for p in
                                 policy.check_posix(str(ext), str(base), str(listing), 'posix')))
            (base / 'usr/bin/awk').unlink()
            self.assertTrue(any('missing executable POSIX utility awk' in p for p in
                                policy.check_posix(str(ext), str(base), str(listing), 'posix')))


    def test_scopes_follow_posix_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / 'base'
            ext = root / 'extension'
            (base / 'usr/bin').mkdir(parents=True)
            ext.mkdir()
            listing = root / 'utilities'
            listing.write_text('posix command vi UP\nboth command man UP\nposix-devel command make SD\n')
            self.assertEqual(policy.posix_utilities(str(listing), 'posix-devel'),
                             {'man': 'command', 'make': 'command'})
            self.assertEqual(policy.posix_utilities(str(listing), 'posix'),
                             {'vi': 'command', 'man': 'command'})
            listing.write_text('posix command vi\n')
            with self.assertRaises(ValueError):
                policy.posix_utilities(str(listing), 'posix')


class PrivilegeMetadata(unittest.TestCase):
    def test_modes_have_one_exact_regular_file_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'usr/bin').mkdir(parents=True)
            helper = root / 'usr/bin/fusermount3'
            helper.write_text('native helper')
            helper.chmod(0o4755)
            if not helper.stat().st_mode & stat.S_ISUID:
                self.skipTest('this filesystem does not preserve privilege bits; verified in the Linux builder')
            self.assertEqual(policy.check_privilege_metadata(str(root)), [])
            bad = root / 'usr/bin/other'
            bad.write_text('other program')
            for mode in (0o4755, 0o2755):
                bad.chmod(mode)
                self.assertTrue(any('setuid/setgid' in p and str(bad) in p
                                    for p in policy.check_privilege_metadata(str(root))))
            bad.unlink()
            (root / 'alias').symlink_to('/usr/bin/fusermount3')
            self.assertEqual(policy.check_privilege_metadata(str(root)), [])
            root.chmod(0o2775)
            self.assertTrue(any('setuid/setgid' in p for p in policy.check_privilege_metadata(str(root))))
            root.chmod(0o700)
            (root / 'usr/local/bin').mkdir(parents=True)
            impostor = root / 'usr/local/bin/fusermount3'
            impostor.write_text('another location')
            impostor.chmod(0o4755)
            self.assertTrue(any(str(impostor) in p for p in policy.check_privilege_metadata(str(root))))

    def test_capability_metadata_and_read_errors_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / 'program'
            binary.write_text('program')
            (root / 'usr/bin').mkdir(parents=True)
            helper = root / 'usr/bin/fusermount3'
            helper.write_text('native helper')

            def capabilities(path):
                if Path(path) in (binary, helper):
                    return b'capability metadata'
                raise OSError(errno.ENODATA, 'no capability attribute')

            with patch.object(policy, 'read_capabilities', side_effect=capabilities):
                problems = policy.check_privilege_metadata(str(root))
                self.assertTrue(any('file capabilities forbidden' in p and str(binary) in p for p in problems))
                self.assertFalse(any(str(helper) in p for p in problems))
            with patch.object(policy, 'read_capabilities', side_effect=OSError(errno.EACCES, 'unreadable metadata')):
                self.assertTrue(any('cannot audit file capabilities' in p
                                    for p in policy.check_privilege_metadata(str(root))))


if __name__ == '__main__':
    unittest.main()
