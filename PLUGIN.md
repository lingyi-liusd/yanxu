# 研序 Agent Plugin Contract

## 产品定位

研序 Research Desk 是 AI-native Project Operating System，面向复杂、长期、由 Agent 参与的项目。Research Desk 是品牌，不限定项目必须是学术科研。核心是持久 Project State，而不是任务数据库或聊天窗口。

- **Agent**：读取 Project Context、推进有边界的 Action、登记 Artifact / Result / Evidence 与重要 Event。
- **Human**：理解当前状态、处理关键 Decision、审阅 Agent 变更、必要时撤销/回滚。
- **Web UI**：用 Today 六问与项目状态解释持续工作，不要求人维护任务数据库。
- **MCP**：Agent 的主要读写接口。
- **SQLite**：本地可信状态源，不依赖云端项目平台。

核心闭环：

```
Agent context → plan → bounded Action → Artifact / Result
       ↓                              ↓
  project.get_context             Event / audit
       ↓                    ↓
Human view ← SSE refresh ← state
       ↓
decision / undo / rollback
```
## 旧全局接口默认权限模型（兼容）

### 可自动执行

以下操作在读取最新 rev、dry-run 通过后，可由 Agent 自动执行：

- 创建/更新项目
- 创建/更新任务
- 调整任务状态、优先级、日期、父子关系、依赖
- 创建/更新决策节点
- 删除普通任务或决策节点
- 多项常规批量更新

所有真实 Agent 写入必须记录：

- `actor = "agent"`
- 可读的 `summary`
- 最新 `ifRev`

### 必须显式确认

- 删除整个项目
- 历史 rollback
- 整状态恢复
- 未来可能引入的外部文件删除、远程同步、发布动作

项目删除只能通过 `research_project_delete(confirm=true)`；不得借 `research_batch` 绕过。
## Agent 接管顺序

1. 项目级连接先调用 `project.get_context` 完成握手；旧全局连接可用 `research_agent_brief`。
2. 核对目标、当前状态、重点、近期正负结果、约束、阻塞、待人决定和工作区边界。
3. 新执行优先 `project.claim_action`；报告进度，登记成果引用和结果来源版本。旧 Task 更新仍用带 `ifRev` 的兼容工具。
4. 改目标、范围、关键约束或撤销依据时提出人类决定，不把 Proposal 当授权。
5. 完成后读取 Project Context 和 Event 验证状态变化，保留负结果和未核验等级。

## 人类观察面的设计原则

Human UI 默认回答六个问题：

1. 现在在哪里？
2. 正在发生什么？
3. 为什么？
4. 发生了什么变化？
5. 下一步是什么？
6. 哪些事项必须由人做决定？

低频管理工具、统计和备份操作不应占据首屏。

## 不做的事情

- 不把聊天框塞进 UI 作为“AI 功能”。
- 不要求人复制粘贴状态给 Agent。
- 不让 Agent 绕过服务端校验直接改 SQLite。
- 不把任务完成自动解释成科学结论成立。
- 不以“AI 自动化”名义静默执行高风险破坏性动作。
