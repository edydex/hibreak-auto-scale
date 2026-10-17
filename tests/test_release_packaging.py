"""Synthetic release tests; no signing key, network, phone, or real APK needed."""
from __future__ import annotations

import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import package_release as package
import verify_release as verify


def zip_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return stream.getvalue()


class Packaging(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "public-repository"
        self.root.mkdir()
        for name in verify.REQUIRED_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic public fixture\n", encoding="utf-8")
        bridge = zip_bytes({"classes.dex": b"synthetic bridge"})
        (self.root / "display-policy-bridge.jar").write_bytes(bridge)
        apk = zip_bytes({"AndroidManifest.xml": b"synthetic compiled manifest", "classes.dex": b"synthetic app", "assets/display-policy-bridge.jar": bridge})
        (self.root / "HiBreak-Auto-Scale.apk").write_bytes(apk)
        self.metadata = {"format": "hibreak-auto-scale-release-v1", "toolkit_release": "v1.1.1-beta.1", "package": "org.hibreak.autoscale", "version_code": 12, "version_name": "1.1.1", "apk": "HiBreak-Auto-Scale.apk", "apk_sha256": verify.sha256(apk), "signer_certificate_sha256": "a" * 64}
        self.save_metadata()
        (self.root / "source/companion/AndroidManifest.xml").write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.hibreak.autoscale" android:versionCode="12" android:versionName="1.1.1"><application android:debuggable="false" /></manifest>', encoding="utf-8")
        self.git("init", "-q")
        self.commit()

    def git(self, *arguments):
        return subprocess.run(["git", "-C", str(self.root), *arguments], check=True, capture_output=True)

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "--allow-empty", "-m", "synthetic fixture")

    def save_metadata(self):
        (self.root / "release.json").write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_metadata_and_manifest_agree(self):
        names, report = verify.verify(self.root)
        self.assertEqual(set(names), verify.REQUIRED_FILES)
        self.assertEqual(report["version_code"], 12)

    def test_source_version_mismatch_refused(self):
        self.metadata["version_code"] = 13
        self.save_metadata()
        with self.assertRaisesRegex(verify.VerificationError, "manifest"):
            verify.verify(self.root)

    def test_apk_hash_mismatch_refused(self):
        self.metadata["apk_sha256"] = "b" * 64
        self.save_metadata()
        with self.assertRaisesRegex(verify.VerificationError, "does not match"):
            verify.verify(self.root)

    def test_embedded_bridge_mismatch_refused(self):
        (self.root / "display-policy-bridge.jar").write_bytes(zip_bytes({"classes.dex": b"different"}))
        with self.assertRaisesRegex(verify.VerificationError, "embedded bridge"):
            verify.verify(self.root)

    def test_missing_required_file_refused(self):
        self.git("rm", "-q", "LICENSE")
        with self.assertRaisesRegex(verify.VerificationError, "required"):
            verify.verify(self.root)

    def test_tracked_signing_material_refused(self):
        path = self.root / "source/companion/signing/private.jks"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic not a key")
        self.git("add", ".")
        with self.assertRaisesRegex(verify.VerificationError, "Private/generated"):
            verify.verify(self.root)

    def test_tracked_private_identifier_refused(self):
        (self.root / "README.md").write_bytes(("/Users/" + "synthetic-user/private-records/").encode())
        with self.assertRaisesRegex(verify.VerificationError, "identifier"):
            verify.verify(self.root)

    def test_tracked_unexpected_binary_refused(self):
        (self.root / "other.apk").write_bytes(b"fixture")
        self.git("add", ".")
        with self.assertRaisesRegex(verify.VerificationError, "Unexpected binary"):
            verify.verify(self.root)

    def test_case_collisions_refused(self):
        names = verify.tracked_files(self.root)
        with self.assertRaisesRegex(verify.VerificationError, "collision"):
            verify.verify_paths(self.root, names + ["readme.md"])

    def test_windows_reserved_filenames_refused(self):
        names = verify.tracked_files(self.root)
        with self.assertRaisesRegex(verify.VerificationError, "Windows-reserved"):
            verify.verify_paths(self.root, names + ["docs/CON.txt"])

    def test_nonportable_filenames_refused(self):
        names = verify.tracked_files(self.root)
        for name in ("docs/trailing. ", "docs/colon:name.txt", "docs/question?.txt"):
            with self.subTest(name=name), self.assertRaisesRegex(verify.VerificationError, "Nonportable"):
                verify.verify_paths(self.root, names + [name])

    @unittest.skipIf(sys.platform == "win32", "Creating a Windows symlink may require administrator/developer permissions.")
    def test_symlinks_refused(self):
        (self.root / "linked.txt").symlink_to(self.root / "README.md")
        self.git("add", ".")
        with self.assertRaisesRegex(verify.VerificationError, "regular files"):
            verify.verify(self.root)

    def test_archive_is_byte_reproducible_and_original_apk_retained(self):
        first = package.package(self.root, self.base / "one")
        second = package.package(self.root, self.base / "two")
        self.assertEqual([p.read_bytes() for p in first], [p.read_bytes() for p in second])
        self.assertEqual(first[0].read_bytes(), (self.root / "HiBreak-Auto-Scale.apk").read_bytes())
        with zipfile.ZipFile(first[1]) as archive:
            self.assertIsNone(archive.testzip())
            for line in archive.read(package.ZIP_ROOT + "/SHA256SUMS").decode().splitlines():
                digest, name = line.split("  ", 1)
                self.assertEqual(digest, verify.sha256(archive.read(package.ZIP_ROOT + "/" + name)))
            launcher = archive.getinfo(package.ZIP_ROOT + "/Setup-on-Mac.command")
            self.assertEqual(stat.S_IMODE(launcher.external_attr >> 16), 0o755)

    def test_existing_release_assets_never_overwritten(self):
        destination = self.base / "release"
        package.package(self.root, destination)
        with self.assertRaises(FileExistsError):
            package.package(self.root, destination)

    def test_untracked_private_file_never_packaged(self):
        (self.root / "private-phone.log").write_bytes(("/Users/" + "synthetic-user/private-records/").encode())
        output = package.package(self.root, self.base / "release")
        with zipfile.ZipFile(output[1]) as archive:
            self.assertFalse(any("private-phone" in name for name in archive.namelist()))

    def test_dirty_public_source_cannot_be_packaged(self):
        (self.root / "README.md").write_text("uncommitted change", encoding="utf-8")
        with self.assertRaisesRegex(verify.VerificationError, "Commit"):
            package.package(self.root, self.base / "release")

    def test_missing_semantic_release_tag_refused(self):
        del self.metadata["toolkit_release"]
        self.save_metadata()
        with self.assertRaisesRegex(verify.VerificationError, "toolkit_release"):
            verify.verify(self.root)


if __name__ == "__main__":
    unittest.main()
