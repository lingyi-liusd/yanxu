# 续芽 · Agent 操作约定（每次会话必读）

生态开发接续入口：`docs/ecosystem/INDEX.md` → `CURRENT.md` → `HANDOFF.md`。讨论室、雷达与生态接口的有效状态以这些记录和实际测试为准；不得继承旧发布或旧科学验收的通过结论。

本机 AI 原生项目操作系统。HTTP 服务 `http://127.0.0.1:8765`，零依赖，单人使用。当前界面品牌名是「续芽」，历史研序 / Yanxu 名称、ResearchDesk 数据目录与协议标识保留兼容，项目类型不限于科研。Agent 推进项目并登记可追溯成果；Web UI 帮人理解、确认关键决策和必要时撤销。长期项目交接仍须遵守当前目标、有效状态、来源版本和证据等级边界。

## 新 Agent Gateway（优先于下方旧接口配方）

连接安全：推荐官方 `codex mcp add` 注册方式；研序不写入全局config.toml，不改变features、模型或登录设置。手动TOML仅为高级选项，不能重复追加同名段，也不能覆盖整个文件；先用`codex mcp list`检查配置能否读取。生成片段将连接设为非必需，不默认自动批准工具。已有配置不自动迁移或改写。

常驻管理连接：设置 → Agents 的启用/暂停控制本地Codex App Server，绿点要求实际握手、登录及所选模型在当前接口列表内，允许空闲；通道正常而模型不可用显示黄点“需选择模型”。模型列表来自model/list，用户明确选择只保存在研序，对项目管理调用生效，不改全局配置、资料授权、原契约或用量，不自动选替代模型/重放失败。30秒心跳无模型调用；断线重连只修通道。沿用项目管理/资料发送授权和总结节奏，按项目及授权版本保存有界会话；运行中断先核对。暂停后不降级到其他执行器。电脑和研序须运行，不是云端常在线；外部研究Agent仍走下方独立MCP契约。详见AGENT-MANAGER.md。

人类可读输出：显示层保留原始记录，常见状态用中文解释，数值、负结果与条件不能被润色成成功。后台模型总结先说发生什么、还缺什么、要人决定什么；专业含义不明确时保留术语，不猜解释。

项目状态变更解释：report_activity、任务更新等已有接口的 reason 应写清“依据哪条记录/对象/版本，为什么改变当前判断，还有什么未确认”；summary 先用一句人话说发生了什么。进展汇报不等于状态已改变：状态值未变时明确只是补充进展。没有前后值不编造旧状态，没有明确关联不把同时发生的事件说成因果；why_now 只解释行动发起原因，不代替本次变更理由。科学结论、核验状态和执行授权分别保留。

在设置 → Agents 为当前项目生成项目级 MCP 配置。新连接以 `RESEARCH_DESK_AGENT_TOKEN` 调用 `mcp-server.js`，首次必须调用 `project.get_context` 完成真实握手，并核对 Project Description、目标、动态状态、原始与归一化结果、约束、阻塞、待人决策、成果来源版本和工作区边界。旧 `research.*`、旧全局 token 与以下 `/api/action` 配方只供兼容旧客户端，不提供项目级权限隔离；不得把旧接口的 `confirm=true` 当成新的范围或方向授权。

接手入口：Today只显示当前记录、一条必要提醒和一个下一步按钮；Today / 项目页面的“依据与交接”按需展开原记录、限制与待处理、Agent接续简报，不调用模型。`project.get_context.management.resume_brief` 仍提供同源三要点与完整handoff；复制的简报可能已过期，执行前必须重新读取上下文、比较project_id/source_hash并核对原目标、Action版本、停止条件、进度报告已耗次数和每日模型预算。活跃Action属于原Agent，不自动接管；任务结束、复制文本和AI摘要都不构成新授权。保留失败、未知、未核验和历史快照移出的负记录，不能因换Agent重置预算或重跑实验。

