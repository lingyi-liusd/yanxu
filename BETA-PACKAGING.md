# 桌面测试包与构建

当前基线：2026.10.03-beta.16。Apple Silicon macOS 与 Windows x64 ZIP 已提供；平台验证范围见 docs/VALIDATION.md。

测试版独立使用 ResearchDeskBeta 数据目录和端口 18765。Python、Node、Codex CLI 运行库随包提供并保留各自许可；首次为空项目，AI 和来源默认关闭。Mac 使用 AppKit/WKWebView、ad-hoc 签名，未公证；Windows 使用当前用户目录安装和 Edge 应用窗口。

构建器只收集明确源文件清单，排除数据库、账号、令牌、来源缓存和授权。包清单绑定 SHA-256；校验和不等于代码签名或安全审计。Windows Python 对比官方发布的消息摘要，未完成完整 Sigstore 签名 / 证书链验证。

```sh
python3 packaging/build_beta.py --output /absolute/new-release-dir --cache /absolute/cache-dir
```

构建 macOS 宿主需要 macOS arm64 与 Swift 系统工具。输出目录不覆盖已有版本。`finalize_beta.py` 同步本版本代码、刷新清单和归档；使用时须以最终字节重新核对回执。

`self_check.py` 使用合成资料、空账号和独立目录，检查运行库、隔离参数、握手、鉴权、文件范围、单实例与 MCP；模型调用为零。安装自检、源码回归、真实登录、原生 GUI 和各平台运行分别判断。
