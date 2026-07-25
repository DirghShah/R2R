import Foundation

public struct APIError: Error, LocalizedError {
    public let status: Int
    public let message: String
    public var errorDescription: String? { message }
    /// True for connectivity failures (no HTTP response reached us), as opposed
    /// to a server-side status code. Lets the Share Extension say "network lost".
    public var isNetwork: Bool { status <= 0 }
}

/// Thin async/await client for the ReelMap backend. Used by both the app and
/// the Share Extension (which only calls `submitReel`).
public actor APIClient {
    public static let shared = APIClient()

    private let baseURL: URL
    private let decoder: JSONDecoder
    private let session: URLSession

    public init(baseURL: URL? = nil) {
        let fromBuild = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String
        self.baseURL = baseURL ?? URL(string: fromBuild ?? "http://localhost:8000")!

        // Fail fast when the backend is unreachable (e.g. Mac asleep / IP changed)
        // so the Share Extension never spins forever — it queues and dismisses.
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 15
        cfg.timeoutIntervalForResource = 20
        cfg.waitsForConnectivity = false
        self.session = URLSession(configuration: cfg)
        let d = JSONDecoder()
        // Backend timestamps come from Python `datetime.now(utc)` and include
        // fractional seconds, which the plain `.iso8601` strategy rejects. Accept
        // ISO8601 with or without fractional seconds.
        d.dateDecodingStrategy = .custom { decoder in
            let raw = try decoder.singleValueContainer().decode(String.self)
            if let date = Self.iso8601Fractional.date(from: raw) { return date }
            if let date = Self.iso8601Plain.date(from: raw) { return date }
            throw DecodingError.dataCorruptedError(
                in: try decoder.singleValueContainer(),
                debugDescription: "Unparseable date: \(raw)")
        }
        self.decoder = d
    }

    private static let iso8601Fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let iso8601Plain = ISO8601DateFormatter()

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

    /// The user's reels, newest-first, with live status (the activity/queue feed).
    public func activity() async throws -> [ReelActivity] {
        try await request("/reels")
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

    /// Remove one saved place. The reel's analysis is kept server-side, so
    /// re-submitting the reel brings the pin back without re-analyzing it.
    public func deletePlace(id: String) async throws {
        try await requestVoid("/places/\(id)", method: "DELETE")
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
        // Harmless normally; when API_BASE_URL is an ngrok tunnel it skips the
        // free-tier browser interstitial that would otherwise break API calls.
        req.setValue("true", forHTTPHeaderField: "ngrok-skip-browser-warning")
        let data: Data
        let resp: URLResponse
        do {
            (data, resp) = try await session.data(for: req)
        } catch let e as URLError {
            // "The network connection was lost" (-1005) & friends are frequently
            // transient against a LAN dev server — retry once, then report honestly.
            if Self.isTransient(e.code), !isRetry {
                try? await Task.sleep(nanoseconds: 500_000_000)
                return try await perform(path, method: method, body: body, authed: authed, isRetry: true)
            }
            throw APIError(status: -1, message: Self.networkMessage(e.code))
        }
        guard let http = resp as? HTTPURLResponse else {
            throw APIError(status: -1, message: "No response from ReelMap.")
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

    private static func isTransient(_ code: URLError.Code) -> Bool {
        [.networkConnectionLost, .timedOut, .cannotConnectToHost].contains(code)
    }

    private static func networkMessage(_ code: URLError.Code) -> String {
        switch code {
        case .notConnectedToInternet: return "You're offline."
        case .networkConnectionLost:  return "Network lost — can't reach the ReelMap backend."
        case .timedOut:               return "ReelMap didn't respond. Is the backend running on the same Wi-Fi?"
        case .cannotConnectToHost, .cannotFindHost:
            return "Can't reach the ReelMap backend at this address."
        default:                      return "Network error — can't reach ReelMap."
        }
    }
}

private struct AnyEncodable: Encodable {
    private let encode: (Encoder) throws -> Void
    init(_ wrapped: any Encodable) { encode = wrapped.encode }
    func encode(to encoder: Encoder) throws { try encode(encoder) }
}
