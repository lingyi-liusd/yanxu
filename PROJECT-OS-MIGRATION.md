# Project OS 语义升级与兼容边界

2026-09-30。研序 Research Desk 的品牌名称不变；系统级定位为 AI-native Project Operating System。核心关系是 Agent 推进、研序保存并解释项目状态、人决定关键方向。适用范围是复杂、长期、有状态且 Agent 参与的项目，而非通用待办或聊天工具。

## 全项目术语扫描的分类

| 类别 | 例子 | 本轮处理 |
| --- | --- | --- |
| A 系统级语言 | “科研项目”“今日研究”“研究时间线”、固定的论文/实验/证明栏目、Research Brief 的示例论点 | 改为 Project、Today、Actions、Results & Evidence、Artifacts & Files、Timeline 等通用语言；旧总览执行路径改为真实项目记录渲染。 |
| B 具体项目内容 | 原项目名称、研究目标、任务笔记、实验/论文/证明文字、文件路径、历史快照 | 不做批量替换或重写；科研项目仍展示其原始领域内容。 |
| C 品牌 | “研序 Research Desk”、Logo | 保留。品牌中的 Research 不等于学术项目类型。 |
| D 兼容接口及内部标识 | `research.*` MCP、`/api/research/*`、`/api/research-focus`、`RESEARCH_FOCUS_*` 环境变量、`task_id`、旧 PASS/FAIL | 保留别名和原始值；在其上增加 `project.*`、`/api/project/*`、`entity_type/entity_id` 与标准化结果。 |

扫描范围包括 `index.html`、`server.py`、`agent_gateway.py`、`mcp-server.js`、`README.md`、`PLUGIN.md` 与 `AGENTS.md`。旧学术启发式仍可用于识别原科研笔记或文件名，但不得作为所有项目的页面模板或已核验事实。

## 数据与 Agent 契约

- `Project Description` 在现有 `projects[]` 中增量保存 `description`、`goal`、`success_definition`、`current_state`、`constraints[]`、`workspace`、`type`；老项目缺字段时按空值读取，不重写原记录。Description 是项目身份，`current_state` 是人保存的状态描述；Today 的动态状态还须结合 Action、Event、Result 与 Decision，不能把 Description 当实时进度。
- `Project Context` 返回 project、goal、current_state、current_focus、actions、blockers、questions、recent_events、artifacts、evidence、results、decisions、constraints、agents、workspace 和 permissions；原接管字段继续提供兼容。
- Action 是 Agent 的主要执行单位，可不绑定 Task。Task 保留给人的规划工作区和旧客户端。`project.claim_action` 仍受预算、停止条件及 Gateway 权限约束。
- Artifact 是独立的 append-only 登记表，含类型、标题、Action、引用、来源版本及 Agent；仅记录引用，不复制文件。旧文件索引继续单列展示，不冒充可验证 Artifact。
- Result 保留原始 `outcome`，同时映射 `normalized_status ∈ {success,failure,partial,inconclusive,unknown}`；写入自动追加 Evidence，并保留 `UNVERIFIED`。负结果不覆盖。交付、结果与证据等级分开表达。
- Decision Request 只能由人批准或拒绝。阻塞性待决定事项可成为非 Task 的 Current Focus；决定完成后重判重点。目标、约束、方向关闭、证据替代与重大破坏性动作不因 Agent 提议而获授权。
- 新 Agent 工具统一 `project.*`；旧工具和路由保留。项目级 token 的 READ/PROPOSE/EXECUTE 隔离只适用于新 Gateway；旧全局 token 不能被解释为同等权限隔离。

## 验收与边界

隔离数据目录可使用 `tests/demo_project_os.py` 构造科研、软件和产品设计三个项目，再在同一界面核对 Today、Project、Actions、Results & Evidence、Artifacts & Files、Timeline、旧任务/笔记/文件工作区。脚本拒绝默认用户数据目录。回归测试见 `python3 -m unittest discover -s tests -v`。

本轮不声称 Agent 的所有外部执行已自动化，也不把文件索引当文件内容、把 Agent 报告当独立验证、把任务完成当科学/发布结论。旧学术启发式和兼容命名仍在源码与历史说明中；新项目不应通过这些旧展示路径获得虚构的学术内容。证据替代审批、Agent 崩溃回收、常驻服务管理与完整可编辑图谱仍是后续工作。
