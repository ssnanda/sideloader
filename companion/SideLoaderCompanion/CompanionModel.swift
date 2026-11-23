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
    @Published var signingJob: SigningJob?
    @Published var signingAppID = ""
    @Published var signingAppName = ""
    @Published var signingMessage = ""
    @Published var verificationCode = ""
    @Published var isStartingSign = false
    @Published var isSubmittingCode = false

    private var signingMonitorTask: Task<Void, Never>?
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
        let assigned: [(app: ManagedApp, target: AppTarget)] = (state?.apps ?? []).compactMap { app in
            app.targets.first(where: { $0.udid.caseInsensitiveCompare(device.udid) == .orderedSame }).map { (app, $0) }
        }
        if state?.remoteServer?.enabled == true {
            let profiles = state?.remoteServer?.profiles ?? []
            return assigned.filter { entry in
                profiles.contains { Self.bundleMatches($0.bundle, source: entry.app.bundleID) }
            }.sorted { $0.app.name.localizedCaseInsensitiveCompare($1.app.name) == .orderedAscending }
        }
        let onDevice = inventoryDeviceID.caseInsensitiveCompare(device.udid) == .orderedSame
        return assigned.filter { entry in
            if onDevice, let installedBundles {
                return installedBundles.contains { installed in
                    Self.bundleMatches(installed, source: entry.0.bundleID)
                }
            }
            return entry.1.installation?.state == "installed"
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

    var remoteMode: Bool { state?.remoteServer?.enabled == true }

    var remoteReady: Bool {
        remoteMode && state?.remoteServer?.paired == true &&
        state?.remoteServer?.reachable == true && state?.remoteServer?.accountReady == true
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

    var signingIsBusy: Bool {
        isStartingSign || signingJob?.running == true
    }

    func reSign(_ app: ManagedApp) async {
        guard !isLoading && !signingIsBusy else { return }
        guard let device = selectedDevice,
              visibleApps.contains(where: { $0.app.id == app.id }),
              (remoteReady || (device.live?.reachable == true && hasFreshInventory)) else {
            signingMessage = remoteMode ?
                "Remote pairing or Apple account unavailable. Confirm the iPhone is on Wi-Fi and NetBird." :
                "Scan a reachable iPhone before re-signing. Only installed apps can be re-signed."
            return
        }
        isStartingSign = true
        signingMessage = ""
        do {
            let server = try serverURL()
            let started = try await api.reSign(server: server, device: device.udid, app: app.id)
            signingAppID = app.id
            signingAppName = app.name
            signingJob = nil
            signingMessage = "SideLoader started signing this app."
            signingMonitorTask?.cancel()
            signingMonitorTask = Task { await self.watchSigningJob(id: started.job, server: server) }
        } catch {
            signingMessage = "Could not start re-signing: \(error.localizedDescription)"
        }
        isStartingSign = false
    }

    func reinstallLatest(_ app: ManagedApp) async {
        guard !isLoading && !signingIsBusy else { return }
        guard remoteReady, let device = selectedDevice,
              visibleApps.contains(where: { $0.app.id == app.id }) else {
            signingMessage = "Remote pairing is unavailable or this app has no matching provisioning profile."
            return
        }
        isStartingSign = true
        signingMessage = ""
        do {
            let server = try serverURL()
            let started = try await api.reinstallLatest(server: server, device: device.udid, app: app.id)
            signingAppID = app.id
            signingAppName = app.name
            signingJob = nil
            signingMessage = "Downloading the latest saved-source IPA for remote installation."
            signingMonitorTask?.cancel()
            signingMonitorTask = Task { await self.watchSigningJob(id: started.job, server: server) }
        } catch {
            signingMessage = "Could not start remote reinstall: \(error.localizedDescription)"
        }
        isStartingSign = false
    }

    private func watchSigningJob(id: String, server: URL) async {
        var failedChecks = 0
        while !Task.isCancelled {
            do {
                guard let job = try await api.currentJob(server: server), job.id == id else {
                    signingMessage = "This signing job is no longer available. Check Activity in the Docker dashboard."
                    return
                }
                signingJob = job
                failedChecks = 0
                if !job.running {
                    signingMessage = job.rc == 0 ?
                        "SideLoader completed the operation. Refreshing status." :
                        "SideLoader operation failed. Check Docker Activity."
                    if !isLoading { await refresh() }
                    if job.rc == 0 { signingMessage = "Operation completed." }
                    return
                }
            } catch {
                failedChecks += 1
                if failedChecks >= 5 {
                    signingMessage = "Cannot track the job. It may still be running on Docker; check Activity."
                    return
                }
            }
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
    }

    func submitVerificationCode() async {
        guard !isSubmittingCode,
              verificationCode.range(of: "^[0-9]{6}$", options: .regularExpression) != nil,
              let job = signingJob, job.running, job.needsInput, job.acceptsInput else { return }
        isSubmittingCode = true
        defer { isSubmittingCode = false }
        do {
            let server = try serverURL()
            guard let current = try await api.currentJob(server: server),
                  current.id == job.id, current.running,
                  current.needsInput, current.acceptsInput else {
                signingMessage = "The verification request is no longer active. Refresh the job status."
                return
            }
            try await api.sendVerificationCode(server: server, code: verificationCode)
            verificationCode = ""
            signingMessage = "Code submitted to SideLoader. Waiting for Apple's response."
        } catch {
            signingMessage = "Code submission failed: \(error.localizedDescription)"
        }
    }

    func dismissSigningResult() {
        guard signingJob?.running != true else { return }
        signingMonitorTask?.cancel()
        signingMonitorTask = nil
        signingJob = nil
        signingAppID = ""
        signingAppName = ""
        signingMessage = ""
        verificationCode = ""
    }

    func signOutLocally() {
        signingMonitorTask?.cancel()
        signingMonitorTask = nil
        signingJob = nil
        signingAppID = ""
        signingAppName = ""
        signingMessage = ""
        verificationCode = ""
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
        if remoteMode {
            installedBundles = nil
            inventoryDeviceID = ""
            inventoryCheckedAt = nil
            inventoryMessage = "Remote profiles do not verify whether an app remains installed."
            return
        }
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
