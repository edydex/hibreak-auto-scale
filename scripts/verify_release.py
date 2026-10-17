#!/usr/bin/env python3
"""Verify the public, originally signed payload without accessing a phone.

The Git index is the release allowlist. Generated builds, local signing material,
phone records and downloaded runtimes are never discovered recursively.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ANDROID = "{http://schemas.android.com/apk/res/android}"
FORBIDDEN_PARTS = {
    ".git", "__pycache__", ".venv", "node_modules", "signing", "build",
    "dist", "records", "setup-records", "logs", "screenshots", "android-sdk",
    "downloads", "runtime", ".private",
}
FORBIDDEN_SUFFIXES = {
    ".jks", ".keystore", ".key", ".pem", ".p12", ".pfx", ".log", ".pyc",
    ".png", ".jpg", ".jpeg", ".wav", ".mp3", ".mp4", ".dmp", ".dump",
}
BINARY_ALLOWLIST = {"HiBreak-Auto-Scale.apk", "display-policy-bridge.jar"}
REQUIRED_FILES = {
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "release.json",
    "HiBreak-Auto-Scale.apk", "display-policy-bridge.jar", "setup.py",
    "Setup-on-Mac.command", "Setup-on-Linux.sh", "Setup-on-Windows.cmd",
    "bootstrap_unix.sh", "bootstrap-windows.ps1", "runtime-downloads.json",
    "ANDROID-SDK-LICENSE.txt", "source/companion/AndroidManifest.xml",
    "scripts/verify_release.py", "scripts/package_release.py",
}
# Generic checks only: never embed a developer's actual private identifiers in
# the public checker. Any development-specific denylist belongs outside Git.
PRIVATE_HOME_PATH = re.compile(rb"/(?:Users|home)/[A-Za-z0-9_.-]+/")
PRIVATE_KEY_HEADER = re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----\r?\n")


class VerificationError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                            check=True, capture_output=True)
    names = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    if not names:
        raise VerificationError("The Git release allowlist is empty; stage the public source first.")
    return names


def verify_paths(root: Path, names: list[str]) -> None:
    missing = REQUIRED_FILES - set(names)
    if missing:
        raise VerificationError("Missing required public files: " + ", ".join(sorted(missing)))
    folded: set[str] = set()
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise VerificationError("Unsafe release path: " + name)
        for part in path.parts:
            if part.endswith((".", " ")) or re.search(r'[<>:"|?*\x00-\x1f]', part):
                raise VerificationError("Nonportable release path: " + name)
            if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", part.split(".")[0], re.IGNORECASE):
                raise VerificationError("Windows-reserved release path: " + name)
        if any(part.lower() in FORBIDDEN_PARTS for part in path.parts):
            raise VerificationError("Private/generated path in release allowlist: " + name)
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or "password" in path.name.lower():
            raise VerificationError("Private/generated file type in release allowlist: " + name)
        if path.suffix.lower() in {".apk", ".jar", ".zip", ".exe", ".dll", ".class", ".dex"} and name not in BINARY_ALLOWLIST:
            raise VerificationError("Unexpected binary in release allowlist: " + name)
        if name.casefold() in folded:
            raise VerificationError("Case-insensitive release path collision: " + name)
        folded.add(name.casefold())
        full = root / name
        if full.is_symlink() or not full.is_file():
            raise VerificationError("Release files must be regular files: " + name)
        if not full.resolve().is_relative_to(root.resolve()):
            raise VerificationError("Release path resolves outside the repository: " + name)
        payload = full.read_bytes()
        if PRIVATE_HOME_PATH.search(payload):
            raise VerificationError("Development-machine/phone identifier in: " + name)
        if PRIVATE_KEY_HEADER.search(payload):
            raise VerificationError("Private signing key in: " + name)


def verify_metadata(root: Path) -> dict:
    metadata = json.loads((root / "release.json").read_text(encoding="utf-8"))
    if metadata.get("format") != "hibreak-auto-scale-release-v1":
        raise VerificationError("Unsupported release metadata format.")
    release = metadata.get("toolkit_release", "")
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", release):
        raise VerificationError("release.json requires a semantic toolkit_release tag.")
    if metadata.get("apk") != "HiBreak-Auto-Scale.apk":
        raise VerificationError("Only the original root APK can be published.")
    apk_path = root / metadata["apk"]
    if sha256(apk_path.read_bytes()) != metadata.get("apk_sha256"):
        raise VerificationError("The bundled APK does not match release.json.")
    if not re.fullmatch(r"[a-f0-9]{64}", metadata.get("signer_certificate_sha256", "")):
        raise VerificationError("The signing-certificate fingerprint is missing or invalid.")
    manifest = ET.parse(root / "source/companion/AndroidManifest.xml").getroot()
    expected = (metadata["package"], str(metadata["version_code"]), metadata["version_name"])
    actual = (manifest.get("package"), manifest.get(ANDROID + "versionCode"), manifest.get(ANDROID + "versionName"))
    if actual != expected:
        raise VerificationError(f"Source manifest and release metadata differ: {actual!r} != {expected!r}")
    application = manifest.find("application")
    if application is None or application.get(ANDROID + "debuggable", "false") != "false":
        raise VerificationError("The release manifest must not be debuggable.")
    with zipfile.ZipFile(apk_path) as apk:
        if apk.testzip() is not None:
            raise VerificationError("APK ZIP CRC verification failed.")
        for required in ("AndroidManifest.xml", "classes.dex", "assets/display-policy-bridge.jar"):
            if required not in apk.namelist():
                raise VerificationError("APK is missing " + required)
        if apk.read("assets/display-policy-bridge.jar") != (root / "display-policy-bridge.jar").read_bytes():
            raise VerificationError("The bundled bridge differs from the APK's embedded bridge.")
    with zipfile.ZipFile(root / "display-policy-bridge.jar") as bridge:
        if bridge.testzip() is not None or "classes.dex" not in bridge.namelist():
            raise VerificationError("The bundled bridge is not a valid dex JAR.")
    return metadata


def verify_android_tools(root: Path, metadata: dict, tools: Path) -> None:
    """Cryptographically verify the original APK; this does not sign any file."""
    suffix = ".bat" if os.name == "nt" else ""
    apksigner = tools / ("apksigner" + suffix)
    aapt2 = tools / ("aapt2.exe" if os.name == "nt" else "aapt2")
    apk = root / metadata["apk"]
    signed = subprocess.run([str(apksigner), "verify", "--verbose", "--print-certs", str(apk)],
                            check=True, capture_output=True, text=True)
    certificates = re.findall(r"Signer #\d+ certificate SHA-256 digest:\s*([a-fA-F0-9]+)", signed.stdout)
    if certificates != [metadata["signer_certificate_sha256"]]:
        raise VerificationError("The APK signing certificate does not match the published identity.")
    badging = subprocess.run([str(aapt2), "dump", "badging", str(apk)],
                             check=True, capture_output=True, text=True).stdout
    package = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging, re.MULTILINE)
    if not package or package.groups() != (metadata["package"], str(metadata["version_code"]), metadata["version_name"]):
        raise VerificationError("Signed APK package/version differs from source/release metadata.")
    if re.search(r"^application-debuggable", badging, re.MULTILINE):
        raise VerificationError("The signed APK is debuggable.")


def verify(root: Path, tools: Path | None = None) -> tuple[list[str], dict]:
    names = tracked_files(root)
    verify_paths(root, names)
    metadata = verify_metadata(root)
    if tools is not None:
        verify_android_tools(root, metadata, tools)
    return names, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--android-tools", type=Path, help="build-tools folder; enables cryptographic APK/signer/binary-manifest checks")
    args = parser.parse_args()
    names, metadata = verify(args.root.resolve(), args.android_tools)
    signature = "signature verified" if args.android_tools else "signature check requires --android-tools"
    print(f"Verified {len(names)} public tracked files; {metadata['toolkit_release']}; APK {metadata['version_name']}/{metadata['version_code']}; {signature}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
