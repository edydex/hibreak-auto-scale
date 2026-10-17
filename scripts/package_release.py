#!/usr/bin/env python3
"""Package only verified Git-index allowlisted files; never upload a release."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import stat
import subprocess
import zipfile

import verify_release

ZIP_ROOT = "HiBreak-Auto-Scale"
EXECUTABLE_SUFFIXES = {".sh", ".command"}


def zip_entry(name: str, payload: bytes, executable: bool = False) -> tuple[zipfile.ZipInfo, bytes]:
    entry = zipfile.ZipInfo(f"{ZIP_ROOT}/{name}", (2020, 1, 1, 0, 0, 0))
    entry.create_system = 3
    # Stored entries avoid cross-platform zlib-version differences. The full kit
    # is small; stable bytes matter more than a small compression saving.
    entry.compress_type = zipfile.ZIP_STORED
    entry.external_attr = ((stat.S_IFREG | (0o755 if executable else 0o644)) << 16)
    return entry, payload


def package(root: Path, output: Path, tools: Path | None = None) -> list[Path]:
    names, metadata = verify_release.verify(root, tools)
    clean = subprocess.run(["git", "-C", str(root), "diff", "--exit-code", "HEAD", "--"], capture_output=True)
    if clean.returncode:
        raise verify_release.VerificationError("Commit the public source before packaging; tracked/index changes are present.")
    if "SHA256SUMS" in names:
        raise verify_release.VerificationError("Do not track a stale root SHA256SUMS; the packager creates it.")
    output.mkdir(parents=True, exist_ok=True)
    release = metadata["toolkit_release"]
    archive_path = output / f"HiBreak-Auto-Scale-Setup-{release}.zip"
    apk_path = output / "HiBreak-Auto-Scale.apk"
    sums_path = output / "SHA256SUMS"
    for destination in (archive_path, apk_path, sums_path):
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite existing release asset: {destination}")
    records: list[tuple[str, bytes]] = [(name, (root / name).read_bytes()) for name in names]
    internal_sums = "".join(f"{verify_release.sha256(payload)}  {name}\n" for name, payload in records).encode("utf-8")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in records + [("SHA256SUMS", internal_sums)]:
            entry, payload = zip_entry(name, payload, Path(name).suffix.lower() in EXECUTABLE_SUFFIXES)
            archive.writestr(entry, payload, compress_type=zipfile.ZIP_STORED)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise verify_release.VerificationError("Release ZIP CRC verification failed.")
        for name, payload in records + [("SHA256SUMS", internal_sums)]:
            if archive.read(f"{ZIP_ROOT}/{name}") != payload:
                raise verify_release.VerificationError("Release ZIP contents differ from source: " + name)
    shutil.copyfile(root / metadata["apk"], apk_path)
    sums_path.write_text("".join(f"{verify_release.sha256(path.read_bytes())}  {path.name}\n" for path in (apk_path, archive_path)), encoding="utf-8", newline="\n")
    return [apk_path, archive_path, sums_path]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True, help="empty output folder, outside source/build")
    parser.add_argument("--android-tools", type=Path, help="build-tools folder for cryptographic APK verification")
    args = parser.parse_args()
    for path in package(args.root.resolve(), args.output.resolve(), args.android_tools):
        print(f"{verify_release.sha256(path.read_bytes())}  {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
