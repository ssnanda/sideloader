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
        return (state?.apps ?? []).compactMap { app in
            app.targets.first(where: { $0.udid.caseInsensitiveCompare(device.udid) == .orderedSame }).map { (app, $0) }
        }.sorted { $0.app.name.localizedCaseInsensitiveCompare($1.app.name) == .orderedAscending }
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
            try await self.loadState(server: self.serverURL())
        }
    }

    func signOutLocally() {
        isAuthenticated = false
        state = nil
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
    }

    private func loadState(server: URL) async throws {
        let loaded = try await api.state(server: server)
        state = loaded
        if selectedDeviceID.isEmpty || !loaded.registered.contains(where: { $0.udid == selectedDeviceID }) {
            selectedDeviceID = loaded.registered.first?.udid ?? ""
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
