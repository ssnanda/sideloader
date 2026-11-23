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
                    }
                }
            }

            Section("Managed apps") {
                if model.visibleApps.isEmpty {
                    ContentUnavailableView("No managed apps", systemImage: "app.dashed",
                                           description: Text("No SideLoader app is assigned to this iPhone."))
                } else {
                    ForEach(model.visibleApps, id: \.app.id) { item in
                        AppRow(app: item.app, target: item.target, serverNow: model.state?.now ?? 0)
                    }
                }
            }

            if !model.errorMessage.isEmpty {
                Section { Text(model.errorMessage).foregroundStyle(.red) }
            }
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
    let app: ManagedApp
    let target: AppTarget
    let serverNow: Int

    private var status: (String, Color, String) {
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
            Text(expiry).font(.subheadline).fontWeight(.semibold)
        }
        .padding(.vertical, 4)
    }
}
