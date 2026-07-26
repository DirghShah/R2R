import CoreLocation
import Foundation
import SharedKit
import SwiftData

/// SwiftData offline cache. The backend stays the source of truth; these models
/// mirror what the UI needs so the map and lists render instantly (and offline),
/// then a background refresh updates them.

@Model
final class CachedPlace {
    @Attribute(.unique) var id: String
    var name: String
    var category: String
    var cuisine: String?
    var lat: Double?
    var lng: Double?
    var address: String?
    var region: String?
    var rating: Double?
    var reviewCount: Int?
    var priceLevel: Int?
    var phone: String?
    var businessStatus: String?
    var googleMapsURL: String?
    var locationSource: String?
    var photos: [String] = []     // default keeps SwiftData lightweight-migration happy
    var hoursData: Data?          // JSON-encoded OpeningHours (SwiftData-safe)
    var utcOffsetMinutes: Int?
    var reelURL: String?
    var summary: String?
    var tips: [String]
    var whatToOrder: [String]
    var vibe: [String]
    var instagramHandle: String?
    var website: String?
    var hoursHint: String?
    var priceLevelAI: Int?
    var city: String?
    var savedAt: Date

    init(
        id: String, name: String, category: String, cuisine: String? = nil,
        lat: Double?, lng: Double?, address: String?, region: String? = nil, rating: Double?,
        reviewCount: Int? = nil, priceLevel: Int? = nil, phone: String? = nil,
        businessStatus: String? = nil, googleMapsURL: String? = nil,
        locationSource: String? = nil, photos: [String] = [], hoursData: Data? = nil, utcOffsetMinutes: Int? = nil,
        reelURL: String?, summary: String?,
        tips: [String], whatToOrder: [String], vibe: [String],
        instagramHandle: String?, website: String?, hoursHint: String?,
        priceLevelAI: Int?, city: String?, savedAt: Date
    ) {
        self.id = id; self.name = name; self.category = category; self.cuisine = cuisine
        self.lat = lat; self.lng = lng; self.address = address; self.region = region
        self.rating = rating
        self.reviewCount = reviewCount; self.priceLevel = priceLevel; self.phone = phone
        self.businessStatus = businessStatus; self.googleMapsURL = googleMapsURL
        self.locationSource = locationSource
        self.photos = photos; self.hoursData = hoursData; self.utcOffsetMinutes = utcOffsetMinutes
        self.reelURL = reelURL; self.summary = summary
        self.tips = tips; self.whatToOrder = whatToOrder; self.vibe = vibe
        self.instagramHandle = instagramHandle; self.website = website
        self.hoursHint = hoursHint; self.priceLevelAI = priceLevelAI
        self.city = city; self.savedAt = savedAt
    }

    convenience init(dto: SavedPlace) {
        self.init(
            id: dto.id, name: dto.place.name, category: dto.place.category,
            cuisine: dto.place.cuisine,
            lat: dto.place.lat, lng: dto.place.lng, address: dto.place.address,
            region: dto.place.region,
            rating: dto.place.rating, reviewCount: dto.place.reviewCount,
            priceLevel: dto.place.priceLevel, phone: dto.place.phone,
            businessStatus: dto.place.businessStatus, googleMapsURL: dto.place.googleMapsURL,
            locationSource: dto.place.locationSource,
            photos: dto.place.photos ?? [],
            hoursData: dto.place.hours.flatMap { try? JSONEncoder().encode($0) },
            utcOffsetMinutes: dto.place.utcOffsetMinutes,
            reelURL: dto.reelURL, summary: dto.description,
            tips: dto.tips ?? [], whatToOrder: dto.whatToOrder ?? [], vibe: dto.vibe ?? [],
            instagramHandle: dto.instagramHandle, website: dto.website,
            hoursHint: dto.hoursHint, priceLevelAI: dto.priceLevelAI,
            city: dto.city, savedAt: dto.savedAt
        )
    }

    var categoryEnum: PlaceCategory { PlaceCategory(rawValue: category) ?? .other }

