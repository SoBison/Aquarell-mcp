#!/usr/bin/env python3
"""Install and manage the local Aquarell MCP bridge. Python 3.9+, standard library only."""

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import importlib.util
import json
import locale
import os
from pathlib import Path
import platform
import plistlib
import secrets
import shutil
import stat
import subprocess
import sys


BUNDLE_ID = "com.bzy.pastel"
MAX_CONFIG = 1024 * 1024
MANAGED_FILES = ("pastel_mcp.py", "pastel-mcp-bridge.py", "locales.json", "VERSION")
LANGUAGES = ("en", "zh-Hans", "de", "fr", "ja")
LANGUAGE = "en"
CATALOG = None


class SetupError(Exception):
    pass


def source_directory():
    return Path(__file__).resolve().parent


def managed_directory():
    return Path.home() / "Library/Application Support/PastelMCP/bridge"


def choose_language(value=None):
    if value in LANGUAGES:
        return value
    candidate = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or locale.getlocale()[0] or "en"
    prefix = candidate.split("_")[0].split("-")[0].lower()
    return {"zh": "zh-Hans", "de": "de", "fr": "fr", "ja": "ja"}.get(prefix, "en")


def message(key):
    global CATALOG
    if CATALOG is None:
        with (source_directory() / "locales.json").open(encoding="utf-8") as stream:
            CATALOG = json.load(stream)
    return CATALOG[LANGUAGE][key]


def fail(key):
    raise SetupError(message(key))


def bridge_source():
    for candidate in (source_directory() / "pastel-mcp-bridge.py", source_directory().parent / "Tools/pastel-mcp-bridge.py"):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    fail("missing_source")


def load_bridge():
    source = bridge_source()
    spec = importlib.util.spec_from_file_location("pastel_mcp_transport", source)
    module = importlib.util.module_from_spec(spec)
    # Do not create __pycache__ inside an integrity-checked installation.
    exec(compile(source.read_bytes(), str(source), "exec"), module.__dict__)
    return module


def valid_app(path):
    """Read bundle metadata without launching or weakening signature verification."""
    try:
        for bundle in (path / "Wrapper/Pastel.app", path):
            info_file = bundle / "Info.plist"
            if not info_file.is_file():
                continue
            with info_file.open("rb") as stream:
                info = plistlib.load(stream)
            executable = info.get("CFBundleExecutable") if isinstance(info, dict) else None
            if (info.get("CFBundleIdentifier") == BUNDLE_ID and isinstance(executable, str)
                    and executable and Path(executable).name == executable
                    and (bundle / executable).is_file()):
                return True
    except (OSError, ValueError, plistlib.InvalidFileException, AttributeError):
        pass
    return False


def find_app(explicit=None):
    if explicit is not None:
        candidate = Path(explicit).expanduser().absolute()
        if not candidate.exists():
            fail("app_missing")
        if not valid_app(candidate):
            fail("invalid_app")
        return candidate
    candidates = [Path.home() / "Applications/Pastel.app", Path("/Applications/Pastel.app"),
                  Path.home() / "Applications/Aquarell.app", Path("/Applications/Aquarell.app")]
    if sys.platform == "darwin":
        try:
            result = subprocess.run(["/usr/bin/mdfind", "-0", "kMDItemCFBundleIdentifier == 'com.bzy.pastel'"],
                                    capture_output=True, timeout=5, check=False)
            if result.returncode == 0 and len(result.stdout) <= 1024 * 1024:
                candidates.extend(Path(os.fsdecode(value)) for value in result.stdout.split(b"\0") if value)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for candidate in candidates:
        if valid_app(candidate):
            return candidate.absolute()
    fail("app_missing")


def supported_host():
    if sys.platform != "darwin":
        return False
    if platform.machine().lower() in ("arm64", "aarch64"):
        return True
    # A universal Python can itself be running under Rosetta on a supported Mac.
    try:
        result = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"],
                                capture_output=True, timeout=3, check=False)
        return result.returncode == 0 and result.stdout.strip() == b"1"
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_host():
    if sys.version_info < (3, 9):
        fail("python_required")
    if not supported_host():
        fail("unsupported_host")


