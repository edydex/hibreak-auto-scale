#!/usr/bin/env python3
"""Extract Google's verified ZIP into a new empty private staging directory.

The shell verifies a pinned archive SHA256 before invoking this parser. Reject
unexpected archive shapes as a second check; never let ZIP names choose paths
outside the empty staging tree. No third-party Python modules are needed.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import zipfile


def extract_platform_tools(archive: Path, destination: Path) -> None:
    if not destination.is_dir() or destination.is_symlink() or any(destination.iterdir()):
        raise ValueError("Archive destination must be a new, empty directory")
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if not members or len(members) > 200 or sum(m.file_size for m in members) > 200_000_000:
            raise ValueError("Unexpected Platform-Tools archive size")
        seen = set()
        for member in members:
            name = member.filename
            path = PurePosixPath(name)
            parts = path.parts
            if (not parts or parts[0] != "platform-tools" or path.is_absolute()
                    or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
                    or any(ord(char) < 32 or char in "\\:" for char in name)):
                raise ValueError("Unsafe or unexpected ZIP path")
            key = name.rstrip("/").casefold()
            if key in seen:
                raise ValueError("Duplicate ZIP member")
            seen.add(key)
            mode = member.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in {0, stat.S_IFREG, stat.S_IFDIR} or (member.is_dir() and kind == stat.S_IFREG):
                raise ValueError("Links and special ZIP entries are unsupported")
        if "platform-tools/adb" not in seen or "platform-tools/notice.txt" not in seen:
            raise ValueError("Platform-Tools executable or license notices are missing")
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.filename).parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with source.open(member) as source_file, target.open("xb") as output:
                shutil.copyfileobj(source_file, output)
            os.chmod(target, 0o600)
    os.chmod(destination / "platform-tools" / "adb", 0o700)


if __name__ == "__main__":
    try:
        extract_platform_tools(Path(sys.argv[1]), Path(sys.argv[2]))
    except (ValueError, OSError, zipfile.BadZipFile, IndexError) as error:
        print("Cannot safely unpack Platform-Tools: " + str(error), file=sys.stderr)
        raise SystemExit(1)