    /// "Dallas, TX" — the state comes from the geocoder, falling back to a parse
    /// of the stored address so places saved before the backend tracked regions
    /// still label correctly. nil when we don't even know the city.
    var cityLabel: String? {
        guard let city = city?.trimmingCharacters(in: .whitespaces), !city.isEmpty else { return nil }
        // Skip only when the city already *is* the code or already carries it —
        // a substring test would eat legitimate pairs like "Ontario, ON".
        guard let code = regionCode,
              city.caseInsensitiveCompare(code) != .orderedSame,
              !city.lowercased().hasSuffix(", \(code.lowercased())")
        else { return city }
        return "\(city), \(code)"
    }

    var regionCode: String? {
        if let r = region?.trimmingCharacters(in: .whitespaces), !r.isEmpty { return r }
        return Self.regionFromAddress(address)
    }

    /// "133 Duane St, New York, NY 10013, USA" -> "NY". Returns nil unless the
    /// component reads like a short state code, so verbose international
    /// addresses never produce a wrong label.
    static func regionFromAddress(_ address: String?) -> String? {
        guard let address else { return nil }
        var parts = address.split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        let countries: Set<String> = ["USA", "US", "UNITED STATES", "CANADA", "CA"]
        if parts.count > 1, countries.contains(parts[parts.count - 1].replacingOccurrences(of: ".", with: "").uppercased()) {
            parts.removeLast()
        }
        guard let last = parts.last,
              let token = last.split(separator: " ").first.map(String.init),
              (2...3).contains(token.count),
              token.allSatisfy({ $0.isLetter && $0.isUppercase })
        else { return nil }
        return token
    }

    var coordinate: CLLocationCoordinate2D? {
        guard let lat, let lng else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }

    /// Geocoding returns no coordinates rather than risk a wrong pin, so a saved
    /// place can legitimately have no map location until someone sets one.
    var isUnmapped: Bool { coordinate == nil }

    /// Someone dropped this pin by hand rather than the geocoder finding it.
    var isUserPlaced: Bool { locationSource == "user" }

    /// "$", "$$", "$$$", "$$$$" — nil if unknown. Prefer Google's verified price
    /// level; fall back to the AI's guess.
    var priceString: String? {
        guard let p = priceLevel ?? priceLevelAI, (1...4).contains(p) else { return nil }
        return String(repeating: "$", count: p)
    }

    var isPermanentlyClosed: Bool { businessStatus == "CLOSED_PERMANENTLY" }

    var hours: OpeningHours? {
        hoursData.flatMap { try? JSONDecoder().decode(OpeningHours.self, from: $0) }
    }

    /// First Google photo, if any.
    var firstPhotoURL: URL? { photos.first.flatMap { URL(string: $0) } }

    func distanceMeters(from user: CLLocation?) -> Double? {
        guard let user, let c = coordinate else { return nil }
        return CLLocation(latitude: c.latitude, longitude: c.longitude).distance(from: user)
    }

    /// Live open/closed, evaluated in the venue's own timezone via its UTC offset.
    /// nil when we don't have structured hours (e.g. Nominatim-only places).
    var openStatus: (open: Bool, label: String)? {
        guard let periods = hours?.periods, !periods.isEmpty, let offset = utcOffsetMinutes
        else { return nil }
        // "Now" at the venue: shift UTC by the venue's offset, then read wall clock.
        let venueNow = Date().addingTimeInterval(Double(offset) * 60)
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let c = cal.dateComponents([.weekday, .hour, .minute], from: venueNow)
        let gDay = ((c.weekday ?? 1) - 1)  // Swift 1=Sun → Google 0=Sun
        let nowMin = gDay * 1440 + (c.hour ?? 0) * 60 + (c.minute ?? 0)

        for p in periods {
            guard let o = p.open else { continue }
            let openMin = o.day * 1440 + o.hour * 60 + o.minute
            guard let cl = p.close else { return (true, "Open 24 hours") }
            var closeMin = cl.day * 1440 + cl.hour * 60 + cl.minute
            if closeMin <= openMin { closeMin += 7 * 1440 }  // spans midnight/week end
            for shifted in [nowMin, nowMin + 7 * 1440] where shifted >= openMin && shifted < closeMin {
                return (true, "Open · closes \(Self.clockLabel(closeMin % (7 * 1440)))")
            }
        }
        // Closed → soonest upcoming opening.
        var next: Int?
        for p in periods {
            guard let o = p.open else { continue }
            let base = o.day * 1440 + o.hour * 60 + o.minute
            for s in [base, base + 7 * 1440] where s >= nowMin {
                next = min(next ?? .max, s)
            }
        }
        if let n = next { return (false, "Closed · opens \(Self.clockLabel(n % (7 * 1440)))") }
        return (false, "Closed")
    }

