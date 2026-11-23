import SwiftUI

struct RootView: View {
    @EnvironmentObject private var model: CompanionModel

    var body: some View {
        NavigationStack {
            Group {
                if model.isAuthenticated { AppsView() }
                else { LoginView() }
            }
        }
        .task { await model.restore() }
    }
}

private struct LoginView: View {
    @EnvironmentObject private var model: CompanionModel

    var body: some View {
        Form {
            Section("SideLoader server") {
                TextField("http://100.106.150.135:38080", text: $model.serverText)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                TextField("Username", text: $model.username)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                SecureField("Password", text: $model.password)
                Toggle("Save password in Keychain", isOn: $model.rememberPassword)
            }
            if !model.errorMessage.isEmpty {
                Section { Text(model.errorMessage).foregroundStyle(.red) }
            }
            Section {
                Button(model.isLoading ? "Connecting…" : "Connect") { Task { await model.signIn() } }
                    .disabled(model.isLoading || model.serverText.isEmpty || model.username.isEmpty || model.password.isEmpty)
            }
            Section {
                Text("Use the Mac's LAN address on the same network, or its NetBird address when remote. The companion lists apps known to SideLoader; iOS does not let ordinary apps enumerate every installed App Store app.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("SideLoader")
    }
}

private struct AppsView: View {
    @EnvironmentObject private var model: CompanionModel

    var body: some View {
        List {
            if let state = model.state, !state.registered.isEmpty {
                Section {
                    Picker("iPhone", selection: $model.selectedDeviceID) {
                        ForEach(state.registered) { Text($0.name).tag($0.udid) }
                    }
                    if let device = model.selectedDevice {
                        Label(device.live?.reachable == true ? "Reachable" : "Offline or unverified",
                              systemImage: device.live?.reachable == true ? "iphone.radiowaves.left.and.right" : "iphone.slash")
                            .foregroundStyle(device.live?.reachable == true ? .green : .secondary)
                        if model.hasFreshInventory, let checked = model.inventoryCheckedAt {
                            Text("Installed apps verified at \(checked.formatted(date: .omitted, time: .shortened))")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }

            Section {
                if model.visibleApps.isEmpty {
                    ContentUnavailableView(model.remoteMode ? "No remote profiles found" : "No installed apps confirmed",
                                           systemImage: "app.dashed",
                                           description: Text(model.remoteMode ?
                                               "The server has no matching remote provisioning profiles. This does not prove which apps are installed." :
                                               "No SideLoader-managed apps are confirmed installed on this iPhone."))
                } else {
                    ForEach(model.visibleApps, id: \.app.id) { item in
                        AppRow(app: item.app, target: item.target, serverNow: model.state?.now ?? 0,
                               verifiedByScan: model.hasFreshInventory)
                    }
                }
            } header: {
                Text(model.remoteMode ? "Remote profiles · installation unverified" : "Installed apps")
            }

            if model.isStartingSign || model.signingJob != nil || !model.signingMessage.isEmpty {
                Section("App signing") {
                    if !model.signingAppName.isEmpty {
                        Text(model.signingAppName).font(.headline)
                    }
                    if model.isStartingSign {
                        ProgressView("Starting re-signing…")
                    }
                    if let job = model.signingJob {
                        if job.running {
                            Text(job.stage?.capitalized ?? "Connecting to SideLoader")
                                .foregroundStyle(.secondary)
                            if let fraction = job.fraction, fraction > 0 {
                                ProgressView(value: min(1, max(0, fraction)))
                            } else {
                                ProgressView()
                            }
                            if job.needsInput && job.acceptsInput {
                                Text(job.verificationDelivery == "reported_sent"
                                     ? "Apple reported a verification code was sent to trusted devices."
                                     : "SideLoader requested your Apple verification code. Check your trusted devices.")
                                    .font(.footnote)
                                if let seconds = job.verificationSecondsRemaining {
                                    Text("\(seconds) seconds left for this attempt")
                                        .font(.footnote).foregroundStyle(.secondary)
                                }
                                TextField("6-digit verification code", text: $model.verificationCode)
                                    .keyboardType(.numberPad)
                                Button(model.isSubmittingCode ? "Submitting…" : "Submit code") {
                                    Task { await model.submitVerificationCode() }
                                }
                                .disabled(model.isSubmittingCode ||
                                          model.verificationCode.range(of: "^[0-9]{6}$",
                                                                     options: .regularExpression) == nil)
                            }
                        } else {
                            Label(job.rc == 0 ? "Re-signing finished" : "Re-signing failed",
                                  systemImage: job.rc == 0 ? "checkmark.circle" : "exclamationmark.triangle")
                            if let detail = job.last, !detail.isEmpty {
                                Text(detail).font(.footnote).foregroundStyle(.secondary)
                            }
                            Button("Dismiss") { model.dismissSigningResult() }
                        }
                    }
                    if !model.signingMessage.isEmpty {
                        Text(model.signingMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            if !model.inventoryMessage.isEmpty {
                Section { Text(model.inventoryMessage).foregroundStyle(.orange) }
            }
            if !model.errorMessage.isEmpty {
                Section { Text(model.errorMessage).foregroundStyle(.red) }
            }
        }
        .onChange(of: model.selectedDeviceID) { _, _ in
            if !model.isLoading { Task { await model.refresh() } }
        }
        .navigationTitle("Apps")
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button("Disconnect") { model.signOutLocally() }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button { Task { await model.refresh() } } label: {
                    if model.isLoading { ProgressView() } else { Image(systemName: "arrow.clockwise") }
                }
                .disabled(model.isLoading)
            }
        }
        .refreshable { await model.refresh() }
    }
}

private struct AppRow: View {
    @EnvironmentObject private var model: CompanionModel
    let app: ManagedApp
    let target: AppTarget
    let serverNow: Int
    let verifiedByScan: Bool

    private var status: (String, Color, String) {
        if model.remoteMode { return ("Profile only", .orange, "questionmark.circle.fill") }
        if verifiedByScan { return ("Installed", .green, "checkmark.circle.fill") }
        switch target.installation?.state {
        case "installed": return ("Installed", .green, "checkmark.circle.fill")
        case "missing": return ("Missing", .red, "xmark.circle.fill")
        case "offline": return ("Offline · unverified", .secondary, "questionmark.circle")
        default: return ("Unverified", .orange, "questionmark.circle.fill")
        }
    }

    private var expiry: String {
        guard let value = target.signature.expiry else { return "Signing expiry unavailable" }
        let remaining = value - serverNow
        if remaining <= 0 { return "Signing expired" }
        let days = remaining / 86_400
        let hours = (remaining % 86_400) / 3_600
        return days > 0 ? "\(days)d \(hours)h remaining" : "\(max(1, hours))h remaining"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(app.name).font(.headline)
                    Text([app.version, app.bundleID].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Label(status.0, systemImage: status.2).font(.caption).foregroundStyle(status.1)
            }
            HStack(spacing: 10) {
                Text(model.remoteMode ? "Saved signing status · " + expiry : expiry)
                    .font(.subheadline).fontWeight(.semibold)
                Spacer()
                if model.signingAppID == app.id && model.signingIsBusy {
                    ProgressView().controlSize(.small)
                }
                Button("Re-sign") {
                    Task { await model.reSign(app) }
                }
                .buttonStyle(.bordered)
                .disabled(model.signingIsBusy || model.isLoading ||
                          !(model.remoteMode ? model.remoteReady :
                            (model.hasFreshInventory && model.selectedDevice?.live?.reachable == true)))
            }
            if model.remoteMode {
                Button("Reinstall latest") {
                    Task { await model.reinstallLatest(app) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.signingIsBusy || model.isLoading || !model.remoteReady)
            }
        }
        .padding(.vertical, 4)
    }
}
