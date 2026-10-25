# Aquarell-mcp

[English](README.md)

让 MCP 客户端控制 Apple Silicon Mac 上支持 MCP 的 Aquarell iPad App。
绘画工具由 App 提供，桥接将标准 MCP JSON-RPC 从标准输入输出转发至 App
带认证的本地 HTTP 服务，无需第三方 Python 依赖。

当前为预览交付版本，尚未用 App Store/TestFlight 发行包完成验收。App 和桥接需
分别发布；此压缩包不包含 App、开发证书、描述文件或 App Store 凭据。公开发布前
需由仓库所有者核对许可和版权声明。压缩包原样保留仓库已有的 MPL 2.0 `LICENSE`，
本次未选择其他许可证。

GitHub 仓库名称为 **Aquarell-mcp**，对外显示名称为 **Aquarell MCP**。为兼容已有
App 和客户端配置，保留 `pastel_*` 工具标识、`pastel_mcp.py` 与
`pastel-mcp-bridge.py` 文件名、`pastel` 客户端配置键、`com.bzy.pastel` 应用标识符，
以及 `PastelMCP` 安装和配对目录。App 也可能显示为旧名称 Pastel。仓库更名不会迁移
已有配置或本地数据。

## 环境要求

- 能运行发行版 iPad App 的 Apple Silicon Mac。
- 从 App Store 或 TestFlight 安装支持 MCP 的 Aquarell。旧版 App 不支持。
  App 内 MCP 仅在 iOS 16 及以上可用，App 本身可继续兼容旧系统。
- Python 3.9 或以上；若 `python3 --version` 不可用，需单独安装 Python。
- 支持本地 stdio MCP 的客户端。安装桥接不需要 Xcode 或 Apple 开发者账号。

## 安装

下载并解压发布包，在对应目录打开终端：

```sh
python3 pastel_mcp.py install
python3 pastel_mcp.py doctor
```

安装器按应用标识符查找 App，也支持显示名称为 Aquarell 的安装。若未找到，可在
`install`、`init-config`、`pair`、`doctor` 后添加
`--app "/Applications/Aquarell.app"`。安装器检查应用包元数据；配对时，传输层还会
独立验证 Apple 签名及运行进程。它不会修改 Gatekeeper，也不会安装开发签名包。

桥接安装于当前用户的 `~/Library/Application Support/PastelMCP/bridge/`，不需要
管理员密码。升级保留之前安装的备份；若有被修改或额外添加的文件，会保留并停止，
请移开这些文件后再安装或卸载。客户端配置使用 Python 的绝对路径，配置后请保留
该解释器。

## 配置客户端

输出通用 JSON `mcpServers` 配置：

```sh
python3 pastel_mcp.py init-config
```

要合并现有 JSON 配置，明确提供客户端配置文件路径：

```sh
python3 pastel_mcp.py init-config --output "/path/to/client-config.json"
```

其他设置和服务会被保留。修改现有文件前，安装器在同目录保存原文件的完整备份，
权限为 `0600`。若已有不同的 `pastel` 项，会停止；仅在确实需要备份并替换该项时
使用 `--replace`。无效 JSON、符号链接、非当前用户所有的文件及超过 1 MiB 的文件
会被拒绝。安装器不会猜测或自动修改客户端特有的配置路径。

Codex 可生成 TOML 配置片段：

```sh
python3 pastel_mcp.py init-config --format codex
```

将其加入现有 Codex 配置；已有 `mcp_servers.pastel` 时替换对应节。安装器不会自动
合并或覆盖 TOML。配置后需在客户端启用或重新加载服务，两种格式均不包含令牌。
字段与 [Codex 官方 MCP 配置文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)一致。

生成的配置默认使用只读桥接，即使 App 已允许编辑也会限制当前连接。桥接查询通过
认证的 App 当前工具定义，拦截未明确标为只读的工具及未知方法。如需允许编辑请求，
在生成配置时添加：

```sh
python3 pastel_mcp.py init-config --allow-edits
```

App 的 AI 控制设置也会生效，该参数不能绕过 App 的编辑开关。只读限制作用于当前
桥接连接，不会撤销其他客户端的权限，也不会修改 App 设置。

## 配对与诊断

本机首次 MCP 连接可自动打开已安装的 App 并配对一次。这份首次使用记录由当前
macOS 用户的桥接共用，客户端重启、桥接升级或卸载后仍然保留；已有配对文件也视为使用过。
正常退出 App 后，工具发现、断线重连或重启客户端都不会把它重新打开。
升级桥接后，需在客户端重载该服务，让新代码生效。

未安装 Aquarell 时，请从 App Store 安装并打开，再重新连接。使用非默认安装位置时，
添加 `--app` 指定路径。若连首次自动打开也不需要，可用
`init-config --no-launch` 生成配置。
已有配置的 `--no-launch` 会继续生效；移除此参数不会清除首次使用记录。

