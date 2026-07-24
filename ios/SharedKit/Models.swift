import Foundation

/// Codable mirrors of the backend JSON, shared by the app and the Share Extension.

public enum PlaceCategory: String, Codable, CaseIterable, Sendable {
    case cafe, restaurant, hotel, bar, club, sight, event, other

    public var symbol: String {
        switch self {
        case .cafe: return "cup.and.saucer.fill"
        case .restaurant: return "fork.knife"
        case .hotel: return "bed.double.fill"
        case .bar: return "wineglass.fill"
        case .club: return "music.note"
        case .sight: return "binoculars.fill"
        case .event: return "ticket.fill"
        case .other: return "mappin"
        }
    }
}

/// Google-shaped opening hours (from the Places API `regularOpeningHours`).
public struct OpeningHours: Codable, Hashable, Sendable {
    public struct Point: Codable, Hashable, Sendable {
        public let day: Int      // 0 = Sunday … 6 = Saturday
        public let hour: Int
        public let minute: Int
    }
    public struct Period: Codable, Hashable, Sendable {
        public let open: Point?
        public let close: Point?
    }
    public let periods: [Period]?
    public let weekdayDescriptions: [String]?
}

public struct Place: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String
    public let category: String
    public let cuisine: String?
    public let lat: Double?
    public let lng: Double?
    public let address: String?
    public let rating: Double?
    public let reviewCount: Int?
    public let priceLevel: Int?
    public let photos: [String]?
    public let hours: OpeningHours?
    public let utcOffsetMinutes: Int?
    public let phone: String?
    public let businessStatus: String?
    public let googleMapsURL: String?

    enum CodingKeys: String, CodingKey {
        case id, name, category, cuisine, lat, lng, address, rating, photos, phone, hours
        case reviewCount = "review_count"
        case priceLevel = "price_level"
        case utcOffsetMinutes = "utc_offset_minutes"
        case businessStatus = "business_status"
        case googleMapsURL = "google_maps_url"
    }
}

public struct SavedPlace: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let place: Place
    public let city: String?
    public let reelURL: String?
    public let description: String?
    public let tips: [String]?
    public let whatToOrder: [String]?
    public let vibe: [String]?
    public let instagramHandle: String?
    public let website: String?
    public let hoursHint: String?
    public let priceLevelAI: Int?
    public let confidence: Double?
    public let savedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, place, city, description, tips, confidence, vibe, website
        case reelURL = "reel_url"
        case whatToOrder = "what_to_order"
        case instagramHandle = "instagram_handle"
        case hoursHint = "hours_hint"
        case priceLevelAI = "price_level_ai"
        case savedAt = "saved_at"
    }
}

public struct PlaceList: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let title: String
    public let category: String?
    public let city: String?
    public let placeCount: Int

    enum CodingKeys: String, CodingKey {
        case id, title, category, city
        case placeCount = "place_count"
    }
}

public struct ReelStatus: Codable, Sendable {
    public let reelID: String
    public let status: String
    public let placeCount: Int

    enum CodingKeys: String, CodingKey {
        case status
        case reelID = "reel_id"
        case placeCount = "place_count"
    }
}

/// One row in the in-app activity/queue feed.
public struct ReelActivity: Codable, Identifiable, Hashable, Sendable {
    public var id: String { reelID }
    public let reelID: String
    public let status: String  // pending | processing | done | failed
    public let platform: String
    public let title: String?
    public let thumbnailURL: String?
    public let placeCount: Int
    public let error: String?
    public let createdAt: Date

    public var isActive: Bool { status == "pending" || status == "processing" }

    enum CodingKeys: String, CodingKey {
        case status, platform, title, error
        case reelID = "reel_id"
        case thumbnailURL = "thumbnail_url"
        case placeCount = "place_count"
        case createdAt = "created_at"
    }
}
