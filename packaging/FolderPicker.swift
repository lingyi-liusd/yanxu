import AppKit
import Foundation

// Finish launching before opening a modal: Launch Services and accessibility
// must see a ready application, not wait behind its first modal run loop.
final class FolderPicker: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        DispatchQueue.main.async { self.choose() }
    }
    func choose() {
        NSApplication.shared.activate(ignoringOtherApps: true)
        let panel = NSOpenPanel()
        panel.title = "研序 · 选择项目资料目录 / Choose project folder"
        panel.message = "这里只选择位置，读取和发送权限将在研序内另行确认。"
        panel.prompt = "选择 / Choose"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = false
        let result: [String: Any]
        if panel.runModal() == .OK, let url = panel.url {
            result = ["path": url.path, "cancelled": false]
        } else {
            result = ["cancelled": true]
        }
        if let data = try? JSONSerialization.data(withJSONObject: result),
           let text = String(data: data, encoding: .utf8) { print(text); fflush(stdout) }
        NSApplication.shared.terminate(nil)
    }
}
let app = NSApplication.shared
let picker = FolderPicker()
app.delegate = picker
app.setActivationPolicy(.accessory)
app.run()