新认领优先传 `context_hash=management.resume_brief.source_hash`，服务事务内拒绝已变快照；兼容客户端未传时不具备该门禁。相同项目中目标（少于400字）、产出和依赖完全一致的未结束行动禁止重复认领，忽略空白和依赖顺序。不是语义或历史实验去重；不同对象应明确写入目标/产出，不通过换几个字冒充新授权。接续检查只提示登记缺口与已观察来源，不代表全项目已安全核验。内测标准见 BETA-ACCEPTANCE.md。

资料整理：`GET /api/project/manager.source_intake` 是已授权本地文件的纯元数据草稿，不调用模型、不生成科学事实。成果与文件 → 整理新资料，默认不勾选；人确认后经dry、ifRev和draft_hash核对，事务内锁住来源授权并再次核对文件内容版本，仅新增UNVERIFIED资料索引。暂停、撤权、来源变化或重复确认拒绝，不静默重试，不改旧结果/依据。Agent令牌不能使用人类确认接口。对话不会自动变成任务或科学证据。Today主入口携带快照hash，刷新发现新进展时要求查看新入口，不沿用旧按钮。

Agent 只认领一个有理由、产物、预算与停止条件的 Action；`project.claim_action` 可不绑定旧 Task，之后 `project.report_activity(start/progress)` → `project.add_artifact`（有成果时）→ `project.record_result`。Result 必须绑定来源对象和版本，写入时自动追加 Evidence、完成 Action、触发 Planner 重判；Artifact 只登记引用，不复制原文件。旧 `research.add_evidence` 只用于补充依据。任务创建/更新、依据追加必须绑定明确 Action，旧任务写入携带最新 `ifRev`。Result 可用 success/failure/partial/inconclusive/unknown；旧 PASS/FAIL/INCONCLUSIVE 保留原值并归一化。Agent 报告的结果 `verification_status=UNVERIFIED`；交付完成不等于结果已独立核验，科研结论还需科学审查。负结果保留，不覆盖人类笔记；目标变更、冻结约束、方向关闭、证据替代或失效必须提出 Proposal/DecisionRequest 并等待人类处理。连接状态只由真实握手与最近通信决定，配置生成不代表在线。令牌须按权限范围发放并妥善保管。

## 连接方式

2026-10-03 接续升级：新界面生成的连接使用strict_v2，新版MCP的project.claim_action强制同模式；先实际get_context握手，提供当前context_hash、完整成功/失败判据、停止条件及报告预算。依赖须为同项目已登记任务，recorded只核对存在，all_completed才要求已完成。原HTTP legacy和旧行动保留兼容，不具有相同强保证。goal最多400字，其他契约文本最多4000字，超长拒绝而不截断；人批契约逐字保存并返回contract_hash，只读限制单独authority_note，不能改写原理由。scope与依赖策略分别保存。

外部行动中断：人类专用GET/POST /api/project/action-recovery，先核对全部已登记成果/结果，确认外部执行已停止，再dry、ifRev、action_version、contract_hash、source_hash确认。continue沿同Action换已握手的本项目Agent，保留原契约和已耗次数；旧worker写回拒绝。已有Result只能对账完成，不重跑；无法确认则标中断或UNKNOWN交付，不捏造Result。此操作不会终止宿主进程、启动模型或工具；缺失原判据不能默补成原授权。

结果人工复核：人类专用GET/POST /api/project/result-review，绑定Result/Evidence与target_hash、原来源版本、判据、审查者、所查版本和结论，先dry/ifRev。只追加收据，缺失/不符/符号版本照实保存；matched仅记录人填的相同sha256版本，不代表服务读取过原文件。软件接受不升级科学VERIFIED，原负结果和UNVERIFIED不变，科学NOT_ASSESSED。复核与对账收据随项目备份保留；旧缺新增集合的备份仍可恢复，但恢复不继承Agent握手事实。

