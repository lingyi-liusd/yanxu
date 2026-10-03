# 贡献说明

欢迎问题报告、文案修正和有明确场景的小范围改进。先说明用户问题、重现步骤及预期行为，再讨论实现。

## 本地开发

建议 Python 3.13 和 Node 22。普通功能无需全局安装依赖，PDF 解析使用 vendor 内固定 wheel。

```sh
python3 scripts/start_demo.py
python3 scripts/verify_release.py
```

演示和回归使用合成记录与隔离目录。不要使用维护者或用户的数据库、账号、来源资料，也不要在测试中调用真实模型。

## 改动要求

- 保留三栏、现有 Logo 与原记录入口；新功能说明具体用户收益。
- 版本冲突、授权撤回、来源变更和中断须有可解释结果，失败不静默重试。
- 分开记录交付、报告结果与核验等级，保留失败和未知。
- Agent 操作先读上下文，写入预检查、版本校验并读回；不得覆盖人工笔记。
- 源码发布只选明确文件，排除运行数据、凭据、日志、备份和缓存。
- PR 说明问题、最终行为、相关测试与尚未覆盖的边界。

自动回归通过不代表原生安装、真实登录、模型质量、长期稳定性或用户收益通过。CI 以实际运行记录为准。

贡献的项目原创源码沿用 MIT；第三方内容须保留原许可和来源。

---

# English · Contributing

Bug reports, wording fixes and small improvements with a concrete user scenario are welcome. Explain the problem, reproduction steps and expected behavior before discussing implementation.

Use Python 3.13 and Node 22. Run `python3 scripts/start_demo.py` for an isolated example and `python3 scripts/verify_release.py` for regression checks. Ordinary features need no globally installed dependencies; PDF parsing uses the pinned vendor wheel. Tests use synthetic data and separate directories. Do not use real accounts, databases, source materials or model calls.

Preserve the three-pane layout, existing logo and access to original records. Make revision conflicts, revoked consent, changed sources and interruptions explainable; do not silently retry failures. Keep delivery, reported results and verification separate, retaining failures and unknowns. Agents read context before acting, preview/check revisions/read back writes, and preserve human notes. Public exports use explicit file lists and exclude runtime data, credentials, logs, backups and caches.

Describe the problem, final behavior, relevant tests and uncovered boundaries in a PR. Passing regression does not prove native installation, login, model quality, long-term stability or user benefits. CI status follows actual runs. Original contributions use MIT; third-party content retains its source and license.
