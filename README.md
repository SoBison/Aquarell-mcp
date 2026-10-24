# Aquarell-mcp

[简体中文](README.zh-CN.md)

Control the MCP-enabled Aquarell iPad app on an Apple Silicon Mac from an
MCP client. The app provides the drawing tools; this bridge forwards standard
MCP JSON-RPC over stdio to the app's authenticated local HTTP server. It has no
third-party Python dependencies.

This is a preview distribution. An App Store/TestFlight release has not yet been
validated with this package. The app and bridge must be released separately;
this archive does not contain an app, development certificate, provisioning
profile, or App Store credentials. The archive retains the repository's existing
MPL 2.0 `LICENSE` unchanged. The owner must review licensing and copyright notices
before public distribution; this package does not choose a different license.

The GitHub repository name is **Aquarell-mcp**; the public display name is
**Aquarell MCP**. Existing `pastel_*` tool identifiers, `pastel_mcp.py` and
`pastel-mcp-bridge.py` filenames, the `pastel` client-config key, the
`com.bzy.pastel` app bundle identifier, and `PastelMCP` installation/pairing paths
remain unchanged for compatibility. The app may also appear under its legacy
Pastel name. The repository name does not migrate existing configs or local data.

## Requirements

- Apple Silicon Mac that can run the released iPad app.
- MCP-enabled Aquarell installed from App Store or TestFlight. A legacy
  app without MCP will not work. MCP requires iOS 16 or newer in the app; the app
  itself can retain support for earlier systems.
- Python 3.9 or newer, installed separately if `python3 --version` is unavailable.
- A client supporting local stdio MCP servers. No Xcode or Apple developer
  account is needed for this bridge.

## Install

Download and extract a release archive, then open Terminal in its directory:

```sh
python3 pastel_mcp.py install
python3 pastel_mcp.py doctor
```

The installer finds the app by bundle identifier, including apps displayed as
“Aquarell”. If detection fails, add `--app "/Applications/Aquarell.app"` to
`install`, `init-config`, or `doctor`. It reads bundle metadata; the transport
independently validates the app's Apple signature and running process during
pairing. It does not change Gatekeeper or install a development-signed app.

The bridge is installed under the current user's
`~/Library/Application Support/PastelMCP/bridge/`. Upgrades preserve a backup of
the previous managed installation. Modified or extra files are preserved and
must be moved aside before upgrading or uninstalling. No administrator password
is needed. Keep the installed Python interpreter available; configs refer to
its absolute path.

## Configure a client

Generate the common JSON `mcpServers` configuration:

```sh
python3 pastel_mcp.py init-config
```

To merge into a JSON client configuration, pass its path:

```sh
python3 pastel_mcp.py init-config --output "/path/to/client-config.json"
```

Other settings and servers are preserved. Before changing an existing file,
the installer writes an exact backup beside it with `0600` permissions. If a
different `pastel` entry already exists, the command stops. Use `--replace` only
when you intend to back up and replace that entry. Invalid JSON, symlinks,
non-owned files, and files over 1 MiB are rejected. Client-specific config paths
are intentionally not guessed or changed automatically.

For Codex, print a TOML section:

```sh
python3 pastel_mcp.py init-config --format codex
```

