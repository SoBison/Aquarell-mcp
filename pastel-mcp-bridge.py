#!/usr/bin/env python3
"""Private, local stdio transport for the installed Pastel iOS-on-Mac app.

No MCP SDK or third-party dependencies are required (Python 3.9+). stdout is
reserved for newline-delimited JSON-RPC. Credentials never enter command-line
arguments, configuration, or diagnostics.
"""

import argparse
import base64
import concurrent.futures
import contextlib
import fcntl
import http.client
import http.server
import json
import os
from pathlib import Path
import plistlib
import secrets
import stat
import subprocess
import sys
import threading
import time
import urllib.parse


MAX_REQUEST = 8 * 1024 * 1024
MAX_RESPONSE = 32 * 1024 * 1024
MAX_DESCRIPTOR = 16 * 1024
MODERN_PROTOCOL = "2026-07-28"
PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"
CONNECTION_ERROR = (
    "Pastel is unavailable. Bring Pastel to the foreground and enable AI Control (MCP). "
    "This request was not retried. If an edit may have run, inspect the artwork before "
    "retrying; after a service restart, read its state before making a new edit."
)


class BridgeError(Exception):
    """A safe, fixed diagnostic that never embeds server data or credentials."""


def request_metadata(message):
    params = message.get("params")
    metadata = params.get("_meta") if isinstance(params, dict) else None
    return metadata if isinstance(metadata, dict) else None


def metadata_header(value):
    """Encode modern Mcp-Name values without creating ambiguous HTTP headers."""
    if not isinstance(value, str):
        raise BridgeError("MCP request metadata is invalid.")
    plain = (value == value.strip(" \t") and value.isascii()
             and all(char == "\t" or 0x20 <= ord(char) <= 0x7e for char in value)
             and not (value.startswith("=?base64?") and value.endswith("?=")))
    encoded = value if plain else "=?base64?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="
    if len(encoded) > 8192:
        raise BridgeError("MCP request metadata exceeds the HTTP header limit.")
    return encoded


def descriptor_paths():
    home = Path.home()
    return [
        home / "Library/Application Support/PastelMCP/connection.json",
        home / "Library/Containers/com.bzy.pastel/Data/Library/Application Support/PastelMCP/connection.json",
    ]


def validate_descriptor(value):
    """Validate data shared by a private file and the app's local callback."""
    try:
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
            raise ValueError()
        pid = value.get("pid")
        if type(pid) is not int or not 0 < pid <= 2147483647:
            raise ValueError()
        os.kill(pid, 0)
        endpoint = urllib.parse.urlsplit(value["endpoint"])
        if (endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1"
                or not endpoint.port or endpoint.path != "/mcp"
                or endpoint.username is not None or endpoint.password is not None
                or endpoint.query or endpoint.fragment):
            raise ValueError()
        token = value.get("token")
        if (not isinstance(token, str) or not 32 <= len(token) <= 256
                or not token.isascii() or not token.replace("-", "").isalnum()):
            raise ValueError()
        started = value.get("startedAt")
        if not isinstance(started, str) or not 1 <= len(started) <= 128 or not started.isprintable():
            raise ValueError()
        result = {"version": 1, "pid": pid, "endpoint": "http://127.0.0.1:%d/mcp" % endpoint.port,
                  "token": token, "startedAt": started}
        if "sequence" in value:
            sequence = value["sequence"]
            if type(sequence) is not int or not 1 <= sequence <= 9007199254740991:
                raise ValueError()
            result["sequence"] = sequence
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise BridgeError("Pastel connection data is missing, stale, or invalid.") from None


def connection_from_descriptor(value):
    return {"pid": value["pid"], "port": urllib.parse.urlsplit(value["endpoint"]).port,
            "token": value["token"]}