工作区（2026-10-03）：项目旧workspace字段仅为路径建议。设置→Agents绑定根目录/项目相对目录/排除项后，GET /api/project/workspace返回canonical path、revision、read_only/path_policy与可用状态；POST仅人类令牌+if_revision+consent=project-workspace-binding-v1，先dry。绑定不是读取或写入授权，项目目录不能重叠。正文来源须独立确认workspace_revision，目录被替换或重绑时失效。索引先覆盖允许目录，再分批128项/64KB；2MB内文本可分段，超大和不支持项保留缺口；50000条目安全阈值会标记索引不完整。Agent接手检查workspace.state与正文coverage；不能以绿点、目录索引或已处理计数宣称全项目理解/核验。没有OS沙箱和跨Agent文件写入锁，禁止把路径策略说成完全隔离。详见AGENT-MANAGER.md。

- 令牌：默认读取 `~/Library/Application Support/ResearchDesk/api-token`（仅当前用户可读）
- 每个请求带 `Authorization: Bearer <令牌>`
- **先调 `GET /api/help` 可获得机器可读的完整 API 说明**，不用猜接口

## 铁律（违反会破坏用户数据）

1. **写之前必须先 GET 最新状态**；用 `POST /api/action` 做增量修改，不要用 `POST /api/state` 整体覆盖（除非恢复备份）
2. **乐观锁**：GET 时记下响应头 `X-Rev`，写入时带 `ifRev`；返回 400 说明用户刚改过，重新 GET 再来
3. **所有 Agent 写入先 `dry:true` 预检**；常规创建/更新可在预检通过后自动写入，不要求每一步都打断用户确认
4. **高风险操作保留人工确认**：删除整个项目、rollback、整状态恢复不得静默执行；MCP `research_project_delete` 必须显式 `confirm=true`
5. **删除用 `POST /api/action` 的 `op:"delete"`**（删项目会级联删任务/资料/决策；删任务会自动清理子任务与依赖），不要手工拼状态
6. Agent 真实写入必须带 `actor:"agent"` 和清晰 `summary`；历史界面据此区分 AI 与手动变更
7. 写入成功后服务会通过 SSE 通知页面自动刷新（`GET /api/events`），不需要让用户手动刷新
8. 大批量读取用 `GET /api/state?slim=1` 剔除资料索引大数组；新 Agent 接管优先调用 MCP `project.get_context`，旧全局连接可用 `research_agent_brief`

## 当前重点（旧 research-focus 接口兼容）

- `GET /api/project-focus` 只读当前按日期、scope 和项目上下文 hash 缓存的焦点，不触发 AI；显式本地规则分析可 `POST /api/project-focus`，body 带 `trigger=daily|task_changed|evidence_changed|manual_refresh`。旧 `/api/research-focus` 同效保留。新 Agent 提交结果、成果或依据后，服务端自动重判并追加 `focus.changed` 事件，无需手工 POST。
- Daily Focus 是建议，不是对项目状态的隐式写入。它可以绑定已有任务，也可以是待用户确认的综合动作；只有用户预览并确认采纳，且 ifRev 与建议来源版本一致，才保存正式任务或附加现有任务来源；不覆盖人工笔记。旧“加入任务”表单路径保留。
- `POST /api/research-focus/feedback` 记录人的 `accepted|rejected|alternate` 反馈；“换一个”应携带 `exclude_previous_focus_id`，避免重复推荐同一个焦点。
- 即使已配置 provider，模型也默认关闭；须另经用户批准项目、provider、发送字段与调用预算，登记私有 analysis-policy.json。刷新数据禁止调用模型。结果后自动模型分析默认关闭；采纳是未发送任务，不是排队执行。
- 服务端未配置 `RESEARCH_FOCUS_API_URL` 与 `RESEARCH_FOCUS_MODEL` 时使用规则回退；若配置的 AI provider 超时或返回不合规 JSON，也必须回退，不能把无效输出写入项目状态。

## 自主管理 Agent（v1）

项目页面 → 自主管理 Agent，或设置 → Agents → Codex常驻管理详情 → 修改总结频率。用户确认发送范围后可选15/30/60分钟或自定义1–1440分钟；新启用默认30分钟、不限每日次数。后台每三秒比较本项目登记内容hash，合并八秒内变化，到检查时间才总结最新输入；页面刷新与没有变化都不调用模型。摘要是未核验建议，不写入原任务/科学证据、不自动执行实验。默认不读聊天或原始文件正文；来源读取与正文发送仍须分别确认，未授权来源不能进入模型。电脑和服务须运行，恢复后不补跑每个错过的窗口。详见AGENT-MANAGER.md。

