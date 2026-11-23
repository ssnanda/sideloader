import Foundation

struct ServerState: Decodable {
    let now: Int
    let apps: [ManagedApp]
    let registered: [RegisteredDevice]
    let remoteServer: RemoteServer?

    enum CodingKeys: String, CodingKey {
        case now, apps, registered
        case remoteServer = "remote_server"
    }
}

struct RemoteServer: Decodable {
    let enabled: Bool
    let reachable: Bool?
    let paired: Bool?
    let accountReady: Bool?
    let profiles: [RemoteProfile]?

    enum CodingKeys: String, CodingKey {
        case enabled, reachable, paired, profiles
        case accountReady = "account_ready"
    }
}

struct RemoteProfile: Decodable {
    let bundle: String
    let expires: Int?
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

struct SigningJobStart: Decodable {
    let job: String
}

struct SigningJobResponse: Decodable {
    let job: SigningJob?
}

struct SigningJob: Decodable {
    let id: String
    let kind: String
    let title: String
    let running: Bool
    let rc: Int?
    let stage: String?
    let fraction: Double?
    let needsInput: Bool
    let acceptsInput: Bool
    let verificationDelivery: String?
    let verificationSecondsRemaining: Int?
    let last: String?

    enum CodingKeys: String, CodingKey {
        case id, kind, title, running, rc, stage, fraction, last
        case needsInput = "needs_input"
        case acceptsInput = "accepts_input"
        case verificationDelivery = "verification_delivery"
        case verificationSecondsRemaining = "verification_seconds_remaining"
    }
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
