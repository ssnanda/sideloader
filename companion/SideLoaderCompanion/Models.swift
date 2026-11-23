import Foundation

struct ServerState: Decodable {
    let now: Int
    let apps: [ManagedApp]
    let registered: [RegisteredDevice]
}

struct RegisteredDevice: Decodable, Identifiable, Hashable {
    var id: String { udid }
    let udid: String
    let name: String
    let live: LiveDevice?
}

struct LiveDevice: Decodable, Hashable {
    let reachable: Bool?
}

struct ManagedApp: Decodable, Identifiable {
    let id: String
    let bundleID: String
    let name: String
    let version: String
    let targets: [AppTarget]

    enum CodingKeys: String, CodingKey {
        case id, name, version, targets
        case bundleID = "bundle_id"
    }
}

struct AppTarget: Decodable {
    let udid: String
    let name: String
    let signature: SignatureState
    let installation: InstallationState?
}

struct SignatureState: Decodable {
    let expiry: Int?
    let lastRun: LastRun?

    enum CodingKeys: String, CodingKey {
        case expiry
        case lastRun = "last_run"
    }
}

struct LastRun: Decodable {
    let t: Int
    let result: String
    let message: String
}

struct InstallationState: Decodable {
    let state: String
    let reason: String?
}

struct DeviceInventory: Decodable {
    let apps: [PhoneApp]
}

struct PhoneApp: Decodable {
    let bundleID: String

    enum CodingKeys: String, CodingKey {
        case bundleID = "bundle_id"
    }
}

struct APIErrorPayload: Decodable {
    let error: String
}

struct AuthenticationState: Decodable {
    let hasPassword: Bool
    let username: String
    let loggedIn: Bool

    enum CodingKeys: String, CodingKey {
        case username
        case hasPassword = "has_password"
        case loggedIn = "logged_in"
    }
}
