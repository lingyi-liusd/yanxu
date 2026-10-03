# 安全边界与报告

研序是本机单人测试软件。默认仅监听回环地址；不要把端口、API 令牌或本机 Codex 服务暴露到公网。

- 工作区绑定、读取、文档文字提取和发送正文分别确认；目录变化使旧授权失效。
- 新项目级令牌与旧全局兼容接口的隔离边界不同，不给不可信代理提供全局令牌。
- 路径和解析门禁不是操作系统沙箱；没有跨 Agent 文件写入锁。
- 模型摘要是未核验建议，不是科学结论或新的执行授权。
- 暂停、失败和中断不自动重放旧工作；电脑睡眠或退出影响本地可用性。

目前尚未完成独立安全审计、Windows 真机验收、正式签名 / 公证或长期稳定性验收。

## 报告问题

如仓库提供 GitHub 私密漏洞报告入口，请优先使用。否则可通过普通 issue 请求私密联系，但不要在 issue 中附漏洞利用细节、令牌、登录文件、真实对话、数据库或个人文件。维护者联系方式未配置前，不上传敏感附件。

公开普通错误报告只需版本、系统、最小复现和脱敏截图。涉及数据丢失、越权读取或重复执行时，先暂停该项目的 AI / 来源功能并保留本地现场。

---

# English · Security boundaries and reporting

Yanxu is a local single-user beta and listens on loopback by default. Keep its port, API tokens and local Codex service off the public Internet.

Workspace binding, reading, extraction and sending text require separate consent; directory changes invalidate previous permissions. Project-scoped tokens and legacy global tools have different isolation boundaries: do not give untrusted agents global tokens. Path/extraction checks are application controls, not an OS sandbox; there are no cross-agent file write locks. Model summaries remain unverified suggestions, not scientific conclusions or new authorization. Paused, failed or interrupted work is not automatically replayed; sleep and app shutdown affect availability.

Independent security auditing, native Windows acceptance, formal signing/notarization and long-term stability acceptance remain incomplete.

Use GitHub's private vulnerability reporting when available. Otherwise request a private contact via an issue without publishing exploit details, tokens, login files, full conversations, databases or personal files. Ordinary bug reports need a version, platform, minimal reproduction and redacted screenshots. For suspected data loss, unauthorized reading or duplicate execution, pause the affected project's AI/source features and preserve local evidence.
