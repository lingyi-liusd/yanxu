# 研序 Research Desk · 内测使用指南

版本：2026.10.03-beta.16 · 更新日期：2026-10-03

beta.16：设置 → Agents → 启用常驻连接。未登录时自动打开官方登录页，研序显示“等待登录”并提供“打开登录页”备用入口。已有登录请求复用，不反复创建；回调后以账号读回确认，再显示已连接/需选择模型。登录失败或过期时再次点击“登录并连接 Codex”重新发起，不自动重试、不复制其他实例凭据。登录、模型选择、项目总结和文件授权仍独立。真实账号输入须由本人完成。

beta.15 修复损坏交接条件导致整个项目管理接口不可查看的问题：损坏格式、非对象或不完整的核查条件明确标记，不能作为待执行授权；原记录不改写，已执行轮次仍读回冻结的原批准版本。隔离合成测试覆盖真实 HTTP 接口、停止执行、保留 UNKNOWN 结果与不重放。该修正不新增权限，不代表桌面首次登录或真实 AI 全链路已经验收。

beta.13 在项目状态的自动总结详情中，用“核查 → 汇总 → 登记”展示人批只读核查。只显示最近一轮，旧轮次按需展开；原契约、来源版本、用量与失败保留。只有实际行动、结果和同来源依据记录对得上才显示“已登记”，可直接打开报告；分批回包、汇总完成或软件任务成功都不等于科学核验。回写未确认会明确提示先对账、不重复调用模型。新增进度解释可中英切换，原始内容不改写。

Mac 应用菜单增加“关闭窗口后保持 Agent 运行”，默认关闭。首次开启需确认：只保留当前测试空间已授权的能力，定时总结仍可能消耗账号额度；不增加文件权限、不设置开机自启，不是云端常在线。开启后关闭窗口只隐藏窗口，不停止 Agent；使用应用菜单“显示研序窗口”重开窗口。菜单退出或 ⌘Q 仍会停止所属服务。偏好只保存在当前测试空间，电脑睡眠、关机或应用崩溃时不保证运行。

项目状态显示总结阻断与分批进度。大项目保留全部原记录，按固定来源快照分批处理，再汇总成一份未核验摘要；每批及汇总都计入账号用量，原每日次数/频率、授权和失败历史不重置。全部完成前不生成行动建议，失败/中断不自动重试；成功批次重启后不重复调用。每次准备输入仍限180 KB，单条记录过大或回包无法汇总会明确保留缺口，不删历史、不截断内容。连接绿点、分批回包或总摘要都不证明全部资料已理解或科学核验。源码回归、包自检、真实模型和各平台原生验收分别记录，以本版证据为准。

beta.11 修正分批进度提示的实际语言切换范围；beta.10只有翻译词典，不足以证明页面切换有效。新进度与用量提示可英汉切换，原记录正文、契约和科学术语仍保持原文，不能宣称所有高级界面已完整翻译。

beta.12 将大项目的人批只读核查也接入完整快照分批队列。每批保留同一份批准契约，并检查来源与执行授权版本；只有全部回包与汇总完成才回写一份交付。暂停后重新授权不继承旧执行批次，失败/中断不自动重跑。模型回包先落盘，结果事务再核对授权；已提交的结果不会因回执中断重复创建。未提交的回写失败保留“需人工检查”，不能当作交付完成。该机制不开放工具、实验、额外目录读取或科学验证；真实登录/模型与各平台原生验收仍独立记录。

原生菜单的登录、打开数据目录、退出现在使用应用启动时的同一测试空间。自定义隔离目录不会因 Terminal 已运行而登录到默认目录；启动过程中退出会等待启动完成并停止所属服务。该版本重新编译原生宿主，不以更新网页替代原生修复。

启动准备阶段退出会取消本次只读取后台偏好的子进程，不再等待这个阶段无限结束，也不启动服务；已经进入服务启动阶段时仍等待并停止所属服务。系统目录访问提示或受保护目录的可用性仍需真人验收，不能通过放宽系统权限绕过。

