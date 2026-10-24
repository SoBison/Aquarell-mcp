# Aquarell MCP support and verification status / 支持与验收状态

Repository name: **Aquarell-mcp**. Existing internal `pastel` identifiers and
paths remain stable as described in the [README](README.md).
仓库名为 **Aquarell-mcp**；已有内部 `pastel` 标识与路径保持兼容，详见 README。

This preview separates implemented features from release acceptance. A tool
count is not a claim that every platform, client, or store build has passed.
本预览版本将已实现功能与发行验收分开；工具数量不代表所有平台、客户端和发行包均已通过。

## Platform matrix / 平台范围

| Environment / 环境 | Package behavior / 安装包行为 | Verification / 验证状态 |
| --- | --- | --- |
| Apple Silicon Mac + MCP-enabled iPad app | Local stdio bridge; app discovery, signature-checked loopback pairing | Installed development-signed app verified on the existing Mac: 113-tool discovery, modern/legacy stdio and read-only write rejection; actual App Store/TestFlight build still required / 已在现有 Mac 验证安装后的开发签名版：113 项工具发现、新旧协议 stdio 连接及只读写入拦截，发行包待验收 |
| Clean Mac with no Xcode/account/profile | No developer tools or signing account required by bridge installer | Temporary-HOME and exact-archive CLI lifecycle tests pass; a separate clean physical Mac is unverified / 临时 HOME 及压缩包安装流程测试通过，独立干净真机待验证 |
| Intel Mac | Rejected by this installer; it targets the iPad app on Apple Silicon | Not supported / 不支持 |
| iPad/iPhone, iOS 16+ | App-native MCP can be enabled; remote direct HTTP/LAN setup is separate | Physical iOS 16 device, local-network consent and cross-device interoperability unverified / iOS 16 真机、局域网授权及跨设备连接待验证 |
| iOS 15 | App deployment target retained; MCP unavailable | Compile-time availability guards required; physical iOS 15 runtime unverified / 已保留可用性保护，iOS 15 真机运行待验证 |
| Other desktop operating systems | This local iPad-app installer is not provided | Not supported by this package / 此包不支持 |
| Generic JSON `mcpServers` clients | Config generation and opt-in safe merge | Temporary-file tests pass; each real client needs validation / 文件测试通过，真实客户端需分别验收 |
| Codex | TOML snippet generated without modifying existing TOML | Snippet generation tested; fresh-client install/reload acceptance required / 配置生成已测试，干净客户端安装与重载待验收 |

The app must be available in the Mac section of its App Store/TestFlight release
and meet Apple's hardware/OS eligibility. This package does not make an iOS-only
listing installable on every Mac. It does not bypass app distribution, signature,
Gatekeeper, device registration, permissions, or the app's editing switch.
App 必须允许其发行版安装在符合 Apple 要求的 Mac 上；此包不改变发行、签名、硬件、
系统或权限限制，也不会绕过 App 编辑开关。

## Feature scope / 功能范围

The app implements **113 tools**, also discovered through the installed signed
development app: the earlier 68-tool foundation,
plus brush management (10), advanced canvas controls (12), palettes (11),
groups (5), workflow controls (5), and close/resize (2). Discover the actual
catalog at runtime; availability and input schemas come from the connected app.
App 已实现 **113 个工具**，并已通过安装后的开发签名版实际发现：已有 68 项，新增
画笔管理 10 项、画布高级控制 12 项、
色板 11 项、图层组 5 项、工作流 5 项及关闭/调整画布 2 项。实际可用目录和参数以
连接 App 后发现的工具为准。

Core operations include artwork discovery/create/open/save, previews, layered
editing, masks, selections, adjustments, brush strokes, colors, editable text,
image import and chunked export download. The expanded work adds Liquify,
Smudge, inspectable brush properties, persisted palettes and groups, canvas workflows, DPI,
animation settings/frame holds, and animation exports. Timed animation playback
is not started by the view-control tool. The catalog and each tool's schema
define which editor actions are available.
基础功能涵盖作品、图层、蒙版、选区、调整、笔触、颜色、可编辑文字、图片导入和
分块导出；扩展包括液化、涂抹、画笔参数、持久化色板和图层组、画布工作流、DPI、
动画设置及停留时长与动画导出。动画视图工具不会启动定时播放；具体开放的编辑
操作以工具目录及各工具参数定义为准。

The existing development Mac also passed synthetic artwork creation, drawing,
rename, undo/redo, save, PNG download and native close checks through the
installed bridge. Pixel comparisons confirmed restoration of the pre-test
artwork. This is development-build evidence on one Mac; it does not establish
App Store/TestFlight acceptance, a clean-machine installation, vendor-client
interoperability, physical iOS coverage or LAN behavior. Keep native regression
evidence tied to the reviewed source revision, and run a separate smoke test on
the actual store build after upload.
现有开发 Mac 还已通过安装后的桥接完成测试作品创建、绘图、重命名、撤销/重做、
保存、PNG 下载及原生关闭检查；像素对比确认测试前作品已恢复。这些记录仅
对应一台 Mac 上的开发构建，不代表 App Store/TestFlight、干净机器安装、真实厂商
客户端、iOS 真机或局域网已通过验收。原生回归证据需对应审核源码版本，上传后的
实际发行包仍需独立验收。

## Distribution checks / 分发检查

The preview source is public at [SoBison/Aquarell-mcp](https://github.com/SoBison/Aquarell-mcp).
The [first hosted workflow](https://github.com/SoBison/Aquarell-mcp/actions/runs/40106901376)
passed for commit `6926a2656a0ab3e68208f54abe44882ebace869a`.
预览源码仓库已公开，首次托管工作流已通过；这不代表下列商店和真机验收已经完成。

The installer suite uses only temporary HOME directories, synthetic app metadata,
and temporary config files. It verifies private permissions, exact config
backups, preservation of unrelated servers, explicit edit opt-in, conflict and
symlink rejection, safe upgrades/uninstall, five setup languages, allowlist
packaging, hashes, and installation from the exact extracted archive. Synthetic
bundles are never launched or treated as a passing app-signature/pairing test.
安装测试只使用临时 HOME、合成 App 元数据和测试配置，覆盖权限、备份、其他服务
保留、显式编辑授权、冲突和链接拒绝、升级卸载、五语言、打包清单、哈希及实际解压
安装流程。合成应用包不会被启动，也不构成真实签名与配对验证。

Read-only bridge tests stub network delivery and assert write calls never reach
an already-editable app connection, including forged client hints, unknown
methods, duplicate/malformed definitions and discovery failures. They validate
the bridge policy independently of the app's switch; they do not establish
real-client UI behavior or a third-party client's security properties.
只读桥接测试隔离网络传输，验证即使复用可编辑连接，伪造提示、未知方法、重复/异常
定义及工具发现失败也不能提交写入；这不代表真实客户端 UI 或其安全性已完成验收。

Remaining gates are explicit in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
Unverified items must remain visible in release notes until checked on the actual
shipping build. 剩余项目详见发布清单；实际发行包完成验收前应保留未验证说明。
