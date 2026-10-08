# 雷达阅读工作台改版 · 2026-10-05

本轮目标是提高发现阅读与来源管理的可用性；群聊推送与确认后调用模型的协议不变。

| 参考产品 | 官方设计依据 | 本轮采纳 |
| --- | --- | --- |
| Feedly | [阅读视图与密度](https://docs.feedly.com/article/276-how-do-i-change-the-views-of-my-feeds-and-source)，文档更新于 2020 年 | 清晰标题、来源与时间的阅读卡片；不复制付费功能或产品资产 |
| Inoreader | [2024 年改版说明](https://us.inoreader.com/blog/2024/10/the-new-inoreader-experience-is-here.html)、[阅读布局](https://www.inoreader.com/help/basic/article-view/what-layout-options-are-available) | 发现与来源分区，搜索及状态/来源筛选；历史改版作为设计参考，未登录验收其当前完整产品 |
| Visualping | [变化通知与对照](https://help.visualping.io/en/articles/4438913) | 强调新增/移除的前后文字对照；当前不提供网页截图差异或 AI 变化摘要 |

页面采用低对比背景、白色阅读卡片、蓝色主动作；统计来自现有记录。失败、过期、未检查与有效覆盖分别展示，不制造重要性评分或来源覆盖成功。来源检查与历史收进来源页详情。搜索和筛选只改变本地视图，不写记录。

验证入口：radar-visual-validation.json。34 个 UI 套件及内联脚本编译通过；浏览器检查搜索空结果、组合筛选、来源页、差异和推送目标选择（取消）。0 次新来源检查，0 次模型调用。截图中的发现是此前合成验收记录。原生安装包未更新。