本版增加授权失效的恢复入口：AI 设置显示“继续仅登记信息总结”与“重新确认文件观察”。前者停用旧观察、不读取新目录，保留总结频率与用量；后者须重新明确确认目录。预检查不保存，设置版本冲突时不自动重试。恢复后仍须等待实际总结回包，不把“已保存”当作“AI 已完成”。

### 简化后的 AI 设置

左下角有独立的 **工作区** 入口，直接显示当前项目「已绑定／未绑定」，点击即可选择项目目录，不必先找资料范围。**AI 设置 · Agents** 中按「项目工作区 → 总结模型 → 资料范围（可选）」分开呈现。工作区和模型尚未完成时用轻微闪烁的红点提示，完成相应项后消除该红点；不要求为消除红点而授权读取或发送资料。开启系统“减少动态效果”时红点不闪烁。工作区按项目绑定，切换项目不会沿用另一个项目的绑定显示。

模型列表完整展示当前登录 Codex 接口返回、可接收文字的模型，包括默认菜单隐藏项，不再折叠为“其他模型”。研序不限制为推荐项，但不能解锁账户或接口不支持的模型；推荐按钮只选择，不替你确认或发送资料。

选择范围时，未绑定的项目先通过系统文件夹窗口绑定目录，再选择要读取的资料；已有工作区直接进入范围选择。路径、对话链接和排除项在高级设置中，原项目内容保持不变。

本地读取、PDF/Word 文字提取、发送正文给 Codex 三项独立勾选。选择目录本身不授予权限；取消不修改授权。目录绑定成功后即已保存，若下一步取消或失败，仍然不会开启来源读取。改变目录或排除项会使旧授权失效。系统选择器不可用时可粘贴路径；Windows 原生选择器仍待真机内测。

绑定及资料确认会显示保存中，并依据服务器保存回执立即更新，不要求手动刷新。目录重绑后，旧文件观察授权会显示“已失效”，不再让整个状态页面读取失败；无效授权下的旧排队任务不执行、不因此记一次调用尝试。请到项目状态的自动总结详情检查旧文件观察授权，需要时先暂停，再明确确认新范围；不会自动恢复旧核查或扩大权限。

欢迎参加研序内测。研序帮助你把任务、AI 推进记录、成果与来源放进同一个项目，快速看清：**现在做到哪里、为什么变化、接下来做什么。**

这是公开测试版，不是稳定正式发行版。请先用一个非关键项目或虚构资料测试，不要首次就导入唯一副本、账号密钥或敏感文件。安装包不含开发者的项目、账号或资料。

## 1. 选对安装包

| 设备 | 文件 | 当前验证范围 |
| --- | --- | --- |
| Apple 芯片 Mac，macOS 12 或更新 | 研序测试版-macOS-Apple芯片.zip | 以此版包内、绑定文件摘要的自检和原生应用回执为准；旧版通过不证明新版已验收 |
| Windows 10/11，x64 | 研序测试版-Windows-x64.zip | 发布时校验文件与 x64 可执行格式；Windows 原生执行为 NOT_RUN，安装时另在测试者设备上自检 |

暂未提供 Intel Mac、Windows ARM 或 Linux 安装包。运行依赖已包含，不需要另装 Python、Node 或开发工具。普通项目管理可离线使用；AI 功能需要联网、自己的可用 Codex 账号及明确授权。

### Mac

1. 完整解压 Mac ZIP。
2. 打开「研序测试版.app」。也可以先拖入「应用程序」，再打开。
3. 首次安装进入为空工作空间，这是正常现象。若以前用过测试版，会继续使用本机 `ResearchDeskBeta` 中的记录；新版包不携带他人的项目。
4. 退出时使用应用菜单的退出入口。
5. 希望只关闭窗口而不停止 Agent 时，先在应用菜单明确开启后台驻留；它与账号登录、连接启用、项目总结授权是不同设置。

本包使用本地 ad-hoc 签名，尚未 Apple 公证。如果系统阻止打开，请把提示截图发给项目维护者；不要关闭 Gatekeeper、关闭安全软件或执行来源不明的解锁命令。签名、公证与其他 Mac 的首次安装体验也是本轮待验证项。

### Windows

