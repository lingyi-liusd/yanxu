# Xuya (续芽) · Workbench, Discussion and Radar

A local-first AI project workspace with three peer apps: project workbench, multi-model group chat and source-change radar. Formerly Yanxu / 研序; the repository URL remains compatible.

**This is the October 8 source preview.** The older beta.16 desktop downloads do not include these new interfaces or ecosystem features. Native installation, real-model quality and user benefits have separate incomplete validation gates.

## Run from source

Python 3.13 and Node.js 22 are recommended.

```sh
git clone https://github.com/lingyi-liusd/yanxu.git
cd yanxu
python3 launcher.py
```

For an isolated synthetic demo, run `python3 scripts/start_demo.py`. Open the printed localhost URL. Use `/` for projects, `/apps/discussion/` for group chat and `/apps/radar/` for monitored changes.

Users can create groups and invite configured models or agents. Radar stores source snapshots and differences, then delivers a pending item to an inbox or group. Delivery does not invoke models. Human confirmation selects the question, members and history before a discussion begins. Human adoption preserves source references and versions; new tasks remain `UNVERIFIED`.

Failed, unchecked and stale sources remain distinct. An empty feed does not prove no change. Model suggestions and completed tasks do not establish verified conclusions.

The stack uses vanilla JavaScript/HTML/CSS, Python, SQLite and optional project-scoped MCP / Codex connections. Users provide their own model access. Data lives locally; path policies are not an OS sandbox.

![Radar with synthetic change material](docs/images/radar-20261008.png)

V2 includes compact cat member cards, visible send scope, previous discussion links, shared light/dark themes, and guarded asynchronous submissions. The full flow was exercised with a synthetic source and a fake executor in an isolated browser environment; real model quality and user value remain unvalidated.

Run `python3 scripts/verify_release.py` for isolated source regression. See the [release receipt](docs/receipts/source-preview-v2-20261008.json) for evidence and remaining gaps, and the [Chinese overview](README.md) for screenshots and architecture links.

Original source is MIT licensed. Third-party components retain their licenses. This is an independent personal project, not an official OpenAI or Apple product.
