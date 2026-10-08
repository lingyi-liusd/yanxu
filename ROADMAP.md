# 路线图

当前源码：2026.10.08-source-preview.2，续芽生态源码预览。桌面 beta.16 是历史安装包，不含当前三入口界面与群聊 / 雷达能力。以下是改进方向，不是完成声明或交付日期承诺。

## 当前开发分支

讨论室＋项目雷达的首版软件框架已实现；用户收益、真实模型效果、公网读取和客户端适配范围仍需实测。架构、验收和接续入口见 [生态工作入口](docs/ecosystem/INDEX.md)。未更新公开安装包。

## 优先

- [ ] Windows 10/11 x64 真机安装、快捷方式、目录选择与退出验收。
- [ ] 当前 Mac 版本在独立设备上的首次安装、登录、退出与重启验收。
- [ ] 英汉高级文案与故障提示一致性。
- [ ] 用目标用户的实际项目观察首次设置和中断后接续体验。

## 工程改进

- [ ] 将大型单文件界面逐步拆分，保持现有行为和三栏布局。
- [ ] 跨机器、多日运行、中断与备份恢复的持续验证。
- [ ] 平台签名 / 公证与更清晰的升级流程。

## 需要另行设计的范围

多用户公网部署、云端常在线调度、任意 Agent 无人值守协作、跨 Agent 文件写入锁、其他桌面架构的分发包。当前不承诺这些能力，也不以模型摘要替代科学核验。

---

# English · Roadmap

Current source: 2026.10.08-source-preview.2, Xuya ecosystem source preview. Desktop beta.16 is a historical installer and does not contain the current peer apps, group chat or radar. These are proposed improvements, not completed features or delivery-date commitments.

- [ ] Native Windows 10/11 x64 installation, shortcuts, directory selection and shutdown acceptance.
- [ ] First install, login, quit and restart of the current Mac package on an independent machine.
- [ ] Consistent Chinese/English advanced UI text and error messages.
- [ ] Observe setup and resumption with intended users' real projects.
- [ ] Gradually modularize the large UI while preserving behavior and the three-pane layout.
- [ ] Validate multi-day operation, interruptions and backup restoration across machines.
- [ ] Improve signing/notarization and upgrade instructions.

Multi-user hosting, always-on cloud scheduling, arbitrary unattended agents, cross-agent file locks and additional desktop architectures require separate design. Model summaries do not replace scientific verification.
