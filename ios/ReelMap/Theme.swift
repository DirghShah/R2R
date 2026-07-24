import SharedKit
import SwiftUI

/// Design system translated from the "Reel Analyzer" HTML mock.
/// Light theme: cream canvas, ink text, brand green, category-colored accents.

extension Color {
    init(hex: UInt) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: 1)
    }

    // Palette (from the mock)
    static let appAccent    = Color(hex: 0x159A6A)  // brand green
    static let ink          = Color(hex: 0x16201C)  // primary text
    static let inkSecondary = Color(hex: 0x6B746F)
    static let inkMuted     = Color(hex: 0x9AA39D)
    static let canvas       = Color(hex: 0xF6F6F3)  // screen background
    static let cardStroke   = Color(hex: 0xEEEEE8)
    static let hairline     = Color(hex: 0xF2F2EC)
    static let linkBlue     = Color(hex: 0x2F6FE0)
    static let starGold     = Color(hex: 0xF0A91E)
    static let closedRed    = Color(hex: 0xC0563F)
    static let deepGreen    = Color(hex: 0x0F2A20)  // "Analyzing now" card
}

extension Font {
    /// Display headings (mock uses Bricolage Grotesque; nearest native is a
    /// heavy rounded grotesque). Swap for the bundled font later for exactness.
    static func display(_ size: CGFloat, _ weight: Font.Weight = .bold) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }
}

extension PlaceCategory {
    var tint: Color {
        switch self {
        case .cafe:       return Color(hex: 0xA9793F)
        case .restaurant: return Color(hex: 0xCF6B46)
        case .bar:        return Color(hex: 0x7A5CC0)
        case .club:       return Color(hex: 0xB8455F)
        case .hotel:      return Color(hex: 0x2B8FB3)
        case .sight:      return Color(hex: 0x159A6A)
        case .event:      return Color(hex: 0xC99A2E)
        case .other:      return Color(hex: 0x6B746F)
        }
    }

    var displayName: String {
        switch self {
        case .cafe: return "Café"
        case .restaurant: return "Restaurant"
        case .hotel: return "Stay"
        case .bar: return "Bar"
        case .club: return "Nightlife"
        case .sight: return "Sight"
        case .event: return "Event"
        case .other: return "Place"
        }
    }
}

/// Cuisine / venue-type colors. The AI tags each place with a free-form cuisine
/// label ("Italian", "Cocktail Bar", "Nightclub", …). Known labels get a curated
/// color; anything unrecognized gets a stable color from a fallback palette so the
/// same cuisine always looks the same (a per-process `hashValue` would flicker).
enum CuisineStyle {
    private static let known: [String: UInt] = [
        "italian": 0xCF6B46, "pizza": 0xCF6B46, "mediterranean": 0xC99A2E,
        "greek": 0x2F6FE0, "spanish": 0xD2683B, "french": 0x8E5AA8,
        "japanese": 0xB8455F, "sushi": 0xB8455F, "ramen": 0xB8455F,
        "korean": 0xC0563F, "chinese": 0xC0563F, "thai": 0x2FA37A,
        "vietnamese": 0x2FA37A, "indian": 0xD98324, "mexican": 0xC99A2E,
        "american": 0x7A6A55, "burgers": 0x7A6A55, "bbq": 0x8A4B2F,
        "steakhouse": 0x8A4B2F, "seafood": 0x2B8FB3, "middle eastern": 0xB07A2E,
        "café": 0xA9793F, "cafe": 0xA9793F, "coffee": 0xA9793F,
        "bakery": 0xB98B4E, "brunch": 0xC99A2E, "dessert": 0xD46A8E,
        "ice cream": 0xD46A8E, "vegan": 0x159A6A, "vegetarian": 0x159A6A,
        "cocktail bar": 0x7A5CC0, "wine bar": 0x8E5AA8, "bar": 0x7A5CC0,
        "brewery": 0xB07A2E, "nightclub": 0xB8455F, "club": 0xB8455F,
        "hotel": 0x2B8FB3, "rooftop": 0x2B8FB3,
    ]

    private static let fallback: [UInt] = [
        0xCF6B46, 0x2B8FB3, 0x7A5CC0, 0xC99A2E, 0x2FA37A,
        0xB8455F, 0x2F6FE0, 0xA9793F, 0x8A4B2F, 0xD46A8E,
    ]

    static func color(_ cuisine: String?) -> Color? {
        guard let cuisine else { return nil }
        let key = cuisine.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !key.isEmpty else { return nil }
        if let hex = known[key] { return Color(hex: hex) }
        // Stable hash across launches (String.hashValue is randomized per process).
        let sum = key.unicodeScalars.reduce(0) { $0 &+ Int($1.value) }
        return Color(hex: fallback[sum % fallback.count])
    }
}

/// Platform accent colors from the mock.
enum PlatformStyle {
    static func color(_ platform: String) -> Color {
        switch platform {
        case "tiktok": return Color(hex: 0x111111)
        case "youtube": return Color(hex: 0xE0322A)
        default: return Color(hex: 0xC4377F)  // instagram
        }
    }
    static func name(_ platform: String) -> String {
        switch platform {
        case "tiktok": return "TikTok"
        case "youtube": return "YouTube"
        default: return "Instagram"
        }
    }
    static func icon(_ platform: String) -> String {
        switch platform {
        case "tiktok": return "music.note"
        case "youtube": return "play.rectangle.fill"
        default: return "camera.fill"
        }
    }
}

/// White card with hairline stroke + soft shadow (matches the mock).
struct CardBackground: ViewModifier {
    var radius: CGFloat = 20
    func body(content: Content) -> some View {
        content
            .background(Color.white, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(Color.cardStroke, lineWidth: 1))
            .shadow(color: Color(hex: 0x1E2822).opacity(0.06), radius: 10, y: 4)
    }
}

extension View {
    func card(_ radius: CGFloat = 20) -> some View { modifier(CardBackground(radius: radius)) }
}

/// Small helpers shared across screens.
extension CachedPlace {
    var initialLetter: String {
        let letters = name.filter { $0.isLetter }
        return String(letters.first ?? name.first ?? "•").uppercased()
    }

    /// AI cuisine label if present, else the broad category ("Café", "Bar", …).
    /// Drives the map filter chips and the pin/detail tags.
    var filterLabel: String {
        if let c = cuisine?.trimmingCharacters(in: .whitespacesAndNewlines), !c.isEmpty {
            return c
        }
        return categoryEnum.displayName
    }

    /// Cuisine-tinted pin color, falling back to the category tint.
    var pinColor: Color { CuisineStyle.color(cuisine) ?? categoryEnum.tint }
}
