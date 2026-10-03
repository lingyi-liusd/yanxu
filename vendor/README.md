# 随包文档提取依赖

离线加载，不向系统 Python 安装，不修改 PATH 或 Codex 配置。

| 包 | 官方文件 | SHA-256 |
| --- | --- | --- |
| pypdf 6.19.0 | pypdf-6.19.0-py3-none-any.whl | 7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14 |
| typing_extensions 4.15.0 | typing_extensions-4.15.0-py3-none-any.whl | f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548 |

来源：https://pypi.org/project/pypdf/6.19.0/ 与 https://pypi.org/project/typing-extensions/4.15.0/ 。许可原文保留在各 wheel 的 dist-info/licenses 目录中。加载前核对整个 wheel 摘要；这是完整性检查，不是代码签名或安全审计。

仅提取文本型 PDF 与 DOCX 中声明范围的文字，不做 OCR、不解释图表/公式/排版。每个原文件最多 2MB；提取文字最多 2MB，PDF 最多 100 页，子进程最长 12 秒。宏、加密、异常压缩或超出范围明确拒绝。新格式需每项目额外勾选授权，旧授权不会自动扩大。
