# Aquarell MCP security / 安全说明

These notes apply to the **Aquarell-mcp** repository and its local bridge.
Existing internal names do not change the security boundaries below.
本说明适用于 **Aquarell-mcp** 仓库及其本地桥接；保留的内部名称不改变以下安全边界。

- The package is a local stdio bridge for an Apple Silicon Mac. It does not
  expose an unauthenticated internet server, configure port forwarding, or
  install an OAuth service. Remote iPad/LAN setup is outside this installer.
- Local app HTTP requests use a bearer token stored in a private `0600` file
  under a `0700` directory. Do not upload that file, installed pairing folders,
  diagnostic dumps, artwork, app containers, signing files, or client configs.
- First pairing verifies the process owner, matching Apple-signed app identity,
  and ownership of the exact loopback listener. Do not disable those checks to
  make an unsupported or unsigned app work.
- Generated configs default to a read-only bridge. It permits only known read
  methods and tools whose current authenticated app definition explicitly marks
  them read-only, even if the app permits edits. `--allow-edits` permits write
  requests but cannot bypass the app's editing switch. Treat an MCP client with
  edit access as able to modify the artwork you open.
- No edit is automatically replayed after a timeout, token change, or failed
  connection. Check document state before retrying with a new request ID.
- `doctor` does not print tokens, file contents, artwork names, or app responses.
  `doctor --connect` performs read-only protocol discovery and subscribes to
  local connection refresh; it can update the private connection file.
- The installer refuses final symlinks, unowned destination files, and modified
  managed installations. JSON config changes preserve exact private backups.
  Backups can contain other clients' secrets; keep them private and do not
  attach them to a public issue.
- The distribution builder uses a fixed source allowlist. It never packages
  a user's `Library`, `.codex`, app data, or build/signing output. The bundled
  SHA-256 manifest is an integrity aid, not a publisher signature.
- Do not post security vulnerabilities publicly with tokens or personal data.
  Before a public release, the owner must designate a private reporting channel.
  This preview intentionally does not invent a contact address or choose a new
  license; the archive retains the repository's existing MPL 2.0 license file.

此包仅配置 Apple Silicon Mac 本地 MCP 连接，不提供互联网或远程 iPad 连接安装。
令牌只应留在本机私有配对文件中；配置备份也可能含其他服务的凭据，不要上传。
生成的配置默认在桥接层限制为只读，`--allow-edits` 不能绕过 App 编辑开关。
失败的编辑不会自动重试，重试前先读取作品状态。发布前由所有者核对已有许可证、
发布来源和私密漏洞反馈渠道。
