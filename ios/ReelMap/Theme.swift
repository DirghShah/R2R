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

enum MapFilter: String, CaseIterable, Identifiable {
    case all, cafes, food, stays, nightlife, sights
    var id: String { rawValue }

    var label: String {
        switch self {
        case .all: return "All"
        case .cafes: return "Cafés"
        case .food: return "Food"
        case .stays: return "Stays"
        case .nightlife: return "Nightlife"
        case .sights: return "Sights"
        }
    }

    var dotColor: Color {
        switch self {
        case .all: return .appAccent
        case .cafes: return PlaceCategory.cafe.tint
        case .food: return PlaceCategory.restaurant.tint
        case .stays: return PlaceCategory.hotel.tint
        case .nightlife: return PlaceCategory.bar.tint
        case .sights: return PlaceCategory.sight.tint
        }
    }

    func matches(_ category: PlaceCategory) -> Bool {
        switch self {
        case .all: return true
        case .cafes: return category == .cafe
        case .food: return category == .restaurant
        case .stays: return category == .hotel
        case .nightlife: return category == .bar || category == .club
        case .sights: return category == .sight || category == .event
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
}