GET /api/project/manager?project_id=…只读策略、队列、来源hash、间隔、next_summary_at与schedule_revision。启用POST manager须原consent=codex-project-records-v1；不限次数定时模式还须max_calls_per_day:null、summary_interval_minutes、schedule_consent=scheduled-codex-management-v1。修改已有频率优先使用POST /api/project/manager/schedule，携带if_schedule_revision并先dry；不重置管理授权代次、用量、队列或旧失败。旧有限策略保留兼容，不默默放宽。每次最长180秒，保留真实使用记录；Codex套餐实际额度仍适用。暂停不启动新调用，在途输出隔离。失败不自动重试；检查后明确重新启用才重试。

`project.get_context` 返回 `management.latest_analysis`；执行 Agent 必须把它当建议而不是授权，核对来源仍有效，保留原科学问题、预算、负结果与证据等级，再按既有 Action 契约推进。不因管理摘要自动重跑实验。

v2：有效摘要自动形成管理行动草案；人审只读核查契约后，`management.ready_handoffs` 才可领取。优先 `project.claim_management_action({handoff_id})`，不得改写人批契约；不允许实验、改文件、改目标或替代依据。沿用 report_activity/add_artifact/record_result 并回写交接回执；负结果仍是负结果。恢复旧记录会使未领取审批失效。新MCP工具需重连；批准并排队不表示执行器已启动，也不会自动向其他聊天发消息。

运行队列与授权在私有数据目录 `manager.sqlite3`，独立于项目科学记录备份；恢复科学记录后按当前内容重新判断，不把旧管理摘要当恢复后的有效证据。服务重启保留等待队列；超过240秒的中断调用标为失败，未自动重跑。

v3：另行授权 `POST /api/project/manager/runtime`，consent=`registered-file-metadata-and-review-v1`，开启工作区内已登记文件元数据观察与固定记录/版本核查。只读本地字节计算hash，不向模型发送文件原文、不扫描目录或其他聊天；最多256个文件、单文件2MB，缺失/版本不符只报告不改旧证据。固定核查持久化自动领取与回执，不消费模型调用。

人批只读核查在runtime启用后可由独立管理执行器自动领取，读取登记快照、调用隔离Codex并回写Action/Result；沿用项目调用设置和原核查契约，不因总结间隔变更而重置报告预算。没有原文/网页访问能力，资料不足必须未知，科学结果始终UNKNOWN/UNVERIFIED，不接管研究Agent。`handoff`人审接口支持 operation=create 直接创建来源绑定的人批核查（仍需ifRev/source_hash/完整contract及dry）；这不是模型生成的草案。管理Action/Result/Evidence和本地回执不作为反思触发输入，防止自触发循环。自由形式AI建议仍不能自行变成授权。

## 常用配方（兼容接口）

```bash
TOKEN=$(cat "$HOME/Library/Application Support/ResearchDesk/api-token")
# 读 slim 状态（无资料索引）
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8765/api/state?slim=1'
# 建任务（批量示例）
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"ifRev":REV,"ops":[{"collection":"tasks","item":{"project":"PROJECT_ID","title":"…","priority":"P1","status":"待开始"}}]}' \
  http://127.0.0.1:8765/api/action
# 删除任务
curl -s -X POST … -d '{"ops":[{"collection":"tasks","op":"delete","id":"任务ID"}]}' …/api/action
# 逾期任务清单（本地过滤 state）
```

## 查询与聚合

- 逾期 = `end < 今天 && status != 已完成`
- 本周截止 = `end 在本周一~周日 && status != 已完成`
- 跨项目聚合视图见页面「我的本周」；agent 可按同样口径计算后在回复里汇总

## MCP

本目录 `mcp-server.js` 提供标准 MCP stdio 接入。请从设置为当前项目生成连接，核对权限和版本后由用户注册。修改工具集后，客户端需重新连接。不要复制维护者的本机配置或令牌。
