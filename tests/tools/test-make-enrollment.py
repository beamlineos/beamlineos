#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
                                                                                                            
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[2] / 'tools/make-enrollment.py'
spec = importlib.util.spec_from_file_location('enrollment', TOOL)
enrollment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enrollment)

EPOCH = 1320937200                           


def openssl(*args):
    subprocess.run(['openssl', *args], check=True, capture_output=True)


class Enrollment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.temp.name)
        cls.key, cls.cert = cls.dir / 'db.key', cls.dir / 'db.crt'
        openssl('req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=Enrollment test',
                '-days', '1', '-keyout', cls.key, '-out', cls.cert)
        openssl('x509', '-in', cls.cert, '-outform', 'DER', '-out', cls.dir / 'db.der')
        cls.certificate = (cls.dir / 'db.der').read_bytes()
        cls.files = cls.make('one')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def make(cls, name):
        out = cls.dir / name
        subprocess.run([sys.executable, TOOL, '--key', cls.key, '--cert', cls.cert, '--time', str(EPOCH), out],
                       check=True, capture_output=True)
        return {variable: (out / f'{variable}.auth').read_bytes() for variable in ('PK', 'KEK', 'db')}

    def test_layout_is_an_authenticated_variable_holding_one_certificate(self):
        for variable, blob in self.files.items():
            with self.subTest(variable=variable):
                self.assertEqual(struct.unpack_from('<HBBBBB', blob, 0), (2011, 11, 10, 15, 0, 0))
                self.assertEqual(blob[6:16], bytes(10))
                length, revision, kind = struct.unpack_from('<IHH', blob, 16)
                self.assertEqual((revision, kind), (0x0200, 0x0EF1))
                self.assertEqual(blob[24:40], enrollment.PKCS7_GUID)
                bare, payload = blob[40:16 + length], blob[16 + length:]
                                                                           
                self.assertEqual(bare[:2], b'\x30\x82')
                self.assertEqual(bare[13:22], enrollment.SHA256_OID)
                self.assertEqual(payload[:16], enrollment.X509_GUID)
                self.assertEqual(struct.unpack_from('<III', payload, 16),
                                 (len(payload), 0, 16 + len(self.certificate)))
                self.assertEqual(payload[28:44], enrollment.OWNER_GUID)
                self.assertEqual(payload[44:], self.certificate)

    def test_signatures_cover_name_guid_attributes_time_and_payload(self):
        for variable, guid in enrollment.VARIABLES:
            with self.subTest(variable=variable):
                blob = self.files[variable]
                length = struct.unpack_from('<I', blob, 16)[0]
                bare, payload = blob[40:16 + length], blob[16 + length:]
                signed = variable.encode('utf-16-le') + guid + struct.pack('<I', 0x27) + blob[:16] + payload
                (self.dir / 'signed').write_bytes(signed)
                wrapped = enrollment.der_encode(0x30, enrollment.der_encode(0x06, enrollment.SIGNED_DATA_OID)
                                                + enrollment.der_encode(0xA0, bare))
                (self.dir / 'sig').write_bytes(wrapped)
                openssl('cms', '-verify', '-binary', '-inform', 'DER', '-in', self.dir / 'sig',
                        '-content', self.dir / 'signed', '-CAfile', self.cert, '-purpose', 'any',
                        '-no_check_time', '-out', '/dev/null')
                (self.dir / 'signed').write_bytes(signed.replace(b'\x27\x00\x00\x00', b'\x07\x00\x00\x00', 1))
                with self.assertRaises(subprocess.CalledProcessError):
                    openssl('cms', '-verify', '-binary', '-inform', 'DER', '-in', self.dir / 'sig',
                            '-content', self.dir / 'signed', '-CAfile', self.cert, '-purpose', 'any',
                            '-no_check_time', '-out', '/dev/null')

    def test_files_are_reproducible(self):
        self.assertEqual(self.make('two'), self.files)

    def test_separate_key_exchange_and_database_certificates(self):
                                                                                                
                                                           
        other_key, other_cert = self.dir / 'other.key', self.dir / 'other.crt'
        openssl('req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=Other CA',
                '-days', '1', '-keyout', other_key, '-out', other_cert)
        openssl('x509', '-in', other_cert, '-outform', 'DER', '-out', self.dir / 'other.der')
        other = (self.dir / 'other.der').read_bytes()
        owner = '77fa9abd-0359-4d32-bd60-28f4e78f784b'
        out = self.dir / 'mixed'
        subprocess.run([sys.executable, TOOL, '--key', self.key, '--cert', self.cert, '--time', str(EPOCH),
                        '--kek', str(self.cert), '--kek', f'{self.dir / "other.der"}={owner}',
                        '--db', f'{other_cert}={owner}', out], check=True, capture_output=True)

        def payload(name):
            blob = (out / f'{name}.auth').read_bytes()
            return blob[16 + struct.unpack_from('<I', blob, 16)[0]:]

        kek = payload('KEK')
        first = struct.unpack_from('<I', kek, 16)[0]
        self.assertEqual(kek[44:first], self.certificate)
        self.assertEqual(kek[first + 28:first + 44], enrollment.uuid.UUID(owner).bytes_le)
        self.assertEqual(kek[first + 44:], other)
        db = payload('db')
        self.assertEqual(db[28:44], enrollment.uuid.UUID(owner).bytes_le)
        self.assertEqual(db[44:], other)
        self.assertEqual(payload('PK')[44:], self.certificate)

    def test_signer_must_be_a_key_exchange_key(self):
        result = subprocess.run([sys.executable, TOOL, '--key', self.key, '--cert', self.cert,
                                 '--time', str(EPOCH), '--kek', str(self.dir / 'other.der'),
                                 self.dir / 'refused'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
