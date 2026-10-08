# v2 最小开放契约

2026-10-05；当前实现的接入说明。一个来源包、一种固定评审模板、现有 Agent 接续，不要求扩展改核心源码或数据库。独立外部使用者验收仍 NOT_RUN。

## 先发现当前核心

GET /healthz 返回根字段 build_id；capabilities 内 product=yanxu、distribution=unified、version=yanxu.ecosystem.v2及 contracts：ecosystem=2、review_brief=1、source_extractor=1、external_reply=1。检查实际 localhost 端口，不假定 8765 一定是目标实例。

源码启动器还比较源码路径、数据路径与 build_id。兼容 API 仍存在，版本发现不是所有旧外部客户端的强制协商机制。扩展遇到未知 schema_version 应停止提交，不靠省略字段尝试写入。

## 来源包 v1

静态 JSON，只声明关注问题与 1–6 个明确公开 URL，不运行扩展代码。示例 source-packs/public-updates.v1.json；字段必须精确匹配以下形状：

```json
{
  "schema_version": "yanxu.source-pack.v1",
  "name": "我关心的软件变化",
  "question": "所选来源出现了哪些值得复核的变化？",
  "sources": [{
    "name": "Flask releases",
    "url": "https://github.com/pallets/flask/releases.atom",
    "keywords": [],
    "interval_minutes": 1440
  }]
}
```

名称最长 100 字，问题最长 1000 字，每处来源最多 12 个关键词、每词 80 字，间隔 15–1440 分钟。重复 URL 拒绝。UI 文件上限 20KB；服务对结构与字段另行校验。导入只创建暂停来源，auto_push=false，保存包名、版本与规范化 SHA-256；不会自动读取、推送或调用模型。

UI：观察→导入来源包→明确选文件→查看问题/来源/检查间隔→确认导入。人类 HTTP：GET 当前 ecosystem 后，POST /api/ecosystem，operation=source.pack.import、project_id、ifRev、pack，先 dry:true。扩展 Agent 不持有此全局主人接口权限。

首次成功检查建立基线；失败保留覆盖缺口。公开 URL 语法合法不证明 DNS 会解析到允许地址，也不证明内容是真实或完整。当前示例包在本机 DNS 条件下尚无成功读取。

## 固定评审模板与简报 v1

review-templates/solution-tradeoff.v1.json 记录当前“需求或方案取舍”的输入提示、单执行器/一轮/一次配额及输出 schema。它是当前固定模板的可检查定义；任意模板文件的导入、注册和运行尚未实现。

人类输入 question、constraints、materials（1–12 份，单份内容最多 16000 字、总 JSON 最多 200KB）；先保存草稿可以不选执行器。材料内容保存实际摘录、SHA-256 和行数，不自动扫描目录或拉取链接全文。

简报 schema_version=yanxu.review-brief.v1：

- recommendation：建议及理由。
- alternatives：候选方案。
- tradeoffs：关键取舍。
- disagreements：分歧与反例。
- unknowns：缺失信息。
- next_step：下一步。
- recheck_conditions：重新评审的条件。
- citations：最多 24 项，每项必须有 claim、material_id、locator、relation。

relation 为 source/inference/unknown。指向材料时 material_id 必须在本次范围，locator 使用 L1 或 L1-L3，不能越界。无材料则 material_id/locator 为空且只能标 inference/unknown。定位通过不会把内容提升为 VERIFIED。

人工编辑使用 review.brief.save、对象 expected_rev、当前 brief_revision、完整 content 和 reason，先 dry；保留原始执行器 output 与过去简报/理由。采纳要再次检查项目上下文、源对象与简报版本，写入 review_ref/material_refs/复核条件，任务尚未执行。GET /api/ecosystem/brief 只供人类本项目导出 Markdown，不给 Agent 主人权限。

## 外部 Agent / MCP 回复

界面入口：评审→执行器设置→登记外部 Agent，默认 PROPOSE，可选 READ，只绑定当前空间；先 dry、ifRev 预检，再登记。界面不提供 EXECUTE，不运行模型或授予文件读取；令牌只在本次回执中展示，默认隐藏；可点击显示后手动复制，复制失败提示显示在回执内，关闭清空字段。需实际握手才在线。已有高级人类接口仍可在指定项目登记 READ/PROPOSE/EXECUTE 令牌；READ 只能读取，评审回复需要 PROPOSE 或 EXECUTE。使用原 Node MCP stdio 桥：先 project.get_context 实际握手，再 project.get_discussion_requests，找到 mode=review、reply_tool=project.reply_review 的有效请求。

请求给出 room_id、participant_id、run_id、明确材料、约束、上下文、output_schema、预算与 deadline。回复必须携带前述三个 ID 和符合 schema 的 output。旧讨论使用 project.reply_discussion 的四字段格式；不得把两者混用。HTTP 等效入口 GET /api/agent/context、GET /api/agent/ecosystem、POST /api/agent/discussion/reply。

服务拒绝跨项目、未握手、角色不符、过期、停止、重复回复、上下文变化或无效引用。接受回复保留 UNVERIFIED，只消耗此轮接受回复配额，不能证明外部执行器用了几个模型、调用几次或已彻底停止。执行器实际权限、费用和取消确认由其自身披露。

examples/review-client.py 是 stdlib 手动适配示例。令牌通过 YANXU_AGENT_TOKEN 环境变量注入。只读使用：

```sh
python3 examples/review-client.py --core http://127.0.0.1:18770
```

显式指定本次回复 JSON 文件与 room 才提交：

```sh
python3 examples/review-client.py --core http://127.0.0.1:18770 --room ROOM_ID --reply selected-reply.json
```

