#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
                                                                                              
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('pin', Path(__file__).resolve().parents[2] / 'tools/pin-sysusers.py')
pin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin)

TABLE = "u root 0 0\nu lp 988 988\ng wheel 998\ng lp 988\n"


class Pinning(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        (self.dir / 'table').write_text(TABLE)
        (self.dir / 'sysusers.d').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def conf(self, name, text):
        (self.dir / 'sysusers.d' / name).write_text(text)

    def test_apply_writes_pinned_numbers_and_keeps_the_rest(self):
        self.conf('basic.conf', 'g wheel -\ng lp -\nm root wheel\n')
        self.conf('cups.conf', 'u lp - "Line printer daemon" / /usr/bin/nologin\n')
        self.conf('root.conf', 'u root 0 "Super User" /root /usr/bin/nologin\n')
        pin.apply(str(self.dir / 'table'), str(self.dir / 'sysusers.d'))
        self.assertEqual((self.dir / 'sysusers.d/basic.conf').read_text(), 'g wheel 998\ng lp 988\nm root wheel\n')
        self.assertEqual((self.dir / 'sysusers.d/cups.conf').read_text(),
                         'u lp 988 "Line printer daemon" / /usr/bin/nologin\n')
        self.assertEqual((self.dir / 'sysusers.d/root.conf').read_text(),
                         'u root 0 "Super User" /root /usr/bin/nologin\n')

    def test_apply_refuses_an_unpinned_account_and_a_conflicting_number(self):
        self.conf('new.conf', 'u newservice - "New" / /usr/bin/nologin\n')
        with self.assertRaises(SystemExit):
            pin.apply(str(self.dir / 'table'), str(self.dir / 'sysusers.d'))
        (self.dir / 'sysusers.d/new.conf').unlink()
        self.conf('wrong.conf', 'g wheel 10\n')
        with self.assertRaises(SystemExit):
            pin.apply(str(self.dir / 'table'), str(self.dir / 'sysusers.d'))

    def write_db(self, passwd, group):
        (self.dir / 'root/etc').mkdir(parents=True, exist_ok=True)
        (self.dir / 'root/etc/passwd').write_text(passwd)
        (self.dir / 'root/etc/group').write_text(group)

    def test_check_accepts_the_table_and_refuses_drift_and_stale_lines(self):
        passwd = 'root:x:0:0::/root:/usr/bin/nologin\nlp:x:988:988::/:/usr/bin/nologin\n'
        group = 'root:x:0:\nwheel:x:998:\nlp:x:988:\n'
        self.write_db(passwd, group)
        pin.check(str(self.dir / 'table'), str(self.dir / 'root'))
        self.write_db(passwd.replace('988:988', '987:987'), group)
        with self.assertRaises(SystemExit):
            pin.check(str(self.dir / 'table'), str(self.dir / 'root'))
        self.write_db(passwd, group.replace('wheel:x:998:\n', ''))
        with self.assertRaises(SystemExit):
            pin.check(str(self.dir / 'table'), str(self.dir / 'root'))


if __name__ == '__main__':
    unittest.main()
