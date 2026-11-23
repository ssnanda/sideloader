import Foundation

@MainActor
final class CompanionModel: ObservableObject {
    @Published var serverText: String
    @Published var username: String
    @Published var password = ""
    @Published var rememberPassword = true
    @Published var state: ServerState?
    @Published var selectedDeviceID = ""
    @Published var isLoading = false
    @Published var errorMessage = ""
    @Published var isAuthenticated = false
    @Published var inventoryDeviceID = ""
    @Published var installedBundles: Set<String>?
    @Published var inventoryCheckedAt: Date?
    @Published var inventoryMessage = ""

    private let api = SideLoaderAPI()
    private let defaults = UserDefaults.standard

    init() {
        serverText = UserDefaults.standard.string(forKey: "serverURL") ?? "http://100.106.150.135:38080"
        username = UserDefaults.standard.string(forKey: "username") ?? ""
        password = KeychainStore.password()
        rememberPassword = !password.isEmpty
    }

    var selectedDevice: RegisteredDevice? {
        state?.registered.first(where: { $0.udid == selectedDeviceID }) ?? state?.registered.first
    }

    var visibleApps: [(app: ManagedApp, target: AppTarget)] {
        guard let device = selectedDevice else { return [] }
        let assigned = (state?.apps ?? []).compactMap { app in
            app.targets.first(where: { $0.udid.caseInsensitiveCompare(device.udid) == .orderedSame }).map { (app, $0) }
        }
        let onDevice = inventoryDeviceID.caseInsensitiveCompare(device.udid) == .orderedSame
        return assigned.filter { app, target in
            if onDevice, let installedBundles {
                return installedBundles.contains { installed in
                    Self.bundleMatches(installed, source: app.bundleID)
                }
            }
            return target.installation?.state == "installed"
        }.sorted { $0.app.name.localizedCaseInsensitiveCompare($1.app.name) == .orderedAscending }
    }

    private static func bundleMatches(_ installed: String, source: String) -> Bool {
        if installed == source { return true }
        let prefix = source + "."
        guard installed.hasPrefix(prefix) else { return false }
        let suffix = String(installed.dropFirst(prefix.count))
        return suffix.utf8.count == 10 && suffix.utf8.allSatisfy {
            (48...57).contains($0) || (65...90).contains($0)
        }
    }

    var hasFreshInventory: Bool {
        inventoryDeviceID.caseInsensitiveCompare(selectedDeviceID) == .orderedSame && installedBundles != nil
    }

    func restore() async {
        guard !serverText.isEmpty else { return }
        await perform {
            let server = try self.serverURL()
            let auth = try await self.api.authentication(server: server)
            self.username = self.username.isEmpty ? auth.username : self.username
            if auth.loggedIn {
                self.isAuthenticated = true
                try await self.loadState(server: server)
                await self.loadInventory(server: server)
            } else if !self.username.isEmpty && !self.password.isEmpty {
                try await self.authenticate(server: server)
            }
        }
    }

    func signIn() async {
        await perform {
            let server = try self.serverURL()
            try await self.authenticate(server: server)
        }
    }

    func refresh() async {
        await perform {
            let server = try self.serverURL()
            try await self.loadState(server: server)
            await self.loadInventory(server: server)
        }
    }

    func signOutLocally() {
        isAuthenticated = false
        state = nil
        installedBundles = nil
        inventoryDeviceID = ""
        inventoryCheckedAt = nil
        inventoryMessage = ""
        password = ""
        KeychainStore.removePassword()
    }

    private func authenticate(server: URL) async throws {
        try await api.login(server: server, username: username, password: password)
        defaults.set(server.absoluteString, forKey: "serverURL")
        defaults.set(username, forKey: "username")
        if rememberPassword { try KeychainStore.savePassword(password) }
        else { KeychainStore.removePassword() }
        isAuthenticated = true
        try await loadState(server: server)
        await loadInventory(server: server)
    }

    private func loadState(server: URL) async throws {
        let loaded = try await api.state(server: server)
        state = loaded
        if selectedDeviceID.isEmpty || !loaded.registered.contains(where: { $0.udid == selectedDeviceID }) {
            selectedDeviceID = loaded.registered.first?.udid ?? ""
        }
    }

    private func loadInventory(server: URL) async {
        guard let device = selectedDevice else {
            installedBundles = nil
            inventoryDeviceID = ""
            inventoryCheckedAt = nil
            inventoryMessage = ""
            return
        }
        if inventoryDeviceID.caseInsensitiveCompare(device.udid) != .orderedSame {
            installedBundles = nil
            inventoryDeviceID = device.udid
            inventoryCheckedAt = nil
        }
        do {
            let rows = try await api.installedApps(server: server, device: device.udid)
            installedBundles = Set(rows.map(\.bundleID))
            inventoryCheckedAt = Date()
            inventoryMessage = ""
        } catch {
            inventoryMessage = "iPhone scan unavailable: \(error.localizedDescription). Showing last verified status."
        }
    }

    private func serverURL() throws -> URL {
        let trimmed = serverText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var components = URLComponents(string: trimmed),
              ["http", "https"].contains(components.scheme?.lowercased()),
              components.host != nil else { throw APIError.invalidServer }
        components.path = ""
        components.query = nil
        components.fragment = nil
        guard let url = components.url else { throw APIError.invalidServer }
        return url
    }

    private func perform(_ operation: @escaping () async throws -> Void) async {
        guard !isLoading else { return }
        isLoading = true
        errorMessage = ""
        do { try await operation() }
        catch {
            if case APIError.server(let message) = error, message == "sign in first" { isAuthenticated = false }
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}