示例在读取项目材料前检查 healthz 的核心契约，未知版本拒绝；只列 mode=review / reply_tool=project.reply_review 请求，忽略旧多角色讨论。只读调用会登记握手/通信状态，但不回复或消费接受回复配额。示例不发现其他文件、不调用模型、不背景轮询。令牌不得写入回复文件、URL、报告或 Git；无需直接开数据库。接口无自动科学执行权；推进项目仍沿既有 Action 成功/失败判据、预算和停止条件。

## 恢复与兼容边界

run_id 与持久 attempt 区分预算预留、发送授权、派发和接收。普通同库备份恢复保留最大消费，旧运行不能通过回滚数据重获新预算；网络等待不锁住业务数据库。数据库文件整体回退、跨机器恢复和提供商重复计费不具备此保证。

首个独立接入应验证：扩展不改核心、不用主人令牌、按版本提交；撤权/过期/跨项目拒绝；成功输出可导出；无额外文件或模型使用。当前合成 HTTP/MCP（含独立客户端、未知版本拒绝与完整负结果接续）通过；实际浏览器/Mac 只验表单和取消，登记提交由隔离接口/夹具验收。独立接入包已准备，见 integration-kit-token-access-v2.json；不能代替真实外部使用者记录。

2026-10-05 前端接续：preview.4 与 integration.2 的接口契约兼容，客户端未改变；前端模块抽取不增加 Agent 权限、材料发送范围或自动运行。新模块由主界面与兼容入口共用。

评审记录范围（preview.5）：review.create 可选 context_selection={tasks:[],decisions:[],results:[]}，每类最多20个同项目ID，review_of自动加入decisions。缺字段的旧客户端沿用原全项目上下文。选取模式 context.schema=yanxu-review-context-v1，selection与实际tasks/decisions/results一致；发送与回写门禁使用同一快照，不读取未选记录。旧 schema=yanxu-project-context-v1 保持。healthz.features声明 review.context_selection.v1；接入者须能处理这两种已声明上下文或明确拒绝，不能自行扩大范围。已提供手动客户端不解析/重写上下文，工程验证通过，不保证所有未知旧客户端兼容。

最新试用包 integration.3 推荐 preview.5，客户端/来源包/模板/合成回复未改，仅更新范围说明；独立使用者仍 NOT_RUN。

范围边界：context_selection 限定研序生成的本次评审输入与失效依赖，不撤销已发令牌的项目级 READ/PROPOSE。独立 project.get_context 握手仍可读取获准项目登记记录；这不是记录级权限沙箱。外部客户端应只把该 request.context/材料作为本次评审输入，未知客户端的额外读取/模型行为不由此选择器保证。

preview.6 新增能力 `review.history_snapshot.v1` / `adoption.target_project_version.v1`。历史评审仍调用 review.create，但用 history_source 代替 materials：`{room_id,expected_rev,context_hash,reason,selection:{materials:[],tasks:[],decisions:[],results:[]}}`。只能引用同项目非运行中的原 room，原对象版本与保存上下文必须相符；1–12 个明确快照，理由必填。原任务/判断/Result 的完整 JSON 或原材料正文转为新的 M1…材料，超量拒绝，不截断。另传 context_selection 选择当前登记记录；界面默认不选。历史快照不会改变原 room 或重置其预算，也不会绕开当前项目/选定当前记录的发送、回复和采纳门禁。

请求、模型输入、人类预览和 Markdown 包含 history_source 收据：旧 room/object revision/context SHA、明确理由、旧消费与新材料映射。新 room 契约只在存在该字段时加入收据；旧契约哈希不变。备份校验收据与材料自洽，即使原 room 不在备份中仍可保留快照；这是未核验来源记录，不是独立出处认证。integration.3 的客户端不解析或改写材料与收据，本版工程用例通过；未开展独立使用者试用，也不保证未知客户端能正确解释历史材料。

采纳可携带 `target_project_version`，来自目标 `/api/ecosystem` 顶层同名字段，即项目对象的 SHA-256。事务内核对目标存在、正式项目限制与版本；无关目标任务变化不使此门禁失效。源 expected_rev、当前选定记录、简报版本和采纳去重继续校验。与 target_context_hash 同传拒绝；缺新字段的旧客户端仍使用原目标全上下文门禁。目标门禁类型/版本保存于采纳回执。

preview.7能力 `observe.result_proposals.v1`：GET /api/ecosystem 顶层result_observation含candidates/total/shown/boundary。仅已登记同项目、明确关联链的Result候选，source_hash/basis_hash与target版本冻结。人类POST operation=watch.result.resolve，需要project_id/id/expected_rev/proposal_id/basis_hash/resolution(keep|modify)/rule={question,keywords,interval_minutes}/reason/consent=result-observation-adjustment-v1，先dry。规则最多1000字/12关键词每词80字/15–1440分钟整数。只能处理当前watch；Agent401、缺同意/理由、版本漂移、重复处理拒绝。keep不变规则，modify须有实际差异；任何URL/启用/推送字段均不由本操作修改。每来源50不可变result_adjustments收据，schema=yanxu.result-observation-resolution.v1，原负结果/UNVERIFIED/来源版本保留；恢复校验只自洽，不是出处真实性认证。不改变旧核心contracts版本，integration.3客户端未改，未知客户端和独立使用者未验证。

## 群定向雷达推送（源码新增）

能力 `radar.group_push.v1`；来源配置与人类确认的增量契约见 [RADAR-PUSH.md](RADAR-PUSH.md)。不改变外部回复 schema，外部 Agent 获得冻结 source_change。推送本身不启动 Agent/模型，原权限/项目/版本门禁继续生效。