1. 完整解压 Windows ZIP；不要在压缩包预览窗口中直接运行。
2. 打开「研序测试版-Windows-x64」文件夹，双击「一键安装.cmd」。安装器先运行离线自检，自检失败时请保留报错并反馈。
3. 安装成功后，从桌面「研序测试版」快捷方式打开。
4. 不想安装时，可以在解压目录双击「打开研序.cmd」试用。优先使用 Edge 应用窗口，没有 Edge 时使用默认浏览器。
5. 用桌面「退出研序测试版」或解压目录「退出研序.cmd」停止后台。只关闭浏览器窗口不等于后台已经退出。

安装位置为当前用户的 `%LOCALAPPDATA%\ResearchDeskBeta\Apps`，不要求管理员权限、不修改系统 PATH。如果 Windows 或公司策略阻止脚本/程序，不要关闭防护；反馈提示即可。

## 2. 第一次使用：先不用 AI

建议用 10–15 分钟完成下面这条路线。

1. 点「新建项目」，填写名称和一个具体目标，例如“整理三份资料，形成一页比较结论”。
2. 添加一条任务，写清下一步；需要排期时再填写日期，不必把所有字段一次填满。
3. 看 Today：能否说清当前在做什么，以及主按钮会带你去哪里？
4. 打开「项目状态」，看阶段和最近变化；不要把“交付完成”理解成“结论已验证”。
5. 从「成果与文件」进入「项目笔记」，保存一段正文，退出再打开，检查内容是否保留。
6. 试一下日历排期、行动泳道、结果分类和时间线。没有数据的地方应保持空白，不应编造进展。
7. 点击右上角 `English` / `中文` 切换界面语言，刷新及退出重开后再看设置是否保留。偏好保存到当前研序数据目录，不修改 Codex 配置。项目名称、笔记和研究原文不会自动翻译；部分高级提示和后端错误仍可能中文。

不连接 AI 也能先测试基本体验。需要给文件建立索引时，在「设置 · Agents」先绑定项目工作区，再单独确认用于内测的来源目录。目录绑定、读取文件、允许的正文格式和向模型发送正文分别确认；目录绑定本身不构成读取授权。

PDF/DOCX 仅在当前项目明确允许该格式后提取文字。默认不因升级包就读取新格式或扩大旧授权；扫描件、加密文件、图片、公式、图表和提取失败仍可能留下缺口，不提供 OCR 或完整排版理解。查看资料覆盖与阅读回执中的原文件版本、提取/片段状态和缺口，不能把“已索引”当作已读全文。

## 3. 可选：测试 AI 与 Agent

AI 默认关闭。请先完成上面的基本操作，再决定是否启用。

1. 登录测试版 AI：在研序「设置 → Agents」点击「启用常驻连接」，未登录会自动打开登录页；浏览器未弹出时点击提示框「打开登录页」。使用你自己的 ChatGPT 账号，完成后回研序查看自动更新的状态。不要同时发起多个登录流程。Mac 顶部菜单和 Windows「登录AI.cmd」保留为旧入口；不要与页面登录同时启动。不要向任何人发送登录文件或令牌。
2. 在「设置 · Agents」启用常驻管理连接，等待真实握手、账号检查和模型列表返回，再明确选择可用模型。模型选择只保存在研序；不可用时显示“需选择模型”，不会自动改用其他模型或重放旧失败。
3. 在当前项目中另行确认自动总结的发送范围和频率，可选 15、30、60 分钟或自定义。连接、模型选择、项目管理、正文格式和资料发送各有边界；连接成功不表示已授权读取文件或执行任务。没有新变化时不应重复调用模型；电脑和研序必须运行。账户额度、网络及模型调用限制仍适用。
4. 如需外部执行 Agent 写回成果，在「设置 · Agents」按当前项目生成连接配置，使用界面给出的注册方式。配置中的令牌只能留在你的设备，不要截图分享，也不要用它覆盖已有全局 Codex 配置。
5. 用一个小任务测试：Agent 读取项目 → 认领行动 → 报告进度 → 登记成果与来源版本 → 报告结果 → 回到研序查看状态和下一步。

