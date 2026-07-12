import Foundation

public struct APIError: Error, LocalizedError {
    public let status: Int
    public let message: String
    public var errorDescription: String? { message }
}

/// Thin async/await client for the ReelMap backend. Used by both the app and
/// the Share Extension (which only calls `submitReel`).
public actor APIClient {
    public static let shared = APIClient()

    private let baseURL: URL
    private let decoder: JSONDecoder

    public init(baseURL: URL? = nil) {
        let fromBuild = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String
        self.baseURL = baseURL ?? URL(string: fromBuild ?? "http://localhost:8000")!
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        self.decoder = d
    }

    // MARK: Auth

    public func signInWithApple(identityToken: String) async throws -> String {
        struct Body: Encodable { let identity_token: String }
        struct Resp: Decodable { let access_token: String }
        let resp: Resp = try await request("/auth/apple", method: "POST",
                                           body: Body(identity_token: identityToken), authed: false)
        AuthStore.token = resp.access_token
        return resp.access_token
    }

    public func registerDevice(apnsToken: String) async throws {
        struct Body: Encodable { let apns_token: String; let platform = "ios" }
        try await requestVoid("/devices", method: "POST", body: Body(apns_token: apnsToken))
    }

    // MARK: Reels

    @discardableResult
    public func submitReel(url: String) async throws -> ReelStatus {
        struct Body: Encodable { let url: String }
        return try await request("/reels", method: "POST", body: Body(url: url))
    }

    public func reelStatus(_ reelID: String) async throws -> ReelStatus {
        try await request("/reels/\(reelID)")
    }

    // MARK: Data

    public func places(city: String? = nil) async throws -> [SavedPlace] {
        var path = "/places"
        if let city, let q = city.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            path += "?city=\(q)"
        }
        return try await request(path)
    }

    public func lists() async throws -> [PlaceList] {
        try await request("/lists")
    }

    // MARK: Core

    private func request<T: Decodable>(
        _ path: String, method: String = "GET",
        body: (any Encodable)? = nil, authed: Bool = true
    ) async throws -> T {
        let data = try await perform(path, method: method, body: body, authed: authed)
        return try decoder.decode(T.self, from: data)
    }

    private func requestVoid(
        _ path: String, method: String = "GET",
        body: (any Encodable)? = nil, authed: Bool = true
    ) async throws {
        _ = try await perform(path, method: method, body: body, authed: authed)
    }

    private func perform(
        _ path: String, method: String,
        body: (any Encodable)?, authed: Bool, isRetry: Bool = false
    ) async throws -> Data {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = method
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        if authed, let token = AuthStore.token {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else {
            throw APIError(status: -1, message: "No response")
        }
        // Self-heal a stale/expired session (e.g. the DB was reset but the old
        // token is still cached): clear it, re-acquire a session, retry once.
        if http.statusCode == 401, authed, !isRetry {
            AuthStore.token = nil
            #if DEBUG
            if (try? await signInWithApple(identityToken: "dev:me")) != nil {
                return try await perform(path, method: method, body: body, authed: authed, isRetry: true)
            }
            #endif
        }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError(status: http.statusCode, message: Self.friendlyMessage(from: data))
        }
        return data
    }

    /// FastAPI errors arrive as {"detail": "..."} — surface just the detail,
    /// never raw JSON, in user-facing alerts.
    private static func friendlyMessage(from data: Data) -> String {
        struct Envelope: Decodable { let detail: String }
        if let env = try? JSONDecoder().decode(Envelope.self, from: data) {
            return env.detail
        }
        return "Something went wrong. Please try again."
    }
}

private struct AnyEncodable: Encodable {
    private let encode: (Encoder) throws -> Void
    init(_ wrapped: any Encodable) { encode = wrapped.encode }
    func encode(to encoder: Encoder) throws { try encode(encoder) }
}
