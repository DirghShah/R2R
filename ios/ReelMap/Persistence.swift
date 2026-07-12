import CoreLocation
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
    var lat: Double?
    var lng: Double?
    var address: String?
    var rating: Double?
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
        id: String, name: String, category: String,
        lat: Double?, lng: Double?, address: String?, rating: Double?,
        reelURL: String?, summary: String?,
        tips: [String], whatToOrder: [String], vibe: [String],
        instagramHandle: String?, website: String?, hoursHint: String?,
        priceLevelAI: Int?, city: String?, savedAt: Date
    ) {
        self.id = id; self.name = name; self.category = category
        self.lat = lat; self.lng = lng; self.address = address; self.rating = rating
        self.reelURL = reelURL; self.summary = summary
        self.tips = tips; self.whatToOrder = whatToOrder; self.vibe = vibe
        self.instagramHandle = instagramHandle; self.website = website
        self.hoursHint = hoursHint; self.priceLevelAI = priceLevelAI
        self.city = city; self.savedAt = savedAt
    }

    convenience init(dto: SavedPlace) {
        self.init(
            id: dto.id, name: dto.place.name, category: dto.place.category,
            lat: dto.place.lat, lng: dto.place.lng, address: dto.place.address,
            rating: dto.place.rating, reelURL: dto.reelURL, summary: dto.description,
            tips: dto.tips ?? [], whatToOrder: dto.whatToOrder ?? [], vibe: dto.vibe ?? [],
            instagramHandle: dto.instagramHandle, website: dto.website,
            hoursHint: dto.hoursHint, priceLevelAI: dto.priceLevelAI,
            city: dto.city, savedAt: dto.savedAt
        )
    }

    var categoryEnum: PlaceCategory { PlaceCategory(rawValue: category) ?? .other }

    var coordinate: CLLocationCoordinate2D? {
        guard let lat, let lng else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }

    /// "$", "$$", "$$$", "$$$$" — nil if unknown
    var priceString: String? {
        guard let p = priceLevelAI, (1...4).contains(p) else { return nil }
        return String(repeating: "$", count: p)
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

    static func clear(_ context: ModelContext) {
        lastRefresh = nil
        try? context.delete(model: CachedPlace.self)
        try? context.delete(model: CachedList.self)
        try? context.save()
    }
}