生成配置不等于已连接；必须完成实际握手。常驻管理主要负责总结与获批的有限核查，不代表所有建议都能无人值守执行，也不会因为你开启总结就自动接管所有项目或科研实验。失败时先查看原因，不要连续开启重复任务。

### 怎样读状态

- 行动领取、推进、交付和结果核验是不同状态；任务做完可以得到失败或部分通过的结果。
- 结果红点：报告失败；绿点：报告通过；黄点：报告部分通过；灰点：未知或未定。绿点不代表已经独立核验，需看详情中的来源、版本与 `UNVERIFIED` / `VERIFIED`。
- 连接绿点：实际握手、登录和所选模型可用；黄点“需选择模型”：通道正常但模型不可用。其余连接状态按页面原因判断；重启后保存的模型名称不代表已重新确认可用。空闲不等于失败，绿色也不是永远在线的保证。
- 阅读回执：记录调用当时的来源范围、版本、片段和处理状态；“接受/已处理”表示相应片段获得有效模型回包，不代表完整理解、独立核验或新的用户授权。历史批次统计是固定快照，当前账本会变化；准备输入的 JSON 摘要不证明实际协议字节或发送成功。
- 「实时交付状态」来自行动与结果；「已保存状态说明」是保留的原文，可能是历史说明。不要混为同一个实时判断。

## 4. 我们最需要的反馈

请尤其留意：

- 你是否能在一分钟内说清项目现状、一个未确认点和下一步？
- 能否从结果找到原来源和版本，而不是只看到一段 AI 总结？
- 哪个页面信息太多、重复、难懂？哪个按钮让你不知道会发生什么？
- 保存、退出重开、切换项目后，是否丢内容、串项目或显示旧状态？
- AI 回写后是否及时更新？是否把失败或未核验内容误显示成已确认成功？
- 英汉切换有没有漏译、误译原文或布局挤压？

出现数据丢失、越权读取、重复执行或错误升级核验状态时，先停止该项目的 AI/来源功能，保留现场并反馈；不要用关键项目继续试。

把下面内容通过仓库 issue 向项目维护者反馈即可。不需要发送整个工作空间。

```text
版本：2026.10.03-beta.16
系统与芯片：
问题发生时间：
操作步骤：1… 2… 3…
原本期待：
实际看到：
退出重开后是否仍存在：
影响：无法打开 / 数据丢失 / 权限问题 / 功能错误 / 难理解 / 外观
截图或原始报错（已遮挡私人内容）：
```

请遮挡姓名、路径中的个人信息、项目正文和连接令牌。不要发送 `auth.json`、`api-token`、Codex 登录文件、完整对话日志或研究数据库。反馈没有自动上传，需要你自行选择分享范围。

## 5. 数据、备份与退出

- 测试版使用独立数据目录，不覆盖正式研序：Mac 为 `~/Library/Application Support/ResearchDeskBeta`；Windows 为 `%LOCALAPPDATA%\ResearchDeskBeta`。
- 测试版使用本机端口 `18765`。多个副本会争用同一测试实例；如果启动提示冲突，先用当前测试版退出入口停止后台，再尝试打开。
- 安装包不带生产数据库、登录凭证、私人资料或管理授权。测试版 AI 登录与正常 Codex 配置隔离；来源读取仍需明确授权。
- 新版本存放在新的发布/安装目录。保留旧 App 与 ZIP；Windows 若发现不同安装目录的同名快捷方式，会要求先重命名旧快捷方式。更新前退出正在运行的测试版，再打开新目录里的 App/启动入口。
- 需要保留记录时，先用「数据与外观 → 导出备份」。项目备份不等于备份账号登录或全部 AI 授权设置；原始文件还需你自行保留。
- 移除应用文件不会自动删除项目数据。首次测试后若要清理，请先确认备份，不要盲目删除原有 Codex 或正式研序目录。

仅供诊断和新包首次使用验收：诊断人员可在启动进程前显式设置 `RESEARCH_DESK_BETA_DATA_DIR`，指定独立、真实的绝对目录；相对路径、符号链接及经过符号链接的父目录会被拒绝。所选目录保存测试记录，独立 AI 登录位于其 `codex` 子目录。不要指向正式研序目录、正常 Codex 目录或原测试资料目录。未设置（或空值）时继续使用上方默认用户位置，不自动迁移记录。启动、登录和退出须使用相同诊断目录；切换目录前先停止当前测试后台，端口仍为 `18765`。这不是普通安装步骤，也不新增资料读取或模型调用授权。

