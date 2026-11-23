import Foundation

actor SideLoaderAPI {
    private let decoder = JSONDecoder()
    private let session: URLSession

    init() {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 12
        configuration.timeoutIntervalForResource = 20
        configuration.httpShouldSetCookies = true
        configuration.httpCookieAcceptPolicy = .always
        configuration.httpCookieStorage = .shared
        session = URLSession(configuration: configuration)
    }

    func authentication(server: URL) async throws -> AuthenticationState {
        try await get(server: server, path: "/api/auth")
    }

    func login(server: URL, username: String, password: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["username": username, "password": password])
        _ = try await request(server: server, path: "/api/auth/login", method: "POST", body: body)
    }

    func state(server: URL) async throws -> ServerState {
        try await get(server: server, path: "/api/state")
    }

    private func get<T: Decodable>(server: URL, path: String) async throws -> T {
        let data: Data = try await request(server: server, path: path, method: "GET", body: nil)
        do { return try decoder.decode(T.self, from: data) }
        catch { throw APIError.invalidResponse(error.localizedDescription) }
    }

    private func request(server: URL, path: String, method: String, body: Data?) async throws -> Data {
        guard let url = URL(string: path, relativeTo: server)?.absoluteURL else { throw APIError.invalidServer }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("sideloop", forHTTPHeaderField: "X-Requested-With")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse("No HTTP response") }
        guard 200..<300 ~= http.statusCode else {
            let message = (try? decoder.decode(APIErrorPayload.self, from: data).error) ?? "HTTP \(http.statusCode)"
            throw APIError.server(message)
        }
        return data
    }
}

enum APIError: LocalizedError {
    case invalidServer
    case invalidResponse(String)
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidServer: return "Enter a valid SideLoader server address."
        case .invalidResponse(let message): return "Invalid server response: \(message)"
        case .server(let message): return message
        }
    }
}
