# Aquarell MCP release checklist / 发布清单

This checklist records remaining release gates; it does not claim they passed.
本清单列出正式发布前的验收项，不表示这些项目已完成。

The selected repository name is **Aquarell-mcp**. Existing MPL 2.0 licensing
and compatibility identifiers remain unchanged; selecting a name does not
authorize publication or change the license.
已选定仓库名 **Aquarell-mcp**。现有 MPL 2.0 许可和兼容标识保持不变；选定名称
不代表已授权发布或变更许可证。

- [ ] Owner reviews the existing MPL 2.0 license and copyright notices, then
  confirms the Aquarell-mcp repository URL, support channel, and private
  vulnerability-reporting channel. / 所有者核对已有 MPL 2.0 许可和版权声明，确定
  Aquarell-mcp 仓库 URL 及反馈渠道。
- [ ] Upload the actual App Store/TestFlight build and install it on a clean
  Apple Silicon Mac without developer tools or development profiles.
  / 在无开发工具及开发描述文件的干净 Mac 上安装实际发行包。
- [ ] Verify first launch, app detection by bundle ID, wrapper layout, Apple
  signature validation, initial pairing and app editing consent using that
  store build. / 用发行包验证查找、签名、首次配对和编辑授权。
- [ ] Test Python 3.9 and a current Python release, including paths with spaces
  and non-ASCII user names. / 验证最低 Python 版本、空格及非 ASCII 路径。
- [ ] Test install, JSON config merge with unrelated servers, Codex TOML setup,
  client enable/reload, upgrade, config restoration, and uninstall on at least
  two real MCP clients. / 在至少两个真实客户端验收完整安装与卸载流程。
- [ ] Verify read-only app settings, edit opt-in, cancellation, timeouts,
  simultaneous clients, service restart, token revocation, app exit/relaunch,
  focus changes, background behavior and reconnection without edit replay.
  / 验证权限、取消、超时、多客户端及生命周期，确保不重放编辑。
- [ ] Create only disposable artwork; check drawing, layers, undo/redo, native
  save/reopen and exports through the shipped bridge. Preserve unrelated data.
  / 使用测试作品验证绘制、图层、撤销、保存重开和导出，保护其他作品。
- [ ] Record iOS/iPadOS real-device tests separately from the local Mac package;
  do not claim that this installer configures remote devices.
  / 真机验收另行记录，不将本机安装器宣传为远程设备安装器。
- [ ] Run the isolated installer and canonical bridge tests, app-native suites,
  and an actual signed-store-build smoke test. Keep evidence without tokens.
  / 执行隔离安装测试、桥接及 App 原生测试，并保留脱敏证据。
- [ ] Build the archive from a reviewed source revision, inspect its allowlist,
  verify hashes, scan for credentials/private paths and verify extraction and
  install from that exact archive. / 检查实际压缩包清单、哈希及隐私，解压验收。
- [ ] Export a fresh standalone source tree, run its tests and build script
  without the app repository, inspect its manifest, and run hosted CI after
  creating the repository. / 验证独立源码导出、脱离 App 仓库运行及发布后的托管 CI。
- [ ] Publish the bridge only after the owner authorizes GitHub publication;
  publish no app signing files, artwork, connection files or client configs.
  / 获所有者授权后发布，不上传签名文件、作品、连接文件或用户配置。
