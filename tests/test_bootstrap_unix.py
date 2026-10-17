#!/usr/bin/env python3
"""Bootstrap contract/failure tests. No network, phone, or system installs."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap_archives", ROOT / "bootstrap_archives.py")
archives = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archives)


@unittest.skipUnless(os.name == 'posix' and Path('/bin/bash').is_file(),
                     'POSIX shell bootstrap contracts; Windows has its native PowerShell suite')
class ShellTests(unittest.TestCase):
    def shell(self, code, input="", check=True, timeout=10):
        env = dict(os.environ, HIBREAK_BOOTSTRAP_SOURCE_ONLY="1")
        prefix = "source " + shlex.quote(str(ROOT / "bootstrap_unix.sh")) + "; "
        result = subprocess.run(["/bin/bash", "-c", prefix + code], text=True,
                                input=input, capture_output=True, env=env, timeout=timeout)
        if check and result.returncode:
            self.fail(result.stdout + result.stderr)
        return result

    def test_shell_syntax(self):
        subprocess.run(["/bin/bash", "-n", str(ROOT / "bootstrap_unix.sh")], check=True)

    def test_explicit_adb_is_used_before_any_download_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            adb=Path(folder)/'custom adb'
            adb.write_text("#!/bin/sh\nprintf '%s\\n' 'Android Debug Bridge version 1.0.41' 'Version 34.0.0-1'\n")
            adb.chmod(0o700)
            code=('hb_platform() { HIBREAK_PLATFORM=linux; HIBREAK_CACHE='+shlex.quote(folder+'/cache')+'; }; '
                  'hb_select_pins() { :; }; '
                  'hb_existing_python() { HIBREAK_PYTHON='+shlex.quote(sys.executable)+'; return 0; }; '
                  'hb_existing_adb() { return 1; }; '
                  'hb_lock() { echo unexpected-download >&2; return 1; }; '
                  'hb_main --check-dependencies --adb '+shlex.quote(str(adb)))
            result=self.shell(code)
            self.assertIn('Using your specified Android connection tool.',result.stdout)
            self.assertNotIn('unexpected-download',result.stderr)

    def test_invalid_explicit_adb_never_silently_downloads_a_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            code=('hb_platform() { HIBREAK_PLATFORM=linux; HIBREAK_CACHE='+shlex.quote(folder+'/cache')+'; }; '
                  'hb_select_pins() { :; }; '
                  'hb_existing_python() { HIBREAK_PYTHON='+shlex.quote(sys.executable)+'; return 0; }; '
                  'hb_existing_adb() { echo incorrect-fallback >&2; return 0; }; '
                  'hb_main --check-dependencies --adb /not/a/tool')
            result=self.shell(code,check=False)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('supplied --adb',result.stderr)
            self.assertNotIn('incorrect-fallback',result.stderr)

    def test_all_shell_pins_equal_manifest(self):
        manifest = json.loads((ROOT / "runtime-downloads.json").read_text())
        for system, arch in [("macos", "arm64"), ("macos", "x86_64"),
                             ("linux", "x86_64"), ("linux", "aarch64")]:
            with self.subTest(system=system, arch=arch):
                result = self.shell(f"HIBREAK_PLATFORM={system}; HIBREAK_ARCH={arch}; hb_select_pins; "
                                    'printf "%s\\n" "$HIBREAK_PYTHON_URL" "$HIBREAK_PYTHON_SHA" "$HIBREAK_ADB_URL" "$HIBREAK_ADB_SHA"')
                python_url, python_sha, adb_url, adb_sha = result.stdout.splitlines()
                expected = manifest["python"][f"{system}-{arch}"]
                self.assertEqual((python_url, python_sha), (expected["url"], expected["sha256"]))
                if system == "linux" and arch == "aarch64":
                    self.assertEqual((adb_url, adb_sha), ("", ""))
                else:
                    adb = manifest["adb"]["macos" if system == "macos" else "linux-x86_64"]
                    self.assertEqual((adb_url, adb_sha), (adb["url"], adb["sha256"]))

    def test_working_current_python(self):
        self.shell("hb_python_works " + shlex.quote(sys.executable))

    def test_invalid_python_refused(self):
        result = self.shell("hb_python_works /does/not/exist", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_unconfigured_apple_stub_never_executed(self):
        # Readable source-level guard is tested without altering xcode-select.
        source = (ROOT / "bootstrap_unix.sh").read_text()
        guard = source.index('if [ "$1" = /usr/bin/python3 ]')
        execute = source.index('"$1" -I -c')
        self.assertLess(guard, execute)
        self.assertIn('[ -d "$developer_dir" ] || return 1', source[guard:execute])

    def test_existing_adb_version_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / "adb"
            fake.write_text("#!/bin/sh\nprintf '%s\\n' 'Android Debug Bridge version 1.0.41' 'Version 37.0.1-1'\n")
            fake.chmod(0o700)
            self.shell("hb_adb_works " + shlex.quote(str(fake)))
            fake.write_text("#!/bin/sh\nprintf '%s\\n' 'Android Debug Bridge version 1.0.41' 'Version 28.0.0-1'\n")
            self.assertNotEqual(self.shell("hb_adb_works " + shlex.quote(str(fake)), check=False).returncode, 0)

    def test_checksum_mismatch_never_succeeds(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "payload"
            log = Path(folder) / "log"
            # The stand-in curl writes bytes; the real checksum code must reject.
            result = self.shell(f'HIBREAK_LOG={shlex.quote(str(log))}; '
                'curl() { while [ "$#" -gt 1 ]; do shift; done; printf bad > "$1"; }; '
                f'hb_fetch https://example.invalid/file {"0" * 64} {shlex.quote(str(file))}', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("failed its security checksum", result.stderr)

    def test_download_failure_never_succeeds(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.shell(f'HIBREAK_LOG={shlex.quote(folder + "/log")}; curl() {{ return 22; }}; '
                f'hb_fetch https://example.invalid/file {"0" * 64} {shlex.quote(folder + "/payload")}', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("download did not finish", result.stderr)

    def test_insecure_download_refused_before_curl(self):
        result = self.shell('curl() { echo SHOULD_NOT_RUN; }; hb_fetch http://example.invalid/file x /tmp/unused', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SHOULD_NOT_RUN", result.stdout)

    def test_declined_license_has_no_acceptance_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.shell(f'HIBREAK_CACHE={shlex.quote(folder)}; hb_accept_sdk_license', input="\n", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(folder) / "android-sdk-license.accepted").exists())

    def test_license_acceptance_is_persisted_for_exact_terms(self):
        with tempfile.TemporaryDirectory() as folder:
            self.shell(f'HIBREAK_CACHE={shlex.quote(folder)}; hb_accept_sdk_license; hb_accept_sdk_license', input="agree\n")
            expected = hashlib.sha256((ROOT / "ANDROID-SDK-LICENSE.txt").read_bytes()).hexdigest()
            self.assertEqual((Path(folder) / "android-sdk-license.accepted").read_text().strip(), expected)

    def test_musl_or_old_glibc_has_actionable_failure(self):
        for output in ["", "glibc 2.16"]:
            result = self.shell(f'HIBREAK_PLATFORM=linux; getconf() {{ printf "%s\\n" {shlex.quote(output)}; }}; hb_require_glibc', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("glibc 2.17", result.stderr)

    def test_linux_arm_adb_fails_before_license_or_fetch(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.shell(f'HIBREAK_CACHE={shlex.quote(folder)}; HIBREAK_PLATFORM=linux; HIBREAK_ARCH=aarch64; '
                'hb_select_pins; hb_accept_sdk_license() { echo SHOULD_NOT_PROMPT; }; hb_install_adb', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not provide a Linux ARM64 ADB", result.stderr)
            self.assertNotIn("SHOULD_NOT_PROMPT", result.stdout)

    def check_tar(self, additions, succeeds):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "test.tar.gz"
            with tarfile.open(archive, "w:gz") as source:
                member = tarfile.TarInfo("python/bin/python3.12")
                member.size = 2
                source.addfile(member, io.BytesIO(b"ok"))
                for name, kind, target in additions:
                    member = tarfile.TarInfo(name)
                    if kind == "link":
                        member.type, member.linkname = tarfile.SYMTYPE, target
                    elif kind == "device":
                        member.type = tarfile.CHRTYPE
                    source.addfile(member)
            result = self.shell("hb_validate_python_tar " + " ".join(shlex.quote(str(Path(folder) / n))
                                for n in ["test.tar.gz", "list", "verbose"]), check=False)
            self.assertEqual(result.returncode == 0, succeeds, result.stdout + result.stderr)

    def test_safe_tar_and_internal_parent_link(self):
        self.check_tar([("python/bin/python3", "link", "python3.12"),
                        ("python/share/terminfo/1/1178", "link", "../a/adm1178")], True)

    def test_tar_parent_traversal_refused(self):
        self.check_tar([("python/../../escape", "file", "")], False)

    def test_tar_absolute_path_refused(self):
        self.check_tar([("/tmp/escape", "file", "")], False)

    def test_tar_escaping_link_refused(self):
        self.check_tar([("python/bin/escape", "link", "../../../escape")], False)

    def test_tar_absolute_link_refused(self):
        self.check_tar([("python/bin/escape", "link", "/tmp/escape")], False)

    def test_tar_device_refused(self):
        self.check_tar([("python/device", "device", "")], False)

    def test_tar_directory_symlink_traversal_refused(self):
        self.check_tar([("python/subfolder", "link", "."),
                        ("python/subfolder/file", "file", "")], False)

    def test_tar_parent_escape_through_link_chain_refused(self):
        self.check_tar([("python/subfolder", "link", "."),
                        ("python/escape", "link", "subfolder/../outside")], False)

    def test_release_lock_reacquirable_and_stale_lock_recovers(self):
        if sys.platform != "darwin":
            self.skipTest("macOS shlock integration")
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / ".bootstrap.lock"
            lock.write_text("99999999\n")
            self.shell(f'HIBREAK_CACHE={shlex.quote(folder)}; HIBREAK_PLATFORM=macos; hb_lock; hb_unlock; hb_lock; hb_unlock')
            self.assertFalse(lock.exists())

    def launcher_fixture(self, folder, entry_text, args):
        kit = Path(folder) / "kit with spaces"
        kit.mkdir()
        for name in ("bootstrap_unix.sh", "bootstrap_archives.py", "ANDROID-SDK-LICENSE.txt"):
            shutil.copy2(ROOT / name, kit / name)
        (kit / "setup.py").write_text(entry_text)
        fake_bin = Path(folder) / "bin"
        fake_bin.mkdir()
        (fake_bin / "python3").symlink_to(sys.executable)
        fake_adb = fake_bin / "adb"
        fake_adb.write_text("#!/bin/sh\nprintf '%s\\n' 'Android Debug Bridge version 1.0.41' 'Version 29.0.0-1'\n")
        fake_adb.chmod(0o700)
        cache = Path(folder) / "private runtime"
        env = dict(os.environ, HIBREAK_RUNTIME_DIR=str(cache),
                   HIBREAK_PAUSE_ON_EXIT="0", HIBREAK_USE_PRIVATE_RUNTIME="0",
                   PATH=str(fake_bin) + os.pathsep + os.environ["PATH"])
        env.pop("HIBREAK_BOOTSTRAP_SOURCE_ONLY", None)
        result = subprocess.run(["/bin/bash", str(kit / "bootstrap_unix.sh"), *args],
                                env=env, capture_output=True, text=True, timeout=10)
        return result, cache, fake_adb

    def test_launcher_uses_private_records_and_forwards_overrides(self):
        entry = ('import argparse,json\n'
                 'p=argparse.ArgumentParser(); p.add_argument("--adb"); p.add_argument("--state-dir"); p.add_argument("--serial"); '
                 'print("FIXTURE="+json.dumps(vars(p.parse_args())))\n')
        for override in (False, True):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as folder:
                selected = Path(folder) / "explicit private records"
                args = ["--serial", "fixture"]
                if override:
                    args += ["--state-dir", str(selected)]
                result, cache, adb = self.launcher_fixture(folder, entry, args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                parsed = json.loads(next(line[8:] for line in result.stdout.splitlines() if line.startswith("FIXTURE=")))
                self.assertEqual(parsed, {"adb": str(adb), "serial": "fixture",
                    "state_dir": str(selected if override else cache / "setup-records")})
                self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o700)

    def test_launcher_propagates_wizard_failure_without_dropping_log(self):
        with tempfile.TemporaryDirectory() as folder:
            result, cache, _ = self.launcher_fixture(folder, "raise SystemExit(17)\n", [])
            self.assertEqual(result.returncode, 17)
            self.assertIn("Setup log:", result.stderr)
            self.assertTrue(list((cache / "logs").glob("*.log")))


class ZipTests(unittest.TestCase):
    def extract(self, entries, expected_error=False):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "test.zip"
            dest = Path(folder) / "stage"
            dest.mkdir()
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("platform-tools/adb", b"executable")
                archive.writestr("platform-tools/NOTICE.txt", b"license")
                for name, content in entries:
                    archive.writestr(name, content)
            if expected_error:
                with self.assertRaises(ValueError):
                    archives.extract_platform_tools(source, dest)
                self.assertFalse(any(dest.iterdir()), "all headers should be checked before writing")
            else:
                archives.extract_platform_tools(source, dest)
                self.assertEqual((dest / "platform-tools/NOTICE.txt").read_bytes(), b"license")
                if os.name == 'posix':
                    self.assertEqual(stat.S_IMODE((dest / "platform-tools/adb").stat().st_mode), 0o700)

    def test_safe_zip_retains_license_and_executable(self):
        self.extract([("platform-tools/lib64/library.so", b"test")])

    def test_zip_parent_traversal_refused(self):
        self.extract([("platform-tools/../../escape", b"")], True)

    def test_zip_absolute_path_refused(self):
        self.extract([("/tmp/escape", b"")], True)

    def test_zip_backslash_refused(self):
        self.extract([("platform-tools/..\\escape", b"")], True)

    def test_zip_case_collision_refused(self):
        self.extract([("platform-tools/ADB", b"")], True)

    def test_zip_symbolic_link_refused(self):
        entry = zipfile.ZipInfo("platform-tools/link")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.extract([(entry, b"../../escape")], True)

    def test_zip_nonempty_destination_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder)
            (dest / "existing").write_text("preserve")
            with self.assertRaises(ValueError):
                archives.extract_platform_tools(Path("not-opened.zip"), dest)


if __name__ == "__main__":
    unittest.main()