def file_bytes(path, limit=MAX_CONFIG):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > limit:
                fail("unsafe_file")
            data = stream.read(limit + 1)
            if len(data) > limit:
                fail("unsafe_file")
            return data
    except FileNotFoundError:
        return None
    except OSError:
        fail("unsafe_file")


@contextlib.contextmanager
def owned_directory(path, create=False, private=False):
    fd = None
    try:
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or (private and stat.S_IMODE(info.st_mode) != 0o700):
            fail("unsafe_directory")
        yield fd
    except OSError:
        fail("unsafe_directory")
    finally:
        if fd is not None:
            os.close(fd)


def atomic_bytes(directory_fd, name, data, exclusive=False):
    temporary = ".pastel-" + secrets.token_hex(16) + ".tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        else:
            os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory_fd)


@contextlib.contextmanager
def config_lock(directory_fd, name):
    fd = os.open("." + name + ".pastel-lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            fail("unsafe_file")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        fail("config_busy")
    finally:
        os.close(fd)


def verified_install(path):
    try:
        with owned_directory(path, private=True):
            raw = file_bytes(path / "install-manifest.json")
            if raw is None:
                fail("unmanaged_install")
            manifest = json.loads(raw)
            hashes = manifest.get("sha256") if isinstance(manifest, dict) else None
            if not isinstance(hashes, dict) or set(hashes) != set(MANAGED_FILES) or manifest.get("schemaVersion") != 1:
                fail("unmanaged_install")
            if set(p.name for p in path.iterdir()) != set(MANAGED_FILES) | {"install-manifest.json"}:
                fail("modified_install")
            for name in MANAGED_FILES:
                data = file_bytes(path / name)
                if data is None or hashlib.sha256(data).hexdigest() != hashes[name]:
                    fail("modified_install")
            return manifest
    except (ValueError, TypeError):
        fail("unmanaged_install")


def installed_cli():
    destination = managed_directory()
    verified_install(destination)
    return destination / "pastel_mcp.py"


def install(args):
    check_host()
    application = find_app(args.app)
    destination = managed_directory()
    parent = destination.parent
    staging = parent / (".bridge-install-" + secrets.token_hex(16))
    backup = None
    with owned_directory(parent, create=True, private=True) as parent_fd, config_lock(parent_fd, "bridge-install"):
        if destination.exists() or destination.is_symlink():
            verified_install(destination)
        staging.mkdir(mode=0o700)
        try:
            sources = {name: source_directory() / name for name in MANAGED_FILES}
            sources["pastel-mcp-bridge.py"] = bridge_source()
            hashes = {}
            with owned_directory(staging, private=True) as fd:
                for name, source in sources.items():
                    data = source.read_bytes()
                    atomic_bytes(fd, name, data)
                    hashes[name] = hashlib.sha256(data).hexdigest()
                manifest = {"schemaVersion": 1, "version": (source_directory() / "VERSION").read_text().strip(), "sha256": hashes}
                atomic_bytes(fd, "install-manifest.json", json.dumps(manifest, indent=2).encode("utf-8") + b"\n")
            if destination.exists():
                backup = parent / ("bridge.backup-" + backup_suffix())
                os.rename(destination, backup)
            try:
                os.rename(staging, destination)
            except OSError:
                if backup is not None:
                    os.rename(backup, destination)
                raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    print(message("installed"))
    print(str(destination))
    print(message("config_next"))
    # App selection is intentionally not persisted: each config records its own
    # verified installation path; no pairing credentials enter this manifest.
    return application


def backup_suffix():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)


