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

    /// The single in-flight refresh. See `refreshSession()`.
    private var refreshTask: Task<AuthSession, Error>?

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

    /// Start opening a connection to the API before anything needs it.
    ///
    /// Strictly fire-and-forget. An earlier version had `perform` *wait* on
    /// this, on the theory that one handshake beats three concurrent ones. That
    /// was wrong and measurably worse: the probe itself timed out at 6.3s and
    /// every real request queued behind it, pushing first data from ~8s to
    /// ~10s. When the first connection is the thing that's broken, making
    /// everything depend on it is the opposite of a fix.
    public func warmUp() async {
        guard let url = URL(string: baseURL.absoluteString.trimmingTrailingSlash + "/health") else { return }
        var req = URLRequest(url: url)
        req.timeoutInterval = 6
        let started = Date()
        _ = try? await session.data(for: req)
        #if DEBUG
        print("[api] warmUp → \(Int(Date().timeIntervalSince(started) * 1000))ms")
        #endif
    }

    // MARK: Auth

    /// `displayName` and `authorizationCode` are only available on the *first*
    /// authorization for an Apple ID — Apple never sends them again, and neither
    /// appears in the identity token — so they're forwarded when present and the
    /// server keeps them.
    @discardableResult
    public func signInWithApple(
        identityToken: String, displayName: String? = nil, authorizationCode: String? = nil
    ) async throws -> AuthSession {
        struct Body: Encodable {
            let identity_token: String
            let display_name: String?
            let authorization_code: String?
        }
        let session: AuthSession = try await request(
            "/auth/apple", method: "POST",
            body: Body(identity_token: identityToken,
                       display_name: displayName,
                       authorization_code: authorizationCode),
            authed: false)
        store(session)
        return session
    }

    /// Non-interactive re-auth. The Share Extension can never show sign-in UI,
    /// so this is the only way a share made after expiry can still go through.
    ///
    /// **Coalesced.** Refresh tokens rotate on use, so two concurrent refreshes
    /// invalidate each other — and at launch the app fires `/maps`, `/reels` and
    /// `/places` at once, which after the 24h access-token expiry meant three
    /// simultaneous 401s each starting its own refresh. Two of the three lost the
    /// race, and the user watched a spinner for fifteen seconds. Every caller
    /// now awaits the same in-flight task.
    @discardableResult
    public func refreshSession() async throws -> AuthSession {
        if let inFlight = refreshTask { return try await inFlight.value }

        let task = Task<AuthSession, Error> { [self] in try await performRefresh() }
        refreshTask = task
        defer { refreshTask = nil }
        return try await task.value
    }

    private func performRefresh() async throws -> AuthSession {
        guard let refresh = AuthStore.refreshToken else {
            throw APIError(status: 401, message: "Signed out. Please sign in again.")
        }
        struct Body: Encodable { let refresh_token: String }
        let session: AuthSession = try await request(
            "/auth/refresh", method: "POST", body: Body(refresh_token: refresh), authed: false)
        store(session)
        return session
    }

    /// Refresh *before* spending a round trip on a request we know will 401.
    /// The access token is a JWT we can read the expiry out of locally, so an
    /// expired session costs one request instead of one-per-caller plus a retry.
    private func refreshIfExpired() async {
        guard let token = AuthStore.token else { return }
        // A minute of slack: a token that expires mid-flight still 401s, and the
        // retry path below handles it, but this avoids the common near-miss.
        guard let expiry = Self.expiry(of: token),
              expiry.timeIntervalSinceNow < 60 else { return }
        _ = try? await refreshSession()
    }

    /// `exp` out of a JWT payload, without verifying the signature — the server
    /// is the only thing that gets to trust this token; we just want to know
    /// whether it's worth sending.
    private static func expiry(of jwt: String) -> Date? {
        let parts = jwt.split(separator: ".")
        guard parts.count == 3 else { return nil }
        var b64 = String(parts[1])
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        b64 += String(repeating: "=", count: (4 - b64.count % 4) % 4)
        guard let data = Data(base64Encoded: b64),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let exp = json["exp"] as? Double else { return nil }
        return Date(timeIntervalSince1970: exp)
    }

    private func store(_ session: AuthSession) {
        AuthStore.token = session.accessToken
        if let refresh = session.refreshToken { AuthStore.refreshToken = refresh }
    }

    public func signOut() async {
        // Best-effort server-side revocation; the local session goes either way.
        try? await requestVoid("/auth/signout", method: "POST")
        AuthStore.signOut()
    }

    // MARK: Profile

    public func me() async throws -> UserProfile {
        let profile: UserProfile = try await request("/me")
        AuthStore.userID = profile.id
        return profile
    }

    @discardableResult
    public func updateDisplayName(_ name: String) async throws -> UserProfile {
        struct Body: Encodable { let display_name: String }
        return try await request("/me", method: "PATCH", body: Body(display_name: name))
    }

    public func deleteAccount() async throws {
        try await requestVoid("/me", method: "DELETE")
        AuthStore.signOut()
    }

    // MARK: Maps

    public func maps() async throws -> [MapSummary] {
        try await request("/maps")
    }

    public func createMap(name: String, emoji: String?) async throws -> MapSummary {
        struct Body: Encodable { let name: String; let emoji: String? }
        return try await request("/maps", method: "POST", body: Body(name: name, emoji: emoji))
    }

    @discardableResult
    public func renameMap(id: String, name: String) async throws -> MapSummary {
        struct Body: Encodable { let name: String }
        return try await request("/maps/\(id)", method: "PATCH", body: Body(name: name))
    }

    /// Owner deletes the map for everyone; a member just leaves it.
    public func deleteOrLeaveMap(id: String) async throws {
        try await requestVoid("/maps/\(id)", method: "DELETE")
    }

    public func createInvite(mapID: String, rotate: Bool = false) async throws -> MapInvite {
        try await request("/maps/\(mapID)/invite?rotate=\(rotate)", method: "POST")
    }

    /// Unauthenticated on purpose: the join screen shows what you're joining
    /// before asking anyone to sign in.
    public func previewInvite(code: String) async throws -> MapPreview {
        try await request("/maps/preview/\(code)", authed: false)
    }

    @discardableResult
    public func joinMap(code: String) async throws -> MapSummary {
        try await request("/maps/join/\(code)", method: "POST")
    }

    public func members(mapID: String) async throws -> [MapMemberSummary] {
        try await request("/maps/\(mapID)/members")
    }

    public func removeMember(mapID: String, userID: String) async throws {
        try await requestVoid("/maps/\(mapID)/members/\(userID)", method: "DELETE")
    }

    public func registerDevice(apnsToken: String) async throws {
        struct Body: Encodable { let apns_token: String; let platform = "ios" }
        try await requestVoid("/devices", method: "POST", body: Body(apns_token: apnsToken))
    }

    // MARK: Moderation

    /// Report content. Required by App Store Guideline 1.2 for any app with
    /// user-generated content — here that's map names, display names, and the
    /// places someone adds to a shared map.
    public func report(
        _ target: ReportTarget, id: String, reason: ReportReason, note: String? = nil
    ) async throws {
        struct Body: Encodable {
            let target_type: String
            let target_id: String
            let reason: String
            let note: String?
        }
        try await requestVoid("/reports", method: "POST", body: Body(
            target_type: target.rawValue, target_id: id,
            reason: reason.rawValue, note: note))
    }

    public func blockedUsers() async throws -> [BlockedUser] {
        try await request("/blocks")
    }

    /// Hides that person's places and their row in member lists, for you only.
    /// It does not remove them from any map — the owner decides membership.
    @discardableResult
    public func block(userID: String) async throws -> BlockedUser {
        struct Body: Encodable { let user_id: String }
        return try await request("/blocks", method: "POST", body: Body(user_id: userID))
    }

    public func unblock(userID: String) async throws {
        try await requestVoid("/blocks/\(userID)", method: "DELETE")
    }

    // MARK: Reels

    /// `mapID` is where the pins land; nil means the caller's personal map.
    @discardableResult
    public func submitReel(url: String, mapID: String? = nil) async throws -> ReelStatus {
        struct Body: Encodable { let url: String; let map_id: String? }
        return try await request("/reels", method: "POST",
                                 body: Body(url: url, map_id: mapID))
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

    /// Drop the pin by hand for a place the geocoder couldn't resolve.
    @discardableResult
    public func setPlaceLocation(
        id: String, lat: Double, lng: Double, address: String? = nil
    ) async throws -> SavedPlace {
        struct Body: Encodable { let lat: Double; let lng: Double; let address: String? }
        return try await request("/places/\(id)/location", method: "PATCH",
                                body: Body(lat: lat, lng: lng, address: address))
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
        // NOT appendingPathComponent: it treats the whole string as one path
        // component and percent-encodes the "?", so any endpoint with a query
        // string resolved to a literal "…%3Frotate=false" path and 404'd.
        guard let url = URL(string: baseURL.absoluteString.trimmingTrailingSlash + path) else {
            throw APIError(status: -1, message: "Bad request URL.")
        }
        if authed, !isRetry { await refreshIfExpired() }

        var req = URLRequest(url: url)
        req.httpMethod = method
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        // Remembered so a 401 can tell "my token is stale" from "the session is
        // gone" — see below.
        let sentToken: String? = authed ? AuthStore.token : nil
        if let sentToken {
            req.setValue("Bearer \(sentToken)", forHTTPHeaderField: "Authorization")
        }
        // Harmless normally; when API_BASE_URL is an ngrok tunnel it skips the
        // free-tier browser interstitial that would otherwise break API calls.
        req.setValue("true", forHTTPHeaderField: "ngrok-skip-browser-warning")
        let started = Date()
        let data: Data
        let resp: URLResponse
        do {
            #if DEBUG
            (data, resp) = try await session.data(for: req, delegate: Self.metrics)
            // Timing on every call: "the app feels slow" is unfixable without
            // knowing whether it's the network, the server, or our own layout.
            let ms = Int(Date().timeIntervalSince(started) * 1000)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            print("[api] \(method) \(path) → \(code) in \(ms)ms")
            #else
            (data, resp) = try await session.data(for: req)
            #endif
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
        // An expired access token is recoverable without the user: swap the
        // refresh token for a new one and retry once. This is what lets the
        // Share Extension — which can never present sign-in UI — keep working.
        if http.statusCode == 401, authed, !isRetry {
            // Someone else already refreshed while this request was in flight,
            // so the token we sent is stale but the session is fine. Retrying
            // without refreshing is the whole point: a second refresh here would
            // rotate the token out from under every other in-flight request.
            if AuthStore.token != sentToken {
                return try await perform(path, method: method, body: body, authed: authed, isRetry: true)
            }
            if (try? await refreshSession()) != nil {
                return try await perform(path, method: method, body: body, authed: authed, isRetry: true)
            }
            // Refresh itself failed: the session is genuinely gone.
            AuthStore.signOut()
            await MainActor.run { SessionExpiry.notify() }
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

    /// Deliberately excludes `.timedOut`. These are all *fast* failures worth a
    /// second attempt; a timeout has already spent the full 15s budget, and
    /// retrying it turned a slow request into a 30-second one.
    private static func isTransient(_ code: URLError.Code) -> Bool {
        [.networkConnectionLost, .cannotConnectToHost].contains(code)
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

private extension String {
    var trimmingTrailingSlash: String {
        hasSuffix("/") ? String(dropLast()) : self
    }
}

#if DEBUG
extension APIClient {
    static let metrics = NetworkMetrics()
}

/// Per-phase timing straight from URLSession.
///
/// The wall-clock number in `[api]` says a request took four seconds but not
/// *where* they went, and three rounds of reasoning from wall-clock alone
/// produced two wrong diagnoses. This prints the breakdown URLSession already
/// collects, so the next log answers it outright:
///
///   queued  time between the task starting and the connection being attempted
///           (nonzero = URLSession is holding the request, not the network)
///   dns/tcp/tls  the handshake, itemised
///   ttfb    request sent → first response byte = the server's own time
///   reused  whether it went over a pooled connection
final class NetworkMetrics: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    didFinishCollecting metrics: URLSessionTaskMetrics) {
        guard let t = metrics.transactionMetrics.last else { return }
        func ms(_ from: Date?, _ to: Date?) -> String {
            guard let from, let to else { return "   -" }
            return String(format: "%4.0f", to.timeIntervalSince(from) * 1000)
        }
        // Connection setup starts at DNS, or at connect when DNS was cached.
        let setupStart = t.domainLookupStartDate ?? t.connectStartDate ?? t.requestStartDate
        let path = task.originalRequest?.url?.path ?? "?"
        print("[net] \(path) \(t.networkProtocolName ?? "?") reused=\(t.isReusedConnection)"
            + " queued=\(ms(t.fetchStartDate, setupStart))"
            + " dns=\(ms(t.domainLookupStartDate, t.domainLookupEndDate))"
            + " tcp=\(ms(t.connectStartDate, t.connectEndDate))"
            + " tls=\(ms(t.secureConnectionStartDate, t.secureConnectionEndDate))"
            + " ttfb=\(ms(t.requestStartDate, t.responseStartDate))"
            + " total=\(ms(t.fetchStartDate, t.responseEndDate))")
    }
}
#endif

private struct AnyEncodable: Encodable {
    private let encode: (Encoder) throws -> Void
    init(_ wrapped: any Encodable) { encode = wrapped.encode }
    func encode(to encoder: Encoder) throws { try encode(encoder) }
}
