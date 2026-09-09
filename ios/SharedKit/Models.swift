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
    /// State/province short code ("TX", "NY") when the geocoder knew one.
    public let region: String?
    public let rating: Double?
    public let reviewCount: Int?
    public let priceLevel: Int?
    public let photos: [String]?
    public let hours: OpeningHours?
    public let utcOffsetMinutes: Int?
    public let phone: String?
    public let businessStatus: String?
    public let googleMapsURL: String?
    /// "user" when someone placed this pin by hand.
    public let locationSource: String?

    enum CodingKeys: String, CodingKey {
        case id, name, category, cuisine, lat, lng, address, region, rating, photos, phone, hours
        case reviewCount = "review_count"
        case priceLevel = "price_level"
        case utcOffsetMinutes = "utc_offset_minutes"
        case businessStatus = "business_status"
        case googleMapsURL = "google_maps_url"
        case locationSource = "location_source"
    }
}

public struct SavedPlace: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let place: Place
    /// Which map this pin lives on. Every map the user belongs to comes back in
    /// one response and the client filters locally.
    public let mapID: String
    /// Who added it — "Priya added Kung Fu Tea" in a shared map.
    public let addedByID: String?
    public let addedByName: String?
    public let addedByColor: String?
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
        case mapID = "map_id"
        case addedByID = "added_by_id"
        case addedByName = "added_by_name"
        case addedByColor = "added_by_color"
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
    /// Set when `status == "unsupported"` — a sentence written for the user
    /// explaining why the reel had nothing to pin.
    public let error: String?
    /// The backend already had this reel analyzed and reused the stored result
    /// instead of running (and charging for) a second analysis.
    public let alreadyAnalyzed: Bool?

    public var isDuplicate: Bool { alreadyAnalyzed == true }

    enum CodingKeys: String, CodingKey {
        case status, error
        case reelID = "reel_id"
        case placeCount = "place_count"
        case alreadyAnalyzed = "already_analyzed"
    }
}

/// One row in the in-app activity/queue feed.
public struct ReelActivity: Codable, Identifiable, Hashable, Sendable {
    public var id: String { reelID }
    public let reelID: String
    public let status: String  // pending | processing | done | failed | unsupported
    public let platform: String
    public let title: String?
    public let thumbnailURL: String?
    public let placeCount: Int
    public let error: String?
    public let createdAt: Date

    public var isActive: Bool { status == "pending" || status == "processing" }

    /// Analysed fine; there was just nothing pinnable in it — an ad, a recipe,
    /// a delivery brand. `error` carries a sentence written for the user.
    public var isUnsupported: Bool { status == "unsupported" }

    enum CodingKeys: String, CodingKey {
        case status, platform, title, error
        case reelID = "reel_id"
        case thumbnailURL = "thumbnail_url"
        case placeCount = "place_count"
        case createdAt = "created_at"
    }
}

// MARK: - Identity

public struct AuthSession: Codable, Sendable {
    public let accessToken: String
    /// Absent only on responses that don't rotate it.
    public let refreshToken: String?

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
    }
}

public struct UserProfile: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let displayName: String?
    /// Generated server-side and stable per user — an initial avatar with no
    /// upload, no storage and nothing to moderate.
    public let avatarColor: String?
    public let plan: String
    public let reelsThisMonth: Int
    public let createdAt: Date

    public var isPro: Bool { plan == "pro" }

    enum CodingKeys: String, CodingKey {
        case id, plan
        case displayName = "display_name"
        case avatarColor = "avatar_color"
        case reelsThisMonth = "reels_this_month"
        case createdAt = "created_at"
    }
}

// MARK: - Maps

public struct MapSummary: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String
    public let emoji: String?
    /// The map every user gets automatically; it can't be deleted.
    public let isPersonal: Bool
    public let isOwner: Bool
    public let memberCount: Int
    public let placeCount: Int
    /// Only ever returned to the owner.
    public let inviteCode: String?
    public let createdAt: Date

    public var isShared: Bool { memberCount > 1 }

    enum CodingKeys: String, CodingKey {
        case id, name, emoji
        case isPersonal = "is_personal"
        case isOwner = "is_owner"
        case memberCount = "member_count"
        case placeCount = "place_count"
        case inviteCode = "invite_code"
        case createdAt = "created_at"
    }
}

public struct MapInvite: Codable, Sendable {
    public let mapID: String
    public let inviteCode: String
    /// Ready to hand straight to a share sheet.
    public let inviteURL: String

    enum CodingKeys: String, CodingKey {
        case mapID = "map_id"
        case inviteCode = "invite_code"
        case inviteURL = "invite_url"
    }
}

/// What someone sees *before* signing in, so it carries nothing sensitive.
public struct MapPreview: Codable, Sendable {
    public let name: String
    public let emoji: String?
    public let ownerName: String?
    public let memberCount: Int

    enum CodingKeys: String, CodingKey {
        case name, emoji
        case ownerName = "owner_name"
        case memberCount = "member_count"
    }
}

public struct MapMemberSummary: Codable, Identifiable, Hashable, Sendable {
    public var id: String { userID }
    public let userID: String
    public let displayName: String?
    public let avatarColor: String?
    public let role: String
    public let joinedAt: Date
    /// Blocked members stay in the list rather than vanishing from it. Hiding
    /// them also hid the menu holding "Remove from map", so blocking someone
    /// on your own map left you unable to remove them.
    public let isBlocked: Bool

    public var isOwner: Bool { role == "owner" }

    enum CodingKeys: String, CodingKey {
        case role
        case userID = "user_id"
        case displayName = "display_name"
        case avatarColor = "avatar_color"
        case joinedAt = "joined_at"
        case isBlocked = "is_blocked"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        userID = try c.decode(String.self, forKey: .userID)
        displayName = try c.decodeIfPresent(String.self, forKey: .displayName)
        avatarColor = try c.decodeIfPresent(String.self, forKey: .avatarColor)
        role = try c.decode(String.self, forKey: .role)
        joinedAt = try c.decode(Date.self, forKey: .joinedAt)
        // Absent from a backend older than this field. Defaulting to false is
        // the safe read: it shows the member normally rather than labelling
        // someone blocked who isn't.
        isBlocked = try c.decodeIfPresent(Bool.self, forKey: .isBlocked) ?? false
    }
}

/// Broadcast when a refresh fails and the session is genuinely gone, so the app
/// can show the sign-in screen instead of silently rendering an empty map.
public enum SessionExpiry {
    public static let didExpire = Notification.Name("reelmap.sessionDidExpire")

    @MainActor public static func notify() {
        NotificationCenter.default.post(name: didExpire, object: nil)
    }
}


// MARK: - Moderation

/// Why someone is reporting something. Raw values match the backend's
/// allowlist in `app/routers/moderation.py`.
public enum ReportReason: String, CaseIterable, Sendable {
    case offensive
    case harassment
    case spam
    case illegal
    case other

    public var label: String {
        switch self {
        case .offensive:  return "Offensive content"
        case .harassment: return "Harassment or bullying"
        case .spam:       return "Spam or misleading"
        case .illegal:    return "Illegal content"
        case .other:      return "Something else"
        }
    }
}

public enum ReportTarget: String, Sendable {
    case map, user, place
}

public struct BlockedUser: Codable, Identifiable, Hashable, Sendable {
    public var id: String { userID }
    public let userID: String
    public let displayName: String?
    public let avatarColor: String?

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case displayName = "display_name"
        case avatarColor = "avatar_color"
    }
}