def configuration(args):
    application = find_app(args.app)
    cli = installed_cli()
    command = str(Path(sys.executable).absolute())
    arguments = [str(cli), "serve", "--app", str(application)]
    if args.no_launch:
        arguments.append("--no-launch")
    if args.allow_edits:
        arguments.append("--allow-edits")
    return {"command": command, "args": arguments}


def strict_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError()
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def merge_config(path, entry, replace=False, remove=False):
    path = path.expanduser().absolute()
    with owned_directory(path.parent, create=True) as fd, config_lock(fd, path.name):
        raw = file_bytes(path)
        try:
            value = strict_json(raw) if raw is not None else {}
            if not isinstance(value, dict):
                fail("invalid_config")
            servers = value.get("mcpServers", {})
            if not isinstance(servers, dict):
                fail("invalid_config")
        except (ValueError, UnicodeError):
            fail("invalid_config")
        existing = servers.get("pastel")
        if remove:
            if existing is None:
                return None
            existing_args = existing.get("args") if isinstance(existing, dict) else None
            if not isinstance(existing_args, list) or existing_args[:2] != [str(managed_directory() / "pastel_mcp.py"), "serve"]:
                fail("config_conflict")
            del servers["pastel"]
        else:
            if existing == entry:
                return None
            if existing is not None and not replace:
                fail("config_conflict")
            servers["pastel"] = entry
        value["mcpServers"] = servers
        output = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if len(output) > MAX_CONFIG:
            fail("invalid_config")
        backup = None
        if raw is not None:
            backup = path.with_name(path.name + ".pastel-backup-" + backup_suffix())
            atomic_bytes(fd, backup.name, raw, exclusive=True)
        atomic_bytes(fd, path.name, output)
        return backup


def init_config(args):
    entry = configuration(args)
    if args.format == "codex":
        if args.output:
            fail("codex_stdout")
        print("[mcp_servers.pastel]")
        print("command = " + json.dumps(entry["command"], ensure_ascii=False))
        print("args = " + json.dumps(entry["args"], ensure_ascii=False))
        print("startup_timeout_sec = 45\ntool_timeout_sec = 180")
    elif args.output:
        backup = merge_config(args.output, entry, replace=args.replace)
        print(message("config_saved"))
        if backup:
            print(message("backup_saved"))
            print(str(backup))
    else:
        print(json.dumps({"mcpServers": {"pastel": entry}}, ensure_ascii=False, indent=2))


def uninstall(args):
    destination = managed_directory()
    with owned_directory(destination.parent, private=True) as parent_fd, config_lock(parent_fd, "bridge-install"):
        verified_install(destination)
        if args.config:
            merge_config(args.config, None, remove=True)
        # Only an exact, unmodified managed install reaches this point. Shared
        # pairing files and backups live outside this directory and are retained.
        with owned_directory(destination, private=True) as fd:
            for name in MANAGED_FILES + ("install-manifest.json",):
                os.unlink(name, dir_fd=fd)
        destination.rmdir()
    print(message("uninstalled"))


def serve(args):
    check_host()
    application = find_app(args.app)
    module = load_bridge()
    # The transport persists the one-time first-connection bootstrap claim.
    # Reconnects and new client processes must respect an already closed app.
    bridge = module.PastelBridge(app=application, launch=not args.no_launch,
                                 read_only=not args.allow_edits)
    try:
        bridge.serve()
    finally:
        bridge.close()


def pair(args):
    check_host()
    application = find_app(args.app)
    module = load_bridge()
    bridge = module.PastelBridge(app=application, launch=True, manual_bootstrap=True,
                                 read_only=not args.allow_edits)
    try:
        bridge.connection()
        print(json.dumps({"paired": True}))
    except module.BridgeError:
        fail("pair_failed")
    finally:
        bridge.close()


