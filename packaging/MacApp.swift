import AppKit
import WebKit

final class DeskApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var focusWindows: [String: NSWindow] = [:]
    let resources = Bundle.main.resourceURL!
    var ready = false
    var terminating = false
    var keepRunningAfterClose = false
    var lifecycleBusy = true
    var backgroundItem: NSMenuItem!
    let preparationLock = NSLock()
    var preparationProcess: Process?
    var preparationCancelled = false
    var startingServer = false

    func boot(_ arguments: [String], completion: @escaping (Int32, String) -> Void) {
        DispatchQueue.global().async {
            let process = Process()
            process.executableURL = self.resources.appendingPathComponent("runtime/python/bin/python3")
            process.arguments = [self.resources.appendingPathComponent("beta_boot.py").path] + arguments
            process.currentDirectoryURL = self.resources
            var env = ProcessInfo.processInfo.environment
            env["PYTHONUTF8"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            process.environment = env
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe
            do {
                if arguments == ["--background-state"] {
                    self.preparationLock.lock()
                    if self.preparationCancelled {
                        self.preparationLock.unlock()
                        DispatchQueue.main.async { completion(1, "启动准备已取消；未启动服务") }
                        return
                    }
                    do { try process.run() } catch { self.preparationLock.unlock(); throw error }
                    self.preparationProcess = process
                    self.preparationLock.unlock()
                } else {
                    try process.run()
                }
                let output = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                DispatchQueue.main.async { completion(process.terminationStatus, String(data: output, encoding: .utf8) ?? "") }
            } catch {
                DispatchQueue.main.async { completion(1, error.localizedDescription) }
            }
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let item = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "显示研序窗口", action: #selector(showWindow), keyEquivalent: "")
        appMenu.addItem(withTitle: "打开评审专注窗口", action: #selector(showReview), keyEquivalent: "1")
        appMenu.addItem(withTitle: "打开观察专注窗口", action: #selector(showObserve), keyEquivalent: "2")
        appMenu.addItem(withTitle: "登录 Codex（仅测试版）", action: #selector(login), keyEquivalent: "l")
        appMenu.addItem(withTitle: "打开测试版数据文件夹", action: #selector(showData), keyEquivalent: "")
        backgroundItem = appMenu.addItem(withTitle: "关闭窗口后保持 Agent 运行", action: #selector(toggleBackground), keyEquivalent: "")
        backgroundItem.isEnabled = false
        appMenu.autoenablesItems = false
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出研序测试版", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = appMenu
        menu.addItem(item)
        let editItem = NSMenuItem(title: "编辑", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        menu.addItem(editItem)
        NSApplication.shared.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "研序 · 测试版"
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 680, height: 520)
        window.center()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = WKWebsiteDataStore.nonPersistent()
        web = WKWebView(frame: .zero, configuration: config)
        web.uiDelegate = self
        web.navigationDelegate = self
        window.contentView = web
        web.loadHTMLString("<meta charset='utf-8'><body style='font:20px -apple-system;padding:64px;color:#555'>正在打开研序…</body>", baseURL: nil)
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
        boot(["--background-state"]) { status, output in
            if self.terminating {
                NSApplication.shared.reply(toApplicationShouldTerminate: true)
                return
            }
            if status == 0, let bytes = output.data(using: .utf8),
               let setting = try? JSONSerialization.jsonObject(with: bytes) as? [String: Bool] {
                self.keepRunningAfterClose = setting["keep_running_after_window_close"] == true
            } else {
                let alert = NSAlert(); alert.messageText = "后台设置未能读取"
                alert.informativeText = "本次按关闭窗口即退出处理。\n" + output; alert.runModal()
            }
            self.backgroundItem.state = self.keepRunningAfterClose ? .on : .off
            self.lifecycleBusy = false
            self.backgroundItem.isEnabled = !self.terminating
            self.startServer()
        }
    }

    func startServer() {
        startingServer = true
        boot(["--no-open"]) { status, output in
            if status == 0 {
                self.ready = true
                if self.terminating {
                    self.finishTermination()
                } else {
                    self.web.load(URLRequest(url: URL(string: "http://127.0.0.1:18765/")!))
                }
            } else if self.terminating {
                NSApplication.shared.reply(toApplicationShouldTerminate: true)
            } else {
                let alert = NSAlert()
                alert.messageText = "研序未能启动"
                alert.informativeText = output
                alert.runModal()
            }
        }
    }

    @objc func toggleBackground() {
        guard !lifecycleBusy && !terminating else { return }
        let enabled = !keepRunningAfterClose
        if enabled {
            let alert = NSAlert(); alert.messageText = "关闭窗口后继续运行 Agent？"
            alert.informativeText = "仅保持本测试空间已授权的连接和总结，不增加文件权限。定时总结仍可能消耗 Codex 额度。电脑休眠或关机时不保证运行；不是云端常在线，也不设置开机自启。选择“退出研序测试版”或 ⌘Q 会停止服务。"
            alert.addButton(withTitle: "继续在后台运行"); alert.addButton(withTitle: "取消")
            guard alert.runModal() == .alertFirstButtonReturn else { return }
        }
        lifecycleBusy = true; backgroundItem.isEnabled = false
        boot([enabled ? "--background-on" : "--background-off"]) { status, output in
            if status == 0 {
                self.keepRunningAfterClose = enabled
                self.backgroundItem.state = enabled ? .on : .off
                if !enabled && !self.terminating { self.showWindow() }
            } else {
                let alert = NSAlert(); alert.messageText = "后台设置未保存"; alert.informativeText = output; alert.runModal()
            }
            self.lifecycleBusy = false; self.backgroundItem.isEnabled = !self.terminating
        }
    }

    @objc func showWindow() {
        guard !terminating else { return }
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }
    @objc func showReview() { _ = focusWindow(URL(string: "http://127.0.0.1:18765/apps/discussion/")!) }
    @objc func showObserve() { _ = focusWindow(URL(string: "http://127.0.0.1:18765/apps/radar/")!) }
    func focusWindow(_ url: URL, configuration: WKWebViewConfiguration? = nil) -> WKWebView? {
        guard ready && !terminating else { return nil }
        let key = configuration == nil ? url.path : url.path + "#" + UUID().uuidString
        if let existing = focusWindows[key], let child = existing.contentView as? WKWebView {
            if child.url?.absoluteString != url.absoluteString { child.load(URLRequest(url: url)) }
            existing.makeKeyAndOrderFront(nil); return child
        }
        let childWindow = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1160, height: 780),
                                   styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        childWindow.title = url.path.contains("radar") ? "研序 · 观察" : url.path.contains("discussion") ? "研序 · 评审" : "研序 · 项目"
        childWindow.minSize = NSSize(width: 680, height: 520)
        childWindow.isReleasedWhenClosed = false; childWindow.delegate = self
        let config = configuration ?? WKWebViewConfiguration()
        if configuration == nil { config.websiteDataStore = web.configuration.websiteDataStore }
        let child = WKWebView(frame: .zero, configuration: config)
        child.uiDelegate = self; child.navigationDelegate = self
        childWindow.contentView = child; childWindow.center(); childWindow.makeKeyAndOrderFront(nil)
        focusWindows[key] = childWindow
        if configuration == nil { child.load(URLRequest(url: url)) }
        return child
    }
    func windowWillClose(_ notification: Notification) {
        guard let closing = notification.object as? NSWindow, closing !== window else { return }
        if let entry = focusWindows.first(where: { $0.value === closing }) { focusWindows.removeValue(forKey: entry.key) }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if keepRunningAfterClose && !terminating {
            sender.orderOut(nil)
            return false
        }
        return true
    }

    @objc func login() {
        boot(["--login-window"]) { status, output in
            if status != 0 { let alert = NSAlert(); alert.messageText = "登录入口未能打开"; alert.informativeText = output; alert.runModal() }
        }
    }
    @objc func showData() {
        boot(["--show-data"]) { status, output in
            if status != 0 { let alert = NSAlert(); alert.messageText = "数据目录未能打开"; alert.informativeText = output; alert.runModal() }
        }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { return !keepRunningAfterClose }
    func finishTermination() {
        boot(["--stop"]) { status, output in
            if status != 0 { let alert = NSAlert(); alert.messageText = "服务停止需要检查"; alert.informativeText = output; alert.runModal() }
            NSApplication.shared.reply(toApplicationShouldTerminate: status == 0)
            if status != 0 { self.terminating = false; self.backgroundItem.isEnabled = !self.lifecycleBusy }
        }
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if terminating { return .terminateLater }
        terminating = true
        backgroundItem.isEnabled = false
        if !startingServer {
            // This command only reads the native preference. No server/model
            // is started yet, so quitting can cancel this exact owned process.
            preparationLock.lock()
            preparationCancelled = true
            if let process = preparationProcess, process.isRunning { process.terminate() }
            preparationLock.unlock()
            return .terminateLater
        }
        // Startup completion stops its own server before replying, so closing
        // the loading window cannot leave an orphan service or stop another app.
        if ready { finishTermination() }
        return .terminateLater
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" || (url.host == "127.0.0.1" && url.port == 18765) || url.absoluteString.hasPrefix("blob:http://127.0.0.1:18765/") {
            decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow)
        } else {
            if ["http", "https"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String,
                  completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = suggestedFilename
        panel.beginSheetModal(for: NSApplication.shared.keyWindow ?? window) { result in completionHandler(result == .OK ? panel.url : nil) }
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        panel.beginSheetModal(for: webView.window ?? window) { result in completionHandler(result == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url {
            if url.host == "127.0.0.1" && url.port == 18765 {
                return focusWindow(url, configuration: configuration)
            }
            if ["http", "https"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        }
        return nil
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.runModal(); completionHandler()
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message
        alert.addButton(withTitle: "确认"); alert.addButton(withTitle: "取消")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }
}

let app = NSApplication.shared
let delegate = DeskApp()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
