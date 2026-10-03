# 本次发布的验证范围

版本：2026.10.03-beta.16。源码整理日期：2026-10-03。

| 检查 | 状态 | 依据与边界 |
| --- | --- | --- |
| 公开源码 Python 回归 | PASS | 493 项：492 通过，1 项 Windows API 跳过 |
| UI Node 回归 | PASS | 27 组 `test_ui_*.cjs` |
| HTML 内联脚本编译 | PASS | 4 个脚本块 |
| 合成项目浏览器走查 | PASS | 实际查看 Today、项目状态、部分完成/UNVERIFIED 结果及来源入口；控制台无警告/错误 |
| 运行源码与桌面 beta.16 基线 | PASS | 26 个 Python/JS/HTML/Swift 文件摘要相同；公开文档、导出脚本和演示另作整理 |
| Mac 离线安装自检 | PASS | 原桌面本版回执绑定包内文件摘要；零模型调用、不读用户来源 |
| Mac / Windows ZIP 完整性与私有状态排除 | PASS | 原回执与本次 ZIP CRC、账号/数据库/令牌文件名检查；校验和随 Release 提供 |
| Windows x64 文件格式 | PASS | 原打包回执；不等于原生运行 |
| 本版 macOS 原生 GUI | NOT_RUN_FOR_THIS_RELEASE | 源码浏览器走查不替代原生宿主验收 |
| Windows 真机安装和运行 | NOT_RUN | Mac 主机上的检查与跳过测试不能替代 Windows |
| 本次真实账号 / 模型全链路 | NOT_RUN | 本次未调用模型；不将合成演示当真实 AI 输出 |
| 跨机器、多日稳定性 | NOT_RUN | 没有本次对应验证 |
| 真人接续体验与效率收益 | NOT_RUN | 目前没有公开对照数据 |
| 独立安全审计 | NOT_RUN | 路径门禁和软件回归不构成完整审计 |

源码回归摘要见 [public-source-regression.json](receipts/public-source-regression.json)。原包回执见 [package-acceptance.json](receipts/desktop-beta16/package-acceptance.json) 和 [macos-offline-self-check.json](receipts/desktop-beta16/macos-offline-self-check.json)。原包回执中的源码摘要只描述原桌面包，不能用于证明新公开文档的字节相同。

回归中出现 SQLite 连接未关闭的 `ResourceWarning`；当前测试无失败，生命周期清理仍值得完善。该警告没有被升级为数据损坏结论，也没有从发布摘要隐藏。

## 重现方式

使用 Python 3.13 和 Node 22，运行 `python3 scripts/verify_release.py`。测试资料与目录隔离，真实模型调用为零。合成界面使用 `python3 scripts/start_demo.py`，所有示例记录明确标为人工合成。

桌面 ZIP 已做公开分发隐私清理：替换旧文档、移除 Python 缓存、重生成 manifest 和 Mac ad-hoc 签名；不再沿用原 ZIP 字节。清理后的 Mac 离线自检 PASS，绑定新文件摘要；新 ZIP CRC 与隐私路径检查 PASS。原桌面回执只适用于原包。当前步骤以仓库与 Release 的双语指南为准。源码、包完整性、原生安装、模型回包、用户收益和科学结论分别判断。

CI 状态以 GitHub 实际运行记录为准。工作流文件存在不表示已通过。


## 公开附件隐私修正 / Public asset privacy correction

首次上传的旧安装包验收文档包含本机目录路径；发现后已撤下旧附件，替换公开文档、移除缓存并重新打包。未发现账号文件、令牌、个人数据库或真实项目资料。此前公开的目录路径不能保证从已下载副本中撤回。

The initial desktop assets contained local directory paths in historical acceptance documentation. Those assets were withdrawn. Public documents replaced the historical guides, Python caches were removed, manifests were regenerated and the Mac app was signed again. The sanitized Mac offline self-check passed against its new file digest. Both replacement archives passed CRC and targeted privacy checks. Old receipts apply only to the original packages. Previously downloaded copies cannot be recalled.

See [new offline receipt](receipts/public-package-self-check.json) and [privacy-check scope](receipts/publication-privacy-check.json). Automated pattern scans and screenshot inspection are bounded checks, not an independent security audit.

## 云端回归 / Cloud regression

[GitHub run](https://github.com/lingyi-liusd/yanxu/actions/runs/37124024386)：Linux PASS；macOS 在 15 分钟限额内未完成，显示取消且日志已有失败标记，因此不能记为 PASS。原本机 Mac 回归和公开重打包离线自检分别有独立回执；不替代 macOS 云端检查。

Linux CI passed. The macOS cloud job timed out at its 15-minute limit, with failure markers in its log; it is not a passing check. Local Mac regression and the sanitized package's offline self-check have separate receipts. Diagnosing the macOS cloud test environment remains open.