Add that section to your existing Codex config, replacing an existing
`mcp_servers.pastel` section if applicable. TOML is never automatically merged or
overwritten. Enable or reload the server in your MCP client after configuration.
No token is included in either format. Field names follow the
[official Codex MCP configuration documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

Generated configs default to a read-only bridge, including when the app already
allows editing. The bridge checks the authenticated app's current tool definitions
and blocks tools without an explicit read-only annotation and unknown methods.
To permit edit requests and request app editing access at launch, add
`--allow-edits` when generating config:

```sh
python3 pastel_mcp.py init-config --allow-edits
```

The app's AI Control settings also remain authoritative. This flag cannot bypass
the app's edit switch. Read-only mode applies to this bridge connection; it does
not revoke editing access from other clients or change the app's settings.

## Pair and check

On the first client connection, the bridge can open the app and pass a temporary
loopback callback. Only the matching Apple-signed app and its verified process
can publish credentials. Credentials stay in the current user's private local
pairing file. They are never written into a client config or command arguments.
Keep the app window open while using MCP; iOS can stop the service in the
background. Normal macOS focus changes are supported.

If the app was already running before pairing, save your work, quit normally,
and reconnect the MCP client. The bridge never force-quits the app. Once paired,
running bridges subscribe to connection updates for service restarts and token
changes. If all bridges were closed while credentials were revoked, normal app
exit and pairing may still be required. A failed or uncertain edit is never
automatically retried; inspect the artwork and read current state first.

With the app running and paired:

```sh
python3 pastel_mcp.py doctor --connect
```

`doctor` reports only fixed check names, booleans, and tool count. Without
`--connect`, it only checks files and app metadata. With `--connect`, it performs
MCP initialization and tool discovery, without launching the app or modifying
artwork. Its connection subscription may refresh the private pairing file.
Exit status `0` means the selected checks passed; `1` means they did not. No
successful file-only check proves actual app connectivity or client compatibility.

For translated setup messages, put `--lang zh-Hans`, `--lang de`, `--lang fr`, or
`--lang ja` before the command. The default follows the environment language.
The underlying protocol transport currently reports its fixed errors in English.

## Remove

Disable the server in your client first, then run:

```sh
python3 pastel_mcp.py uninstall
```

To also remove this installation's entry from a JSON client config, add
`--config "/path/to/client-config.json"`. An exact private backup is retained.
It refuses to remove another installation's entry. Manually remove a generated
Codex TOML section. Shared pairing files, previous installation backups, the app,
and all artwork are preserved. Other clients may still depend on shared pairing.

## Source and validation

In the app repository, the sole maintained transport source is
`Tools/pastel-mcp-bridge.py`. The installer reads it directly from a checkout;
`build-release.py` copies it into the archive. Do not maintain a second transport
implementation under this directory.

```sh
python3 -m unittest discover -s mcp/tests -v
python3 Tests/test-mcp-bridge.py
python3 mcp/build-release.py --output output/mcp-release
```

To prepare a **separate GitHub source repository** without publishing it, export
a new directory from the app checkout:

```sh
python3 mcp/build-release.py --export-source output/Aquarell-mcp
```

The exporter copies only the reviewed package allowlist, tests, build script,
existing license and canonical transport at export time. It refuses an existing
destination and copies no `.git` directory, app code, user config or credentials.
The exported tree works independently of the app repository:

```sh
python3 -m unittest discover -s tests -v
python3 build-release.py --output dist
```

Its GitHub workflow tests Python 3.9 on Linux and the current Python on Linux and
macOS, then builds the same 11-file end-user ZIP. The workflow uses the official
[checkout](https://github.com/actions/checkout) and
[setup-python](https://github.com/actions/setup-python) actions with read-only
repository permissions and no publishing step. The preview source is published
at [SoBison/Aquarell-mcp](https://github.com/SoBison/Aquarell-mcp). Its
[first hosted CI run](https://github.com/SoBison/Aquarell-mcp/actions/runs/40106901376)
passed for commit `6926a2656a0ab3e68208f54abe44882ebace869a`; see
[Actions](https://github.com/SoBison/Aquarell-mcp/actions) for later revisions.
CI uses synthetic app metadata; it does not replace
real signed-app or store-build acceptance. Do not edit the exported bridge and
the app's transport independently; regenerate the export from reviewed canonical
source for each release.

Each release contains a SHA-256 file manifest and a separate archive checksum.
Checksums verify accidental corruption; they are not proof of a trusted
publisher. Verify the source of the release before running it. Packaging uses an
explicit file allowlist, never a copy of a user's installed pairing directory.
See the [support and verification matrix](SUPPORT.md), [security notes](SECURITY.md)
and [release checklist](RELEASE_CHECKLIST.md).