    private static func clockLabel(_ minuteOfWeek: Int) -> String {
        let m = minuteOfWeek % 1440
        var h = m / 60
        let mm = m % 60
        let ap = h < 12 ? "AM" : "PM"
        h %= 12; if h == 0 { h = 12 }
        return mm == 0 ? "\(h) \(ap)" : String(format: "%d:%02d %@", h, mm, ap)
    }
}

/// Local-only per-place state (visited toggle + personal note). Kept in its own
/// model so `Syncer`'s delete-and-replace of CachedPlace never wipes it.
@Model
final class PlaceMark {
    @Attribute(.unique) var placeID: String
    var visited: Bool
    var note: String
    var updatedAt: Date

    init(placeID: String, visited: Bool = false, note: String = "", updatedAt: Date = .now) {
        self.placeID = placeID
        self.visited = visited
        self.note = note
        self.updatedAt = updatedAt
    }
}

@Model
final class CachedList {
    @Attribute(.unique) var id: String
    var title: String
    var category: String?
    var city: String?
    var placeCount: Int

    init(id: String, title: String, category: String?, city: String?, placeCount: Int) {
        self.id = id; self.title = title; self.category = category
        self.city = city; self.placeCount = placeCount
    }

    convenience init(dto: PlaceList) {
        self.init(id: dto.id, title: dto.title, category: dto.category,
                  city: dto.city, placeCount: dto.placeCount)
    }
}

/// Pulls from the API and replaces the local cache. On network failure it leaves
/// the existing cache intact (that's the offline path).
///
/// Throttled + single-flight so switching between the Map and Lists tabs doesn't
/// re-fetch and rewrite SwiftData on every appearance (that thrash caused jank).
/// Pass `force: true` for pull-to-refresh and right after analyzing a reel.
@MainActor
enum Syncer {
    private static var lastRefresh: Date?
    private static var isRefreshing = false

    static func refresh(_ context: ModelContext, force: Bool = false) async {
        if isRefreshing { return }
        if !force, let last = lastRefresh, Date().timeIntervalSince(last) < 20 { return }
        isRefreshing = true
        defer { isRefreshing = false }

        guard let places = try? await APIClient.shared.places() else { return }
        let lists = (try? await APIClient.shared.lists()) ?? []

        try? context.delete(model: CachedPlace.self)
        try? context.delete(model: CachedList.self)
        for p in places { context.insert(CachedPlace(dto: p)) }
        for l in lists { context.insert(CachedList(dto: l)) }
        try? context.save()
        lastRefresh = Date()
    }

    /// Remove a saved place everywhere: server first, then the local cache and
    /// its personal mark. Server-first matters — a failed call must not make the
    /// pin vanish locally only to reappear on the next sync.
    static func delete(placeID: String, _ context: ModelContext) async throws {
        try await APIClient.shared.deletePlace(id: placeID)
        purge(placeID: placeID, context)
    }

    static func purge(placeID: String, _ context: ModelContext) {
        let places = FetchDescriptor<CachedPlace>(predicate: #Predicate { $0.id == placeID })
        for p in (try? context.fetch(places)) ?? [] { context.delete(p) }
        let marks = FetchDescriptor<PlaceMark>(predicate: #Predicate { $0.placeID == placeID })
        for m in (try? context.fetch(marks)) ?? [] { context.delete(m) }
        try? context.save()
    }

    static func clear(_ context: ModelContext) {
        lastRefresh = nil
        try? context.delete(model: CachedPlace.self)
        try? context.delete(model: CachedList.self)
        try? context.save()
    }
}
