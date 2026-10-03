# Yanxu · Research Desk

**Continue long-running projects with AI agents, with the original work and sources still in view.**

Yanxu is a local-first desktop workspace for individual research, development, design and writing projects. It brings project goals, tasks, agent actions, deliverables, results and source versions into one place.

![Today view with synthetic demo records](docs/images/today-desktop.png)

## What it offers

- A Today view with the current record, a necessary reminder and one next action.
- Project tasks, dependencies, action lanes, calendar and event history.
- Deliverable references and version-bound results; failures and unknowns remain visible.
- Project-scoped MCP tools for bounded actions and structured handoffs.
- Optional Codex management summaries and human-approved read-only reviews.
- Separate consent for workspace binding, local reading, document text extraction and sending source content.

A completed task is not a verified result. Agent-reported results default to `UNVERIFIED`.

## Try it

Download the beta from [Releases](https://github.com/lingyi-liusd/yanxu/releases). Apple Silicon macOS and Windows x64 packages include runtime dependencies. This release has a passing macOS offline self-check; exact-release native macOS GUI and Windows native execution are `NOT_RUN`. The macOS app uses ad-hoc signing and is not notarized. No Intel Mac, Windows ARM or Linux desktop package is provided.

To run from source (Python 3.13 recommended):

```sh
git clone https://github.com/lingyi-liusd/yanxu.git
cd yanxu
python3 launcher.py
```

Open `http://127.0.0.1:8765`. Basic project work runs without AI. Optional AI features require your own eligible Codex account and explicit consent. Data is kept in the local user-data directory, separate from source.

For an isolated, no-login demo:

```sh
python3 scripts/start_demo.py
```

The script starts a server with a new temporary profile and synthetic records. Stop it with Ctrl-C. It does not read personal files, invoke a model or modify your normal workspace. Screenshots use this same synthetic example.

## Architecture and development

HTML/CSS/JavaScript UI → local Python HTTP API → SQLite, versioned writes and SSE → project-scoped Agent Gateway → Node MCP. Native macOS packaging uses AppKit/WKWebView; Windows uses installation scripts and an Edge app window.

```sh
python3 scripts/verify_release.py
```

Development checks require Python 3.13 and Node 22. They cover synthetic software behavior, not model quality, scientific validity or native-platform acceptance. See [Architecture](docs/ARCHITECTURE.md), [Validation](docs/VALIDATION.md), [Contributing](CONTRIBUTING.md) and [Security](SECURITY.md).

This is a single-user local beta, not a public multi-user server. Workspace path checks are application rules, not an OS sandbox. There is no cross-agent file write lock or promise of uninterrupted unattended operation.

## License

Yanxu source is [MIT licensed](LICENSE). Bundled dependencies and fonts retain their own licenses; see [Third-party notices](THIRD-PARTY-NOTICES.md).
