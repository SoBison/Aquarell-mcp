import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


SOURCE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


setup = load("pastel_install_under_test", SOURCE / "pastel_mcp.py")
release = load("pastel_release_under_test", SOURCE / "build-release.py")


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pastel-install-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "用户 with spaces"
        self.home.mkdir(mode=0o700)
        self.environment = mock.patch.dict(os.environ, {"HOME": str(self.home), "LANG": "en_US.UTF-8", "LC_ALL": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.host = mock.patch.object(setup, "supported_host", return_value=True)
        self.host.start()
        self.addCleanup(self.host.stop)
        self.app = self.home / "Applications/Aquarell.app"
        self.app.mkdir(parents=True)
        self.bundle(self.app)
        self.config = self.home / "client/config.json"

    def bundle(self, path, identity="com.bzy.pastel"):
        (path / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": identity, "CFBundleExecutable": "Pastel"}))
        (path / "Pastel").write_bytes(b"metadata-only test fixture; never executed")

    def cli(self, *arguments):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = setup.main(list(arguments))
        return status, output.getvalue(), error.getvalue()

    def install(self):
        status, output, error = self.cli("install", "--app", str(self.app))
        self.assertEqual(status, 0, error)
        return setup.managed_directory()

    def write_config(self, value):
        self.config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.config.write_bytes(raw)
        return raw

    def test_install_is_private_and_uses_canonical_transport(self):
        destination = self.install()
        manifest = setup.verified_install(destination)
        self.assertEqual(set(manifest["sha256"]), set(setup.MANAGED_FILES))
        self.assertEqual((destination / "pastel-mcp-bridge.py").read_bytes(), setup.bridge_source().read_bytes())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in destination.iterdir()))

    def test_known_display_name_and_wrapper_detection(self):
        self.assertEqual(setup.find_app(), self.app)
        outer = self.home / "Wrapped.app"
        inner = outer / "Wrapper/Pastel.app"
        inner.mkdir(parents=True)
        self.bundle(inner)
        self.assertEqual(setup.find_app(outer), outer)

    def test_explicit_wrong_bundle_is_not_fallback(self):
        other = self.home / "Other.app"
        other.mkdir()
        self.bundle(other, "example.other")
        status, _, _ = self.cli("install", "--app", str(other))
        self.assertEqual(status, 1)
        self.assertFalse(setup.managed_directory().exists())

    def test_non_mac_host_rejected_before_install(self):
        with mock.patch.object(setup, "supported_host", return_value=False):
            status, _, _ = self.cli("install", "--app", str(self.app))
        self.assertEqual(status, 1)
        self.assertFalse(setup.managed_directory().exists())

    def test_python_older_than_declared_minimum_rejected(self):
        with mock.patch.object(setup.sys, "version_info", (3, 8, 0)):
            status, _, _ = self.cli("install", "--app", str(self.app))
        self.assertEqual(status, 1)
        self.assertFalse(setup.managed_directory().exists())

    def test_upgrade_keeps_original_install_backup(self):
        destination = self.install()
        original = (destination / "install-manifest.json").read_bytes()
        self.install()
        backups = list(destination.parent.glob("bridge.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "install-manifest.json").read_bytes(), original)
        setup.verified_install(destination)

    def test_unmanaged_directory_and_modified_files_preserved(self):
        destination = setup.managed_directory()
        destination.mkdir(mode=0o700, parents=True)
        destination.parent.chmod(0o700)
        personal = destination / "notes.txt"
        personal.write_text("keep this")
        self.assertEqual(self.cli("install", "--app", str(self.app))[0], 1)
        self.assertEqual(personal.read_text(), "keep this")
        personal.unlink()
        destination.rmdir()
        destination = self.install()
        (destination / "VERSION").write_text("customized")
        self.assertEqual(self.cli("uninstall")[0], 1)
        self.assertEqual((destination / "VERSION").read_text(), "customized")

    def test_final_install_symlink_rejected_without_touching_target(self):
        destination = setup.managed_directory()
        destination.parent.mkdir(mode=0o700, parents=True)
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "private.txt").write_text("keep")
        destination.symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual(self.cli("install", "--app", str(self.app))[0], 1)
        self.assertEqual((elsewhere / "private.txt").read_text(), "keep")

    def test_shared_pairing_file_survives_install_and_remove(self):
        destination = setup.managed_directory()
        destination.parent.mkdir(mode=0o700, parents=True)
        pairing = destination.parent / "connection.json"
        pairing.write_bytes(b"sensitive fixture; never copied")
        pairing.chmod(0o600)
        self.install()
        self.assertEqual(self.cli("uninstall")[0], 0)
        self.assertFalse(destination.exists())
        self.assertEqual(pairing.read_bytes(), b"sensitive fixture; never copied")

    def test_json_merge_preserves_values_exact_backup_and_permissions(self):
        self.install()
        value = {"preferences": {"theme": "深色"}, "mcpServers": {"other": {"command": "keep", "env": {"TOKEN": "private-other-secret"}}}}
        raw = self.write_config(value)
        status, output, error = self.cli("init-config", "--app", str(self.app), "--output", str(self.config))
        self.assertEqual(status, 0, error)
        updated = json.loads(self.config.read_bytes())
        self.assertEqual(updated["preferences"], value["preferences"])
        self.assertEqual(updated["mcpServers"]["other"], value["mcpServers"]["other"])
        self.assertNotIn("--allow-edits", updated["mcpServers"]["pastel"]["args"])
        self.assertNotIn("private-other-secret", output + error)
        backups = list(self.config.parent.glob("config.json.pastel-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), raw)
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_allow_edits_is_explicit_and_config_has_no_token(self):
        self.install()
        status, output, error = self.cli("init-config", "--app", str(self.app), "--allow-edits")
        self.assertEqual(status, 0, error)
        entry = json.loads(output)["mcpServers"]["pastel"]
        self.assertIn("--allow-edits", entry["args"])
        self.assertEqual(set(entry), {"command", "args"})
        self.assertNotIn("token", output.lower())
        self.assertEqual(entry["args"][:2], [str(setup.managed_directory() / "pastel_mcp.py"), "serve"])

    def test_existing_entry_requires_explicit_replace(self):
        self.install()
        raw = self.write_config({"mcpServers": {"pastel": {"command": "another-server"}}})
        status, _, _ = self.cli("init-config", "--app", str(self.app), "--output", str(self.config))
        self.assertEqual(status, 1)
        self.assertEqual(self.config.read_bytes(), raw)
        status, _, error = self.cli("init-config", "--app", str(self.app), "--output", str(self.config), "--replace")
        self.assertEqual(status, 0, error)
        self.assertEqual(next(self.config.parent.glob("*.pastel-backup-*")).read_bytes(), raw)

    def test_identical_merge_is_noop(self):
        self.install()
        args = ("init-config", "--app", str(self.app), "--output", str(self.config))
        self.assertEqual(self.cli(*args)[0], 0)
        raw = self.config.read_bytes()
        modified = self.config.stat().st_mtime_ns
        self.assertEqual(self.cli(*args)[0], 0)
        self.assertEqual(self.config.read_bytes(), raw)
        self.assertEqual(self.config.stat().st_mtime_ns, modified)
        self.assertFalse(list(self.config.parent.glob("*.pastel-backup-*")))

    def test_invalid_json_shapes_and_duplicate_keys_preserve_original(self):
        self.install()
        self.config.parent.mkdir()
        for raw in (b"not json", b"[]", b'{"mcpServers":[]}', b'{"a":1,"a":2}', b'{"x":NaN}'):
            with self.subTest(raw=raw):
                self.config.write_bytes(raw)
                self.assertEqual(self.cli("init-config", "--app", str(self.app), "--output", str(self.config))[0], 1)
                self.assertEqual(self.config.read_bytes(), raw)

    def test_symlink_and_oversized_config_rejected(self):
        self.install()
        self.config.parent.mkdir()
        target = self.home / "target.json"
        target.write_bytes(b"{}")
        self.config.symlink_to(target)
        self.assertEqual(self.cli("init-config", "--app", str(self.app), "--output", str(self.config))[0], 1)
        self.assertEqual(target.read_bytes(), b"{}")
        self.config.unlink()
        self.config.write_bytes(b" " * (setup.MAX_CONFIG + 1))
        self.assertEqual(self.cli("init-config", "--app", str(self.app), "--output", str(self.config))[0], 1)
        self.assertEqual(self.config.stat().st_size, setup.MAX_CONFIG + 1)

    def test_locked_config_rejected_and_old_bytes_unchanged(self):
        self.install()
        raw = self.write_config({"keep": True})
        with setup.owned_directory(self.config.parent) as fd, setup.config_lock(fd, self.config.name):
            self.assertEqual(self.cli("init-config", "--app", str(self.app), "--output", str(self.config))[0], 1)
        self.assertEqual(self.config.read_bytes(), raw)

    def test_failed_config_publication_preserves_original_and_backup(self):
        self.install()
        raw = self.write_config({"keep": "secret"})
        original_replace = setup.os.replace
        def fail_selected(source, destination, **kwargs):
            if destination == self.config.name:
                raise OSError("fixture publication failure")
            return original_replace(source, destination, **kwargs)
        with mock.patch.object(setup.os, "replace", side_effect=fail_selected):
            status, output, error = self.cli("init-config", "--app", str(self.app), "--output", str(self.config))
        self.assertEqual(status, 1)
        self.assertEqual(self.config.read_bytes(), raw)
        self.assertEqual(next(self.config.parent.glob("*.pastel-backup-*")).read_bytes(), raw)
        self.assertNotIn("secret", output + error)
        self.assertFalse(list(self.config.parent.glob(".pastel-*.tmp")))

    def test_codex_snippet_never_overwrites_toml(self):
        self.install()
        toml = self.home / "config.toml"
        toml.write_text('model = "keep"\n')
        status, output, error = self.cli("init-config", "--format", "codex", "--app", str(self.app))
        self.assertEqual(status, 0, error)
        self.assertTrue(output.startswith("[mcp_servers.pastel]\n"))
        self.assertIn(json.dumps(str(setup.managed_directory() / "pastel_mcp.py"), ensure_ascii=False), output)
        self.assertEqual(self.cli("init-config", "--format", "codex", "--app", str(self.app), "--output", str(toml))[0], 1)
        self.assertEqual(toml.read_text(), 'model = "keep"\n')

    def test_uninstall_removes_only_matching_entry_with_backup(self):
        destination = self.install()
        self.write_config({"mcpServers": {"other": {"command": "keep"}}, "preferences": [1, 2]})
        self.assertEqual(self.cli("init-config", "--app", str(self.app), "--output", str(self.config))[0], 0)
        before = self.config.read_bytes()
        status, _, error = self.cli("uninstall", "--config", str(self.config))
        self.assertEqual(status, 0, error)
        self.assertFalse(destination.exists())
        self.assertEqual(json.loads(self.config.read_bytes()), {"mcpServers": {"other": {"command": "keep"}}, "preferences": [1, 2]})
        self.assertTrue(any(path.read_bytes() == before for path in self.config.parent.glob("*.pastel-backup-*")))

    def test_uninstall_refuses_foreign_config_entry(self):
        destination = self.install()
        raw = self.write_config({"mcpServers": {"pastel": {"command": "other", "args": ["custom.py"]}}})
        self.assertEqual(self.cli("uninstall", "--config", str(self.config))[0], 1)
        self.assertTrue(destination.is_dir())
        self.assertEqual(self.config.read_bytes(), raw)

    def test_doctor_is_read_only_and_redacts_config_and_pairing(self):
        self.install()
        (setup.managed_directory().parent / "connection.json").write_text("private-token")
        with mock.patch.object(setup, "load_bridge", side_effect=AssertionError("must not connect")):
            status, output, error = self.cli("doctor", "--app", str(self.app))
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output), {"checks": {"python": True, "appleSiliconMac": True, "installedApp": True, "managedBridge": True}, "connected": None, "ready": True})
        self.assertNotIn("private-token", output + error)

    def test_importing_installed_transport_creates_no_unmanaged_cache(self):
        destination = self.install()
        installed = load("installed_pastel_under_test", destination / "pastel_mcp.py")
        self.assertTrue(hasattr(installed.load_bridge(), "PastelBridge"))
        self.assertFalse((destination / "__pycache__").exists())
        installed.verified_install(destination)

    def test_all_five_catalogs_have_identical_nonempty_keys(self):
        catalog = json.loads((SOURCE / "locales.json").read_bytes())
        self.assertEqual(set(catalog), set(setup.LANGUAGES))
        for language in setup.LANGUAGES:
            self.assertEqual(set(catalog[language]), set(catalog["en"]))
            self.assertTrue(all(isinstance(value, str) and value for value in catalog[language].values()))
        status, _, error = self.cli("--lang=zh-Hans", "install", "--app", str(self.home / "missing.app"))
        self.assertEqual(status, 1)
        self.assertIn("应用包", error)


class ReleaseTests(unittest.TestCase):
    def test_archive_allowlist_canonical_source_hashes_and_no_user_data(self):
        with tempfile.TemporaryDirectory(prefix="pastel-release-test-") as temporary:
            output = Path(temporary)
            archive_path = release.build(output, "0.1.0-test.1")
            prefix = "Aquarell-mcp-0.1.0-test.1/"
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                expected = set(release.FILES) | {"VERSION", "LICENSE", "pastel-mcp-bridge.py", "release-manifest.json"}
                self.assertEqual(names, {prefix + name for name in expected})
                self.assertEqual(archive.read(prefix + "pastel-mcp-bridge.py"), setup.bridge_source().read_bytes())
                license_file = SOURCE / "LICENSE" if (SOURCE / "LICENSE").is_file() else SOURCE.parent / "LICENSE"
                self.assertEqual(archive.read(prefix + "LICENSE"), license_file.read_bytes())
                manifest = json.loads(archive.read(prefix + "release-manifest.json"))
                for name, digest in manifest["sha256"].items():
                    self.assertEqual(hashlib.sha256(archive.read(prefix + name)).hexdigest(), digest)
                self.assertEqual(set(manifest["sha256"]), expected - {"release-manifest.json"})
                for name in names:
                    payload = archive.read(name)
                    self.assertNotIn(os.fsencode(str(SOURCE.resolve())), payload)
                    self.assertNotIn(b"connection.json\"", payload if name.endswith("release-manifest.json") else b"")
                    self.assertNotIn("__pycache__", name)
            checksum = archive_path.with_suffix(".zip.sha256").read_text().split()[0]
            self.assertEqual(checksum, hashlib.sha256(archive_path.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                release.build(output, "0.1.0-test.1")

    def test_invalid_version_cannot_traverse_release_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            for value in ("../private", "1.0", "1.0.0/../../other", "1.0.0\n"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    release.build(Path(temporary), value)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_standalone_source_export_exact_files_builds_without_app_repository(self):
        with tempfile.TemporaryDirectory(prefix="pastel-source-export-") as temporary:
            root = Path(temporary)
            destination = root / "github-source"
            release.export_source(destination, "0.1.0-test.3")
            expected = set(release.FILES) | set(release.SOURCE_FILES) | {"VERSION", "LICENSE", "pastel-mcp-bridge.py", "source-manifest.json"}
            actual = {str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()}
            self.assertEqual(actual, expected)
            self.assertFalse((destination / ".git").exists())
            self.assertEqual((destination / "pastel-mcp-bridge.py").read_bytes(), setup.bridge_source().read_bytes())
            manifest = json.loads((destination / "source-manifest.json").read_bytes())
            for name, digest in manifest["sha256"].items():
                self.assertEqual(hashlib.sha256((destination / name).read_bytes()).hexdigest(), digest)
                self.assertNotIn(os.fsencode(str(SOURCE.resolve())), (destination / name).read_bytes())
            standalone = load("standalone_build_under_test", destination / "build-release.py")
            archive = standalone.build(root / "dist", "0.1.0-test.3")
            self.assertTrue(archive.is_file())
            installer = load("standalone_setup_under_test", destination / "pastel_mcp.py")
            self.assertEqual(installer.bridge_source(), (destination / "pastel-mcp-bridge.py").resolve())
            with self.assertRaises(FileExistsError):
                release.export_source(destination, "0.1.0-test.3")
            self.assertEqual((destination / "source-manifest.json").read_bytes(), json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")

    @unittest.skipUnless(setup.supported_host(), "The shipped CLI targets an Apple Silicon Mac.")
    def test_exact_extracted_archive_cli_install_config_doctor_uninstall(self):
        with tempfile.TemporaryDirectory(prefix="pastel-archive-install-") as temporary:
            root = Path(temporary)
            archive_path = release.build(root / "releases", "0.1.0-test.2")
            extracted = root / "extracted"
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extracted)
            cli = extracted / "Aquarell-mcp-0.1.0-test.2/pastel_mcp.py"
            home = root / "新用户 with spaces"
            home.mkdir(mode=0o700)
            app = home / "Applications/Aquarell.app"
            app.mkdir(parents=True)
            (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.bzy.pastel", "CFBundleExecutable": "Pastel"}))
            (app / "Pastel").write_bytes(b"not executable; metadata fixture only")
            environment = dict(os.environ, HOME=str(home), LANG="en_US.UTF-8", LC_ALL="")
            def run(*args):
                result = subprocess.run([sys.executable, str(cli), *args], env=environment,
                                        capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
                return result.stdout.decode("utf-8")
            run("install", "--app", str(app))
            config = json.loads(run("init-config", "--app", str(app)))
            installed_cli = Path(config["mcpServers"]["pastel"]["args"][0])
            self.assertTrue(installed_cli.is_file())
            self.assertNotIn("--allow-edits", config["mcpServers"]["pastel"]["args"])
            self.assertTrue(json.loads(run("doctor", "--app", str(app)))["ready"])
            run("uninstall")
            self.assertFalse(installed_cli.exists())
            self.assertTrue((app / "Pastel").is_file())


if __name__ == "__main__":
    unittest.main()