## 6. 本版本边界

目前适合小范围、非关键项目内测。具体已测代码以此版「打包验收.json」和绑定包内文件摘要的离线自检为准，原生窗口与真实模型流程还需对应版本的单独回执。没有回执的检查仍为待验证，不沿用旧版成功结论。

工作区提供应用层路径限制，不是操作系统沙箱，也没有跨 Agent 文件写入锁。打包与安装自检使用合成资料、空数据和独立临时账号目录，模型调用为零；自检通过不证明模型质量、用户收益或科学结果。文档解析依赖随包提供，wheel 内保留各自许可；来源说明（若提供）位于 `app/vendor/README.md` 或 `THIRD-PARTY-NOTICES.md`，文件摘要纳入清单。依赖摘要不等于代码签名或完整安全审计。

尚未完成：Windows 原生安装与运行验收、跨机器长期稳定性、完整高级文案本地化、无人值守跨 Agent 自动调度，以及正式平台签名/公证。App 交付、AI 报告和科学结论分别判断；研序不是“开着就自动证明所有结论正确”的软件。

---

## English quick start

Research Desk is a public beta for organizing project work, Agent activity, deliverables and their sources. Start with a disposable, non-sensitive project.

- **Apple Silicon Mac, macOS 12+:** extract the Mac ZIP and open `研序测试版.app`. The app is locally signed, not Apple-notarized. If blocked, report the message; do not disable security protections.
- **Windows 10/11 x64:** extract the entire Windows ZIP, run `一键安装.cmd`, then use the desktop shortcut. `打开研序.cmd` launches without installation; `退出研序.cmd` stops the background service. Windows native execution is not yet verified.
- Runtime dependencies are included. Basic project work can run offline. AI requires a network connection, your own eligible account and explicit project consent.
- Create a project, add a task, inspect Today and Project status, then save and reopen a note through Outputs & files → Project notes.
- Use the top-right language button. The preference is saved in this Research Desk data directory and survives refresh and restart, without changing Codex configuration. Original notes and research content stay unchanged; some advanced messages remain Chinese.
- AI is off by default. After login and a live handshake, explicitly select an available model. Connection, project consent, document-format consent and source-content sharing are separate choices. No model fallback or failed-job replay is automatic.
- On Mac, opt into “关闭窗口后保持 Agent 运行” in the app menu to keep the already-authorized Agent running after closing the window. Use “显示研序窗口” to show it again; Quit / Cmd-Q still stops the service. This is local background operation, not a cloud service or launch-at-login setting. Sleep and shutdown suspend availability.
- Oversized registered inputs now show a specific blocker and size breakdown. The 180 KB per-input limit remains; no history is silently truncated or deleted. Large registered projects use a fixed-snapshot multi-batch queue and aggregation; incomplete or failed batches retain explicit gaps.
- PDF/DOCX text requires explicit format consent. Reading receipts bind versions and chunks, not complete understanding or scientific verification. Scanned pages, images, equations and extraction failures can remain gaps; no OCR is provided.
- A completed delivery or green reported result does not imply independent verification. Check the original source, version and verification status.
- Report your OS, version, steps, expected/actual behavior and a redacted screenshot to your tester contact. Never share tokens, login files, private databases or full conversation logs.

Private beta data uses `ResearchDeskBeta`; an existing beta keeps its local records. Workspace path rules are application checks, not an OS sandbox. Removing the app does not automatically remove saved data. Keep older apps and archives; use the receipts bound to this release's exact file hashes. Long-running unattended workflows, full localization and Windows native behavior remain test areas, not release guarantees.

Diagnostics only: explicitly set `RESEARCH_DESK_BETA_DATA_DIR` before launch to use a separate real absolute directory, with its own `codex` login subdirectory. Relative or symlinked paths are rejected. An unset or empty variable keeps the default location. Use the same directory for launch, login and stop; stop the current beta before switching. This does not grant source access or AI consent.
