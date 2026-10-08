> 2026-10-08 当前生态源码请见根 README.md 与 docs/receipts/source-preview-20261008.json。以下桌面 beta.16 说明属于历史版本。

# 第一次使用

先用一个非关键项目体验普通功能，再决定是否启用 AI。

## 桌面下载

从仓库 Releases 下载对应平台 ZIP，完整解压。Mac 打开「研序测试版.app」；Windows 双击「一键安装.cmd」，或用「打开研序.cmd」免安装体验。Windows 关闭浏览器窗口不等于停止后台，使用「退出研序.cmd」。Mac 通过退出或 ⌘Q 停止所属服务。

首次使用为空项目。测试版数据保存在本机独立的 ResearchDeskBeta 目录；已有测试版会继续使用其本地记录。安装包不包含维护者的项目或账号。

本版 Windows 原生执行未测，Mac 未公证。系统阻止时请提供已遮挡私人内容的原始提示，不要关闭安全防护。

## 十分钟路线

1. 新建项目，写一个具体目标，例如“比较三种方案，形成一页说明”。
2. 添加当前任务，只填写必要信息；日期和依赖可以之后补充。
3. 查看 Today 的当前记录和下一步，打开对应原记录。
4. 在「成果与文件 → 项目笔记」保存正文，退出重开查看保存结果。
5. 查看排期、行动、结果与依据及时间线。没有记录时应该为空。
6. 切换中文 / English。原项目正文不会自动翻译，部分高级文案仍有中文。

## 可选 AI

在「AI 设置 · Agents」启用常驻连接，未登录时通过官方页面登录自己的 Codex 账号；回到研序等待账号读回并选择接口提供的模型。连接成功不代表已授权项目总结或文件读取。

在当前项目单独确认总结范围与频率。有变化时按设定节奏总结；无变化不重复调用。大项目按固定快照分批并汇总，180 KB 单次准备输入限制仍存在。失败不自动重试，回写未确认时先对账。

如需本地资料，先绑定工作区，再分别确认本地读取、PDF/DOCX 文字提取和发送正文。扫描件、图片、公式和图表可能留下缺口；文字提取不是完整理解。

外部执行 Agent 使用页面生成的项目级 MCP 配置；保留原目标、契约、预算和来源版本。令牌只保存在自己设备，不发到 issue 或截图里。

## 备份与反馈

使用「数据与外观 → 导出备份」。项目备份不包括所有原文件、账号或 AI 授权，原始文件需另保留。升级前退出当前测试版并保留旧包。

反馈请提供版本、系统与芯片、步骤、期待结果、实际结果，以及脱敏截图。不要上传数据库、账号缓存、连接令牌、完整对话或个人研究资料。

---

# English · Getting started

Start with a non-critical project and basic features before enabling AI.

## Download and launch

Download the matching ZIP from [Releases](https://github.com/lingyi-liusd/yanxu/releases/tag/v2026.10.03-beta.16) and fully extract it. On Mac, open “研序测试版.app”. On Windows, run “一键安装.cmd” (install) or “打开研序.cmd” (launch without installation). Closing the Windows browser does not stop the background service; use “退出研序.cmd” (quit). On Mac, Quit or ⌘Q stops the service owned by that app.

The first run has no projects. Beta data lives in a separate local ResearchDeskBeta directory; existing beta records are reused. Packages do not include the maintainer's projects or accounts. Native Windows execution has not been tested, and the Mac app is not notarized. If your OS blocks launch, report its exact message with private details redacted.

## A ten-minute walkthrough

1. Create a project with a specific goal, such as “Compare three options and write a one-page explanation.”
2. Add a current task; dates and dependencies can be added later.
3. Inspect Today and follow its next-step link to the original record.
4. Save a project note under Deliverables and files; restart to check persistence.
5. Explore schedule, actions, results/evidence and timeline. Empty records should remain empty.
6. Switch between Chinese and English. Project content is not automatically translated; some advanced UI text remains Chinese.

For a no-login source demo, run `python3 scripts/start_demo.py` and open the printed localhost address. It uses a temporary profile and synthetic records, makes no model calls and does not modify your normal workspace. Stop it with Ctrl-C.

## Optional AI

Enable the persistent connection in AI Settings → Agents, sign in to your own Codex account through the official login page, wait for account readback and select an available model. A successful connection does not authorize project summaries or file reading.

Confirm summary scope and frequency separately for each project. Summaries follow the configured rhythm when records change; unchanged projects do not repeatedly invoke the model. Large projects use a fixed snapshot with batches and a final summary; the 180 KB single-input preparation limit still applies. Failures are not automatically retried; reconcile uncertain writes first.

Bind a workspace before separately authorizing local reading, PDF/DOCX text extraction and sending source text. Scans, images, equations and charts may leave extraction gaps. Text extraction does not prove complete understanding. External agents use the generated project-scoped MCP configuration and preserve goals, contracts, budgets and source versions. Keep tokens on your own device.

## Backup and feedback

Use Data and appearance → Export backup. Project backups do not include all original files, accounts or AI permissions; keep original files separately. Quit the current beta before upgrading and retain the old package.

Report the version, OS/chip, steps, expected behavior, actual behavior and redacted screenshots. Do not upload databases, account caches, connection tokens, complete conversations or personal research material.
