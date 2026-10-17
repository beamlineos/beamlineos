#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
HELP = """Secure Boot enrollment files for systemd-boot (docs/decisions.md D111, D113).

  make-enrollment.py --key KEY --cert CERT --time EPOCH
                     [--kek CERT[=OWNER]]... [--db CERT[=OWNER]]... OUTDIR

writes OUTDIR/{PK,KEK,db}.auth, which systemd-boot enrolls from loader/keys/auto/ in setup mode.
CERT (with KEY) is the platform key and signs PK and KEK. db is signed with the same key acting
as a key exchange key, so CERT must also be among the --kek certificates. Without --kek and
--db, CERT alone is PK, KEK and db. Each certificate gets a signature list of its own, owned by
OWNER (a GUID; Beamline's by default). The test firmware of ci/test-install (D113) holds the
development certificate as PK and KEK beside Microsoft's KEK CAs, and only Microsoft's UEFI CAs in
db, as a PC sold with Microsoft's keys does.

The files are time-based authenticated variables (EFI_VARIABLE_AUTHENTICATION_2). The signature is
bare PKCS#7 SignedData, which every EDK2 accepts; UTM's EDK2 accepts nothing else. Without signed
attributes, with an RSA key and the time taken from EPOCH, the files are reproducible. Each
signature is verified against the certificate before any file is written.
"""

import argparse
import datetime
import os
import struct
import subprocess
import sys
import tempfile
import uuid

X509_GUID = uuid.UUID("a5c059a1-94e4-4aa7-87b5-ab155c2bf072").bytes_le
PKCS7_GUID = uuid.UUID("4aafd29d-68df-49ee-8aa9-347d375665a7").bytes_le
GLOBAL_GUID = uuid.UUID("8be4df61-93ca-11d2-aa0d-00e098032b8c").bytes_le
DB_GUID = uuid.UUID("d719b2cb-3d3a-4596-a3bc-dad00e67656f").bytes_le
                                                                                            
                                                                                
OWNER_GUID = uuid.UUID("ab38e45f-7aef-4c17-ae45-9c5b15183a84").bytes_le
                                                                                      
                                        
ATTRIBUTES = 0x27
SIGNED_DATA_OID = bytes.fromhex("2a864886f70d010702")
SHA256_OID = bytes.fromhex("608648016503040201")
VARIABLES = (("PK", GLOBAL_GUID), ("KEK", GLOBAL_GUID), ("db", DB_GUID))


def der_element(blob, offset=0):
                                                                          
    tag, first = blob[offset], blob[offset + 1]
    offset += 2
    if first & 0x80:
        count = first & 0x7F
        size = int.from_bytes(blob[offset:offset + count], "big")
        offset += count
    else:
        size = first
    if offset + size > len(blob):
        raise ValueError("truncated DER element")
    return tag, offset, offset + size


def der_encode(tag, content):
    size = len(content)
    if size < 128:
        return bytes([tag, size]) + content
    length = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(length)]) + length + content


def bare_signed_data(content_info):
                                                  
    tag, start, end = der_element(content_info)
    if tag != 0x30 or end != len(content_info):
        raise ValueError("expected one DER sequence")
    tag, oid_start, oid_end = der_element(content_info, start)
    if tag != 0x06 or content_info[oid_start:oid_end] != SIGNED_DATA_OID:
        raise ValueError("expected a signedData ContentInfo")
    tag, inner_start, inner_end = der_element(content_info, oid_end)
    if tag != 0xA0 or inner_end != end:
        raise ValueError("invalid signedData wrapper")
    bare = content_info[inner_start:inner_end]
                                                                                        
    if bare[0] != 0x30 or bare[1] != 0x82 or bare[13:22] != SHA256_OID:
        raise ValueError("SignedData is not SHA-256 in the layout EDK2 expects")
    return bare


def efi_time(epoch):
    t = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
                                                                                     
    return struct.pack("<HBBBBBBIhBB", t.year, t.month, t.day, t.hour, t.minute, t.second, 0, 0, 0, 0, 0)


def signature_list(certificate, owner=OWNER_GUID):
    entry = owner + certificate
    return X509_GUID + struct.pack("<III", 28 + len(entry), 0, len(entry)) + entry


def certificate_der(path):
                                                 
    with open(path, "rb") as f:
        pem = f.read(64).lstrip().startswith(b"-----BEGIN")
    return openssl("x509", "-inform", "PEM" if pem else "DER", "-in", path, "-outform", "DER")


def signature_lists(specs):
                                                                          
    payload = b""
    for spec in specs:
        path, _, owner = spec.partition("=")
        payload += signature_list(certificate_der(path), uuid.UUID(owner).bytes_le if owner else OWNER_GUID)
    return payload


def openssl(*args):
    result = subprocess.run(["openssl", *args], capture_output=True)
    if result.returncode:
        sys.exit(f"make-enrollment: openssl {args[0]} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def auth_file(name, guid, timestamp, payload, key, cert, work):
    signed = name.encode("utf-16-le") + guid + struct.pack("<I", ATTRIBUTES) + timestamp + payload
    data = os.path.join(work, f"{name}.data")
    with open(data, "wb") as f:
        f.write(signed)
    content_info = openssl("cms", "-sign", "-binary", "-noattr", "-md", "sha256", "-signer", cert,
                           "-inkey", key, "-in", data, "-outform", "DER")
    bare = bare_signed_data(content_info)
                                                                                               
    signature = os.path.join(work, f"{name}.p7")
    with open(signature, "wb") as f:
        f.write(der_encode(0x30, der_encode(0x06, SIGNED_DATA_OID) + der_encode(0xA0, bare)))
    openssl("cms", "-verify", "-binary", "-inform", "DER", "-in", signature, "-content", data,
            "-CAfile", cert, "-purpose", "any", "-no_check_time", "-out", os.devnull)
    header = struct.pack("<IHH", 24 + len(bare), 0x0200, 0x0EF1) + PKCS7_GUID
    return timestamp + header + bare + payload


def main():
    parser = argparse.ArgumentParser(description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key", required=True, help="the signing key (PEM, RSA)")
    parser.add_argument("--cert", required=True, help="its certificate (PEM)")
    parser.add_argument("--time", required=True, type=int, help="the variables' timestamp (seconds since the epoch)")
    parser.add_argument("--kek", action="append", default=[], metavar="CERT[=OWNER]",
                        help="a key exchange key certificate (repeatable; must include --cert with --db)")
    parser.add_argument("--db", action="append", default=[], metavar="CERT[=OWNER]",
                        help="a signature database certificate (repeatable)")
    parser.add_argument("outdir")
    args = parser.parse_args()

    signer = certificate_der(args.cert)
    keks, dbs = args.kek or [args.cert], args.db or [args.cert]
    if not any(certificate_der(spec.partition("=")[0]) == signer for spec in keks):
        sys.exit("make-enrollment: --cert must be among the --kek certificates, since it signs db")
    payloads = {"PK": signature_list(signer), "KEK": signature_lists(keks), "db": signature_lists(dbs)}
    timestamp = efi_time(args.time)
    with tempfile.TemporaryDirectory() as work:
        files = {name: auth_file(name, guid, timestamp, payloads[name], args.key, args.cert, work)
                 for name, guid in VARIABLES}
    os.makedirs(args.outdir, exist_ok=True)
    for name, blob in files.items():
        path = os.path.join(args.outdir, f"{name}.auth")
        with open(path, "wb") as f:
            f.write(blob)
        os.chmod(path, 0o644)
        print(f"make-enrollment: {path} ({len(blob)} bytes)")


if __name__ == "__main__":
    main()
