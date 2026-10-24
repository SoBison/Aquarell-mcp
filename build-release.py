#!/usr/bin/env python3
"""Build an explicit-allowlist bridge archive without app data or credentials."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile


ROOT = Path(__file__).resolve().parent
PROJECT_NAME = "Aquarell-mcp"
FILES = ("pastel_mcp.py", "locales.json", "README.md", "README.zh-CN.md",
         "SECURITY.md", "RELEASE_CHECKLIST.md", "SUPPORT.md")
SOURCE_FILES = ("build-release.py", ".gitignore", ".github/workflows/ci.yml",
                "tests/test_install.py", "tests/test_read_only.py")


def payload(version):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?", version):
        raise ValueError("Use a version such as 0.1.0-preview.1.")
    result = {name: (ROOT / name).read_bytes() for name in FILES}
    bridge = ROOT / "pastel-mcp-bridge.py"
    if not bridge.is_file():
        bridge = ROOT.parent / "Tools/pastel-mcp-bridge.py"
    license_file = ROOT / "LICENSE"
    if not license_file.is_file():
        license_file = ROOT.parent / "LICENSE"
    result["pastel-mcp-bridge.py"] = bridge.read_bytes()
    result["LICENSE"] = license_file.read_bytes()
    result["VERSION"] = (version + "\n").encode("ascii")
    return result


def build(output, version):
    files = payload(version)
    manifest = {"schemaVersion": 1, "projectName": PROJECT_NAME, "version": version,
                "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    files["release-manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    archive_prefix = PROJECT_NAME + "-" + version
    destination = output / (archive_prefix + ".zip")
    # Exclusive creation prevents a second build from quietly replacing a release.
    with destination.open("xb") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(archive_prefix + "/" + name, (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    with destination.with_suffix(".zip.sha256").open("x", encoding="ascii") as stream:
        stream.write(digest + "  " + destination.name + "\n")
    return destination


def export_source(destination, version):
    """Export a fresh standalone source tree, never an existing Git checkout."""
    files = payload(version)
    files.update({name: (ROOT / name).read_bytes() for name in SOURCE_FILES})
    manifest = {"schemaVersion": 1, "projectName": PROJECT_NAME, "version": version,
                "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    files["source-manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    # Read the full allowlist before creating anything. A failed source read
    # cannot leave a misleading partial repository ready to publish.
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in sorted(files.items()):
        target = destination / name
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--export-source", type=Path, help="Export a new standalone GitHub source directory, including tests and the canonical bridge.")
    parser.add_argument("--version", default=(ROOT / "VERSION").read_text().strip())
    args = parser.parse_args()
    try:
        print(export_source(args.export_source, args.version) if args.export_source else build(args.output, args.version))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
