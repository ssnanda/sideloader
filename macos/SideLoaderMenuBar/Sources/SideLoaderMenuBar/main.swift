import AppKit
import SwiftUI

@MainActor
final class SideLoaderStatus: ObservableObject {
    enum ServiceState { case checking, online, offline }

    @Published var state: ServiceState = .checking
    @Published var checkedAt: Date?
    private var timer: Timer?
    private let baseURL = URL(string: "http://localhost:38080")!

    var label: String {
        switch state {
        case .checking: return "Checking SideLoader…"
        case .online: return "SideLoader is running"
        case .offline: return "SideLoader is offline"
        }
    }

    var symbol: String {
        switch state {
        case .checking: return "arrow.triangle.2.circlepath"
        case .online: return "iphone.and.arrow.forward"
        case .offline: return "iphone.slash"
        }
    }

    init() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }

    func refresh() {
        state = .checking
        Task {
            do {
                let url = baseURL.appending(path: "api/health")
                var request = URLRequest(url: url)
                request.timeoutInterval = 4
                let (_, response) = try await URLSession.shared.data(for: request)
                state = (response as? HTTPURLResponse)?.statusCode == 200 ? .online : .offline
            } catch {
                state = .offline
            }
            checkedAt = Date()
        }
    }

    func open(_ path: String) {
        guard let url = URL(string: path, relativeTo: baseURL) else { return }
        NSWorkspace.shared.open(url)
    }
}

@main
struct SideLoaderMenuBarApp: App {
    @StateObject private var status = SideLoaderStatus()

    var body: some Scene {
        MenuBarExtra {
            Label(status.label, systemImage: status.symbol)
            if let checked = status.checkedAt {
                Text("Checked \(checked.formatted(date: .omitted, time: .shortened))")
            }
            Divider()
            Button("Open Apps") { status.open("/#apps") }
            Button("Open Activity") { status.open("/#apps") }
            Button("Sources") { status.open("/sources") }
            Button("Roadmap") { status.open("/roadmap") }
            Divider()
            Button("Check Now") { status.refresh() }
            Button("Quit SideLoader Menu") { NSApplication.shared.terminate(nil) }
        } label: {
            Label("SideLoader", systemImage: status.symbol)
        }
        .menuBarExtraStyle(.menu)
    }
}