def read_descriptor(path):
    """Read one bounded, current-user-only regular file without following links."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > MAX_DESCRIPTOR):
                raise BridgeError("Pastel connection file must be a private 0600 regular file owned by this user.")
            value = json.loads(stream.read(MAX_DESCRIPTOR + 1))
        return connection_from_descriptor(validate_descriptor(value))
    except BridgeError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise BridgeError("Pastel connection file is missing, stale, or invalid.") from None


@contextlib.contextmanager
def private_directory(path):
    """Keep directory operations anchored to an owned, non-symlink directory."""
    directory_fd = None
    try:
        if path.name != "connection.json":
            raise BridgeError("Local pairing requires a private connection.json file.")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(directory_fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise BridgeError("Pastel pairing directory must be a private 0700 directory owned by this user.")
        yield directory_fd
    except BridgeError:
        raise
    except OSError:
        raise BridgeError("Pastel's private local pairing directory could not be accessed.") from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


@contextlib.contextmanager
def private_lock(directory_fd, name, timeout, message):
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise BridgeError("Pastel's local connection lock must be private to this user.")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BridgeError(message) from None
                time.sleep(0.01)
        yield
    finally:
        os.close(fd)


def persist_descriptor(path, value):
    """Publish only connection.json; never replace the installed bridge script."""
    temporary = ".connection-" + secrets.token_hex(16) + ".tmp"
    with private_directory(path) as directory_fd, private_lock(directory_fd, ".connection.lock", 2,
            "Another Pastel bridge is publishing connection data. Reconnect after it finishes."):
        try:
            try:
                info = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                info = None
            if info and (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                         or stat.S_IMODE(info.st_mode) != 0o600):
                raise BridgeError("Pastel's existing connection file is not a private 0600 regular file.")
            descriptor = validate_descriptor(value)
            if info:
                fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                with os.fdopen(fd, "rb") as stream:
                    current_info = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(current_info.st_mode) or current_info.st_uid != os.getuid()
                            or stat.S_IMODE(current_info.st_mode) != 0o600):
                        raise BridgeError("Pastel's existing connection file is not a private 0600 regular file.")
                    try:
                        current = validate_descriptor(json.loads(stream.read(MAX_DESCRIPTOR + 1))) if current_info.st_size <= MAX_DESCRIPTOR else None
                    except (BridgeError, ValueError):
                        current = None
                if current is not None:
                    if current["pid"] != descriptor["pid"]:
                        raise BridgeError("Pastel's connection file belongs to another live app process.")
                    if current.get("sequence", 0) > descriptor.get("sequence", 0):
                        # Another live callback already published newer data.
                        # Acknowledge this delivery without rolling back the file.
                        return
                    if "sequence" in current and current.get("sequence") == descriptor.get("sequence"):
                        if any(current[key] != descriptor[key] for key in ("pid", "endpoint", "token")):
                            raise BridgeError("Pastel returned conflicting connection data for one sequence.")
                        return
            data = json.dumps(descriptor, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(data) > MAX_DESCRIPTOR:
                raise BridgeError("Pastel connection data exceeds its size limit.")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory_fd)
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        except OSError:
            raise BridgeError("Pastel's private connection file could not be saved.") from None
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


@contextlib.contextmanager
def pairing_lock(path, timeout):
    """Serialize startup across bridge processes as well as request threads."""
    with private_directory(path) as directory_fd, private_lock(directory_fd, ".pairing.lock", timeout,
            "Another Pastel bridge is pairing. Wait for it to finish and reconnect."):
        yield


def app_bundle(application):
    for bundle in [application / "Wrapper/Pastel.app", application]:
        try:
            with (bundle / "Info.plist").open("rb") as stream:
                info = plistlib.load(stream)
            executable = info.get("CFBundleExecutable")
            if (isinstance(info, dict) and info.get("CFBundleIdentifier") == "com.bzy.pastel"
                    and isinstance(executable, str) and executable and Path(executable).name == executable
                    and (bundle / executable).is_file()):
                return bundle
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
    raise BridgeError("The installed application is not a valid Pastel app bundle.")


def signed_identity(bundle):
    requirement = '=anchor apple generic and identifier "com.bzy.pastel"'
    verified = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", "-R", requirement, str(bundle)],
                              capture_output=True, timeout=8, check=False)
    details = subprocess.run(["/usr/bin/codesign", "-d", "--verbose=4", str(bundle)],
                             capture_output=True, timeout=8, check=False)
    fields = dict(line.split("=", 1) for line in details.stderr.decode("utf-8", errors="replace").splitlines()
                  if line.startswith(("Identifier=", "CDHash=")))
    if (verified.returncode or details.returncode or fields.get("Identifier") != "com.bzy.pastel"
            or not fields.get("CDHash")):
        raise BridgeError("Pastel's local pairing requires a valid Apple-signed app matching the installation.")
    return fields["CDHash"]


def verify_callback_process(value, application):
    """A translocated iPad app must have the installed signature and own its port."""
    try:
        process = subprocess.run(["/bin/ps", "-ww", "-p", str(value["pid"]), "-o", "uid=,comm="],
                                 capture_output=True, timeout=5, check=False)
        fields = process.stdout.decode("utf-8").strip().split(None, 1)
        if process.returncode or len(fields) != 2 or int(fields[0]) != os.getuid():
            raise ValueError()
        running_executable = Path(fields[1])
        running_bundle = app_bundle(running_executable.parent)
        with (running_bundle / "Info.plist").open("rb") as stream:
            executable = plistlib.load(stream)["CFBundleExecutable"]
        if running_executable != running_bundle / executable:
            raise ValueError()
        if signed_identity(running_bundle) != signed_identity(app_bundle(application)):
            raise ValueError()
        port = urllib.parse.urlsplit(value["endpoint"]).port
        listeners = subprocess.run(["/usr/sbin/lsof", "-nP", "-a", "-p", str(value["pid"]),
                                    "-iTCP@127.0.0.1:%d" % port, "-sTCP:LISTEN", "-Fpn"],
                                   capture_output=True, timeout=5, check=False)
        lines = listeners.stdout.decode("utf-8").splitlines()
        if (listeners.returncode or "p%d" % value["pid"] not in lines
                or "n127.0.0.1:%d" % port not in lines):
            raise ValueError()
    except BridgeError:
        raise
    except (OSError, ValueError, KeyError, UnicodeError, subprocess.TimeoutExpired):
        raise BridgeError("Pastel's pairing process or loopback listener could not be verified.") from None


class PairingHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_POST(self):
        server = self.server
        lengths = self.headers.get_all("Content-Length", [])
        types = self.headers.get_all("Content-Type", [])
        if (self.client_address[0] != "127.0.0.1" or self.path != server.callback_path
                or "Origin" in self.headers):
            self.reply(403)
            return
        if server.completed.is_set() and not server.allow_refresh:
            self.reply(409)
            return
        if ("Transfer-Encoding" in self.headers or len(lengths) != 1
                or len(lengths[0]) > 5
                or not lengths[0].isascii() or not lengths[0].isdigit()
                or not 0 < int(lengths[0]) <= MAX_DESCRIPTOR
                or len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json"):
            self.reply(400)
            return
        try:
            data = self.rfile.read(int(lengths[0]))
            if len(data) != int(lengths[0]):
                raise ValueError()
            value = validate_descriptor(json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
            if server.target_pid is not None and value["pid"] != server.target_pid:
                raise ValueError()
            if server.descriptor is not None and server.allow_refresh:
                if value.get("sequence", 0) <= server.descriptor.get("sequence", 0):
                    self.reply(409)
                    return
            server.verify(value, server.application)
        except (BridgeError, ValueError, OSError):
            self.reply(403)
            return
        try:
            persist_descriptor(server.destination, value)
        except BridgeError as error:
            server.error = error
            server.completed.set()
            self.reply(500)
            return
        server.descriptor = value
        server.target_pid = value["pid"]
        server.completed.set()
        self.reply(200)


class PairingServer(http.server.HTTPServer):
    allow_reuse_address = False

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address

    def handle_error(self, request, client_address):
        # The standard implementation prints tracebacks including request data.
        pass


class LocalPairing:
    def __init__(self, application, destination, verifier=None, allow_refresh=False, target_pid=None):
        self.server = PairingServer(("127.0.0.1", 0), PairingHandler)
        self.server.callback_path = "/pair/" + secrets.token_hex(32)
        self.server.completed = threading.Event()
        self.server.application = application
        self.server.destination = destination
        self.server.verify = verifier or verify_callback_process
        self.server.descriptor = None
        self.server.error = None
        self.server.allow_refresh = allow_refresh
        self.server.target_pid = target_pid
        self.url = "http://127.0.0.1:%d%s" % (self.server.server_port, self.server.callback_path)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class PastelBridge:
    def __init__(self, paths=None, app=None, launch=True, startup_timeout=35, request_timeout=150,
                 read_only=False):
        self.paths = [Path(p) for p in (paths if paths is not None else descriptor_paths())]
        self.app = Path(app) if app else None
        self.launch = launch
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self.read_only = read_only
        self.launch_lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.cancellation_lock = threading.Lock()
        self.modern_requests = {}
        self.last_launch = float("-inf")
        self.protocol_version = "2025-11-25"
        self.pairing = None

    def close(self):
        with self.launch_lock:
            if self.pairing is not None:
                self.pairing.__exit__(None, None, None)
                self.pairing = None

    def current_connection(self):
        for path in self.paths:
            try:
                return read_descriptor(path)
            except BridgeError:
                continue
        return None

    def launch_app(self):
        if not self.launch:
            raise BridgeError(CONNECTION_ERROR)
        # A concurrent request must not start a second app or interrupt an edit.
        with self.launch_lock:
            value = self.current_connection()
            if value is not None:
                return value
            if time.monotonic() - self.last_launch < 5:
                raise BridgeError(CONNECTION_ERROR)
            candidates = [self.app] if self.app else [Path.home() / "Applications/Pastel.app", Path("/Applications/Pastel.app")]
            application = next((p for p in candidates if p and p.is_dir()), None)
            if application is None:
                raise BridgeError("Pastel is not installed. Install Pastel.app in ~/Applications or /Applications.")
            with pairing_lock(self.paths[0], self.startup_timeout):
                value = self.current_connection()
                if value is not None:
                    return value
                try:
                    pairing = LocalPairing(application, self.paths[0], allow_refresh=True)
                    pairing.__enter__()
                    try:
                        command = ["/usr/bin/open", "-a", str(application), "--args", "--pastel-mcp"]
                        if not self.read_only:
                            command.append("--pastel-mcp-allow-edits")
                        command.extend(["--pastel-mcp-callback", pairing.url])
                        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL, timeout=10, check=False)
                        if result.returncode:
                            raise BridgeError("Pastel could not be opened. Open it manually and enable AI Control (MCP).")
                        if not pairing.server.completed.wait(self.startup_timeout):
                            raise BridgeError("Pastel did not complete local pairing. If it is already running, save your work, "
                                              "quit it normally, then reconnect. The bridge never quits the app.")
                        if pairing.server.error:
                            raise pairing.server.error
                        if self.pairing is not None:
                            self.pairing.__exit__(None, None, None)
                        self.pairing = pairing
                        # A different subscribed bridge may have published an
                        # even newer sequence while this callback was verified.
                        return self.current_connection() or connection_from_descriptor(pairing.server.descriptor)
                    finally:
                        if self.pairing is not pairing:
                            pairing.__exit__(None, None, None)
                except (OSError, subprocess.TimeoutExpired):
                    raise BridgeError("Pastel could not be opened or paired. Open it manually and enable AI Control (MCP).") from None
                finally:
                    self.last_launch = time.monotonic()

    def connection(self):
        value = self.current_connection()
        if value is not None:
            return value
        return self.launch_app()

    def forward(self, message):
        method = message.get("method")
        if self.read_only and method not in {
                "initialize", "server/discover", "ping", "tools/list", "tools/call", "resources/list",
                "resources/templates/list", "resources/read", "prompts/list", "prompts/get",
                "notifications/initialized", "notifications/cancelled"}:
            raise BridgeError("This MCP connection is read-only; this method is not permitted.")
        connection = self.connection()
        if self.read_only and method == "tools/call":
            # Check the authenticated app's current definitions, including when
            # reusing an editable connection or after the app updates. Fail closed
            # on missing/malformed annotations; never trust client-supplied hints.
            params = message.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            probe_params = {}
            metadata = request_metadata(message)
            if metadata is not None:
                probe_params["_meta"] = dict(metadata)
            listed = self.request({"jsonrpc": "2.0", "id": "pastel-read-only-" + secrets.token_hex(16),
                                   "method": "tools/list", "params": probe_params}, connection)
            result = listed.get("result") if isinstance(listed, dict) else None
            definitions = result.get("tools") if isinstance(result, dict) else None
            matches = [tool for tool in definitions if isinstance(tool, dict) and tool.get("name") == name] if isinstance(definitions, list) else []
            if (not isinstance(name, str) or len(matches) != 1
                    or not isinstance(matches[0].get("annotations"), dict)
                    or matches[0]["annotations"].get("readOnlyHint") is not True):
                raise BridgeError("This MCP connection is read-only; this tool is not permitted.")
        result = self.request(message, connection)
        if message.get("method") in {"initialize", "server/discover"} and isinstance(result, dict):
            initialized = result.get("result", {})
            capabilities = initialized.get("capabilities", {}) if isinstance(initialized, dict) else {}
            experimental = capabilities.get("experimental", {}) if isinstance(capabilities, dict) else {}
            extensions = capabilities.get("extensions", {}) if isinstance(capabilities, dict) else {}
            local_refresh = ((isinstance(experimental, dict) and experimental.get("pastel/localConnection") == {"subscribe": True})
                             or (isinstance(extensions, dict) and extensions.get("com.bzy.pastel/localConnection") == {"subscribe": True}))
            if local_refresh:
                self.subscribe_local_connection(connection, request_metadata(message))
        return result

    def subscribe_local_connection(self, connection, metadata=None):
        # Only discovery/initialize (reads) negotiate this extension. Never replay an edit
        # when credentials rotate or a request's result is uncertain.
        with self.launch_lock:
            if self.pairing is not None and self.pairing.server.target_pid == connection["pid"]:
                return
            candidates = [self.app] if self.app else [Path.home() / "Applications/Pastel.app", Path("/Applications/Pastel.app")]
            application = next((p for p in candidates if p and p.is_dir()), None)
            if application is None:
                raise BridgeError("Pastel's installed app is required to verify local connection refresh.")
            pairing = LocalPairing(application, self.paths[0], allow_refresh=True, target_pid=connection["pid"])
            pairing.__enter__()
            try:
                params = {"callback": pairing.url}
                if metadata is not None:
                    params["_meta"] = dict(metadata)
                result = self.request({"jsonrpc": "2.0", "id": "pastel-local-" + secrets.token_hex(16),
                                       "method": "pastel/localConnection/subscribe", "params": params}, connection)
                subscribed = result.get("result") if isinstance(result, dict) else None
                if (not isinstance(subscribed, dict) or subscribed.get("subscribed") is not True
                        or not pairing.server.completed.wait(self.startup_timeout) or pairing.server.error):
                    raise BridgeError("Pastel local connection refresh could not be registered. Reconnect after checking AI Control settings.")
                if self.pairing is not None:
                    self.pairing.__exit__(None, None, None)
                self.pairing = pairing
            finally:
                if self.pairing is not pairing:
                    pairing.__exit__(None, None, None)

    def request(self, message, connection):
        # HTTPConnection ignores proxy environment variables and cannot redirect a
        # bearer token to another host. No HTTP request is automatically retried.
        client = http.client.HTTPConnection("127.0.0.1", connection["port"], timeout=self.request_timeout)
        try:
            body = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(body) > MAX_REQUEST:
                raise BridgeError("MCP request exceeds Pastel's 8 MiB limit.")
            metadata = request_metadata(message)
            declared = metadata.get(PROTOCOL_VERSION_META) if metadata else None
            version = declared if isinstance(declared, str) else self.protocol_version
            if (not isinstance(version, str) or len(version) > 64
                    or not version.isascii() or not version or not all(0x21 <= ord(c) <= 0x7e for c in version)):
                raise BridgeError("MCP protocol version metadata is invalid.")
            headers = {
                "Authorization": "Bearer " + connection["token"],
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": version,
            }
            if declared is not None:
                method = message.get("method")
                if (not isinstance(method, str) or not method or not method.isascii()
                        or not all(0x21 <= ord(char) <= 0x7e for char in method)):
                    raise BridgeError("MCP method metadata is invalid.")
                headers["Mcp-Method"] = method
                if method in {"tools/call", "resources/read", "prompts/get"}:
                    params = message.get("params", {})
                    name = params.get("uri" if method == "resources/read" else "name")
                    headers["Mcp-Name"] = metadata_header(name)
            client.request("POST", "/mcp", body, headers)
            response = client.getresponse()
            if response.status == 202 and "id" not in message:
                response.read(MAX_RESPONSE + 1)
                return None
            modern_error_status = declared is not None and response.status in {400, 404}
            if response.status != 200 and not modern_error_status:
                raise BridgeError(CONNECTION_ERROR)
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise BridgeError("Pastel response exceeds the bridge's 32 MiB limit.")
            result = json.loads(data)
            if (not isinstance(result, dict) or result.get("jsonrpc") != "2.0"
                    or result.get("id") != message.get("id")
                    or ("result" in result) == ("error" in result)):
                raise BridgeError("Pastel returned an invalid MCP response. This request was not retried.")
            if modern_error_status and not isinstance(result.get("error"), dict):
                raise BridgeError("Pastel returned an invalid MCP error response. This request was not retried.")
            if message.get("method") == "initialize" and isinstance(result.get("result"), dict):
                version = result["result"].get("protocolVersion")
                if isinstance(version, str):
                    self.protocol_version = version
            return result if "id" in message else None
        except BridgeError:
            raise
        except (OSError, ValueError, http.client.HTTPException):
            raise BridgeError(CONNECTION_ERROR) from None
        finally:
            client.close()

    def write(self, message):
        value = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        with self.output_lock:
            sys.stdout.write(value + "\n")
            sys.stdout.flush()

    @staticmethod
    def cancellation_key(value):
        if type(value) not in {str, int, float}:
            return None
        return (type(value).__name__, value)

    def track_modern_request(self, message):
        metadata = request_metadata(message)
        key = self.cancellation_key(message.get("id"))
        if key is None or not metadata or metadata.get(PROTOCOL_VERSION_META) != MODERN_PROTOCOL:
            return None
        with self.cancellation_lock:
            if key in self.modern_requests:
                return None
            ticket = {"key": key, "cancelled": False}
            self.modern_requests[key] = ticket
            return ticket

    def mark_cancelled(self, message):
        params = message.get("params")
        if message.get("method") != "notifications/cancelled" or not isinstance(params, dict):
            return
        key = self.cancellation_key(params.get("requestId"))
        with self.cancellation_lock:
            if key in self.modern_requests:
                self.modern_requests[key]["cancelled"] = True

    def handle(self, message, ticket=None):
        self.mark_cancelled(message)
        ticket = ticket if ticket is not None else self.track_modern_request(message)
        try:
            with self.cancellation_lock:
                if ticket is not None and ticket["cancelled"]:
                    return
            result = self.forward(message)
            if result is not None:
                with self.cancellation_lock:
                    if ticket is None or not ticket["cancelled"]:
                        self.write(result)
        except BridgeError as error:
            if "id" in message:
                with self.cancellation_lock:
                    if ticket is None or not ticket["cancelled"]:
                        self.write({"jsonrpc": "2.0", "id": message["id"],
                                    "error": {"code": -32001, "message": str(error)}})
        finally:
            if ticket is not None:
                with self.cancellation_lock:
                    if self.modern_requests.get(ticket["key"]) is ticket:
                        self.modern_requests.pop(ticket["key"])

    def serve(self):
        # Keep reading while long exports run so cancellation can reach Pastel.
        # Bound pending work to avoid unbounded queues from a broken MCP client.
        slots = threading.BoundedSemaphore(16)
        notification_slots = threading.BoundedSemaphore(16)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor, \
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as notifications:
            while True:
                data = sys.stdin.buffer.readline(MAX_REQUEST + 2)
                if not data:
                    break
                if len(data) > MAX_REQUEST + 1:
                    while data and not data.endswith(b"\n"):
                        data = sys.stdin.buffer.readline(MAX_REQUEST + 2)
                    self.write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "MCP input exceeds 8 MiB."}})
                    continue
                try:
                    message = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeError):
                    self.write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON."}})
                    continue
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
                    self.write({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid JSON-RPC request."}})
                    continue
                is_notification = message["method"].startswith("notifications/")
                pending_slots = notification_slots if is_notification else slots
                self.mark_cancelled(message)
                if not pending_slots.acquire(blocking=False):
                    if "id" in message:
                        self.write({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32001, "message": "Too many pending Pastel requests."}})
                    continue
                target = notifications if is_notification else executor
                ticket = self.track_modern_request(message)
                future = target.submit(self.handle, message, ticket)
                future.add_done_callback(lambda _, semaphore=pending_slots: semaphore.release())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection-file", type=Path, help="Use a specific private app connection file.")
    parser.add_argument("--app", type=Path, help="Installed Pastel.app path (optional).")
    parser.add_argument("--no-launch", action="store_true", help="Do not open the app when disconnected.")
    parser.add_argument("--read-only", action="store_true", help="Enforce read-only tools on this bridge, including reused connections; do not grant editing on launch.")
    parser.add_argument("--pair-only", action="store_true", help="Pair or reuse the installed app, print safe metadata, and exit.")
    args = parser.parse_args()
    bridge = PastelBridge(paths=[args.connection_file] if args.connection_file else None,
                          app=args.app, launch=not args.no_launch, read_only=args.read_only)
    try:
        if args.pair_only:
            value = bridge.connection()
            print(json.dumps({"paired": True, "pid": value["pid"], "endpoint": "http://127.0.0.1:%d/mcp" % value["port"]}))
        else:
            bridge.serve()
    except BridgeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        bridge.close()


if __name__ == "__main__":
    sys.exit(main())