def doctor(args):
    checks = {"python": sys.version_info >= (3, 9), "appleSiliconMac": supported_host()}
    try:
        application = find_app(args.app)
        checks["installedApp"] = True
    except SetupError:
        application = None
        checks["installedApp"] = False
    try:
        verified_install(managed_directory())
        checks["managedBridge"] = True
    except SetupError:
        checks["managedBridge"] = False
    report = {"checks": checks, "connected": None}
    if args.connect:
        if application is None or not checks["appleSiliconMac"]:
            report["connected"] = False
        else:
            module = load_bridge()
            bridge = module.PastelBridge(app=application, launch=False, read_only=True)
            try:
                initialized = bridge.forward({"jsonrpc": "2.0", "id": "doctor-initialize", "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "pastel-mcp-doctor", "version": (source_directory() / "VERSION").read_text().strip()}}})
                if not isinstance(initialized, dict) or not isinstance(initialized.get("result"), dict):
                    raise module.BridgeError("unavailable")
                bridge.forward({"jsonrpc": "2.0", "method": "notifications/initialized"})
                listing = bridge.forward({"jsonrpc": "2.0", "id": "doctor-tools", "method": "tools/list"})
                tools = listing.get("result", {}).get("tools") if isinstance(listing, dict) else None
                report["connected"] = isinstance(tools, list)
                if isinstance(tools, list):
                    report["toolCount"] = len(tools)
            except module.BridgeError:
                report["connected"] = False
            finally:
                bridge.close()
    report["ready"] = all(checks.values()) and report["connected"] is not False
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


def parser():
    result = argparse.ArgumentParser(description=message("description"))
    result.add_argument("--lang", choices=LANGUAGES, help=message("language_help"))
    result.add_argument("--version", action="version", version=(source_directory() / "VERSION").read_text().strip())
    commands = result.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install", help=message("install_help"))
    install_parser.add_argument("--app", type=Path, help=message("app_help"))
    install_parser.set_defaults(action=install)
    remove = commands.add_parser("uninstall", help=message("uninstall_help"))
    remove.add_argument("--config", type=Path, help=message("remove_config_help"))
    remove.set_defaults(action=uninstall)
    config = commands.add_parser("init-config", help=message("init_help"))
    config.add_argument("--app", type=Path, help=message("app_help"))
    config.add_argument("--format", choices=("json", "codex"), default="json", help=message("format_help"))
    config.add_argument("--output", type=Path, help=message("output_help"))
    config.add_argument("--replace", action="store_true", help=message("replace_help"))
    config.add_argument("--allow-edits", action="store_true", help=message("edits_help"))
    config.add_argument("--no-launch", action="store_true", help=message("launch_help"))
    config.set_defaults(action=init_config)
    run = commands.add_parser("serve", help=message("serve_help"))
    run.add_argument("--app", type=Path, help=message("app_help"))
    run.add_argument("--allow-edits", action="store_true", help=message("edits_help"))
    run.add_argument("--no-launch", action="store_true", help=message("launch_help"))
    run.set_defaults(action=serve)
    pairing = commands.add_parser("pair", help=message("pair_help"), description=message("pair_help"))
    pairing.add_argument("--app", type=Path, help=message("app_help"))
    pairing.add_argument("--allow-edits", action="store_true", help=message("edits_help"))
    pairing.set_defaults(action=pair)
    diagnostic = commands.add_parser("doctor", help=message("doctor_help"))
    diagnostic.add_argument("--app", type=Path, help=message("app_help"))
    diagnostic.add_argument("--connect", action="store_true", help=message("connect_help"))
    diagnostic.set_defaults(action=doctor)
    return result


def main(argv=None):
    global LANGUAGE
    arguments = list(sys.argv[1:] if argv is None else argv)
    hint = None
    if "--lang" in arguments:
        with contextlib.suppress(IndexError):
            hint = arguments[arguments.index("--lang") + 1]
    for value in arguments:
        if value.startswith("--lang="):
            hint = value.partition("=")[2]
    LANGUAGE = choose_language(hint)
    try:
        args = parser().parse_args(arguments)
        value = args.action(args)
        return value if type(value) is int else 0
    except SetupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyboardInterrupt):
        print(message("operation_failed"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