退出 App 后，需要恢复 MCP 时，手动运行启动与配对：

```sh
python3 pastel_mcp.py pair
```

需要编辑时，用 `pair --allow-edits` 向 App 请求编辑权限，并用
`init-config --allow-edits` 生成允许编辑的客户端配置；这两个开关都不能绕过 App
的 AI 控制设置。使用非默认安装位置时，为 `pair` 添加 `--app` 参数。

首次连接和手动 `pair` 均可传入临时回环回调；`pair` 配对后即退出，不处理客户端请求。
只有签名一致、进程验证
通过的 App 能发布连接信息。凭据仅保存在当前用户的私有本地配对文件中，不进入
客户端配置或命令行参数。使用 MCP 时保持 App 窗口打开；iOS 在进入后台时可能停止
服务，普通 Mac 窗口焦点切换受支持。

若 App 在首次配对前已打开，请先保存作品、正常退出 App，再运行 `pair`。
主动退出 App 后，需要恢复 MCP 时也请显式运行 `pair`。桥接不会强制退出 App。
配对后，运行中的桥接会订阅服务重启和令牌变更。如果凭据
撤销时所有桥接都已关闭，可能仍需正常退出 App 后重新配对。失败或结果不确定的
编辑不会被自动重试；请先查看作品并读取最新状态。

App 已运行并完成配对后：

```sh
python3 pastel_mcp.py doctor --connect
```

`doctor` 仅输出固定检查名、布尔值和工具数量。未加 `--connect` 时只检查文件和
App 元数据；加上后执行 MCP 初始化和工具发现，不启动 App、不编辑作品，但连接
订阅可能更新私有配对文件。退出码 `0` 表示所选检查通过，`1` 表示未通过。仅文件
检查通过不代表 App 已连通，也不代表所有客户端兼容。

命令前添加 `--lang zh-Hans` 可指定中文，也支持 `en`、`de`、`fr`、`ja`；默认跟随
环境语言。底层协议传输的固定错误提示目前仍使用英文。

## 卸载

先在客户端禁用服务，然后运行：

```sh
python3 pastel_mcp.py uninstall
```

如需同时移除指定 JSON 客户端配置内属于本安装的服务项，添加
`--config "/path/to/client-config.json"`，会保留完整私有备份，不会删除属于其他
安装的服务项。Codex TOML 节需手动删除。共用配对文件、首次使用记录、历史安装备份、App 和所有
作品都保留，其他客户端可能还依赖这些共用配对文件。

## 源码与验证

App 仓库中唯一维护的传输源码为 `Tools/pastel-mcp-bridge.py`。从源码安装会直接
读取它，`build-release.py` 会将它复制进发布包；不要在本目录维护第二份传输实现。

```sh
python3 -m unittest discover -s mcp/tests -v
python3 Tests/test-mcp-bridge.py
python3 mcp/build-release.py --output output/mcp-release
```

如需准备**独立的 GitHub 源码仓库**，在 App 仓库中导出一个新目录，不会自动发布：

```sh
python3 mcp/build-release.py --export-source output/Aquarell-mcp
```

仅复制明确列出的桥接包源码、测试、构建脚本、已有许可证，以及导出当时的唯一传输
源码。目标目录必须尚不存在，不复制 `.git`、App 源码、用户配置或凭据。导出目录
可独立于 App 仓库运行：

```sh
python3 -m unittest discover -s tests -v
python3 build-release.py --output dist
```

其 GitHub 工作流在 Linux 上测试 Python 3.9，并在 Linux/macOS 上测试当前 Python，
随后构建相同的 11 文件用户 ZIP。使用官方 [checkout](https://github.com/actions/checkout)
和 [setup-python](https://github.com/actions/setup-python) Actions，仓库权限只读，
没有发布步骤。预览源码已发布至 [SoBison/Aquarell-mcp](https://github.com/SoBison/Aquarell-mcp)，
提交 `6926a2656a0ab3e68208f54abe44882ebace869a` 的
[首次托管 CI](https://github.com/SoBison/Aquarell-mcp/actions/runs/40106901376) 已通过；
后续版本状态见 [Actions](https://github.com/SoBison/Aquarell-mcp/actions)。CI 使用合成 App 元数据，不能
代替真实签名 App 或商店发行包验收。不要独立修改导出的桥接与 App 中的传输源码，
每次发布应从审核后的唯一源码重新导出。

每个发布包包含各文件的 SHA-256 清单及单独的压缩包校验值。校验值只能检查意外
损坏，不能证明发布者可信；运行前请确认来源。打包仅使用明确列出的源码文件，绝不
复制用户已安装的配对目录。详见[支持与验收状态](SUPPORT.md)、[安全说明](SECURITY.md)
及[发布清单](RELEASE_CHECKLIST.md)。
