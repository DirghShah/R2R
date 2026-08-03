import SharedKit
import SwiftUI
import UIKit

/// Design system translated from the "Reel Analyzer" HTML mock. Cream/ink light
/// theme with brand green + category accents, now with adaptive dark variants.

extension Color {
    init(hex: UInt) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: 1)
    }

    /// Light/dark adaptive color from two hex values.
    static func dynamic(_ light: UInt, _ dark: UInt) -> Color {
        Color(uiColor: UIColor { tc in
            UIColor(Color(hex: tc.userInterfaceStyle == .dark ? dark : light))
        })
    }

    // Palette — neutrals adapt to dark mode; brand hues stay put.
    static let appAccent    = Color(hex: 0x159A6A)  // brand green
    static let ink          = dynamic(0x16201C, 0xF1F4F1)  // primary text
    static let inkSecondary = dynamic(0x6B746F, 0xA7B0AA)
    static let inkMuted     = dynamic(0x9AA39D, 0x6E766F)
    static let canvas       = dynamic(0xF6F6F3, 0x111412)  // screen background
    static let cardFill     = dynamic(0xFFFFFF, 0x1C201E)  // card surface (was white)
    static let cardStroke   = dynamic(0xEEEEE8, 0x2B2F2C)
    static let hairline     = dynamic(0xF2F2EC, 0x262A27)
    static let linkBlue     = dynamic(0x2F6FE0, 0x5B8DF0)
    static let starGold     = Color(hex: 0xF0A91E)
    static let closedRed    = dynamic(0xC0563F, 0xE07D66)
    static let deepGreen    = Color(hex: 0x0F2A20)  // "Analyzing now" card (always dark)
}

/// SwiftUI resolves `.foregroundStyle(.appAccent)` / `.fill(.appAccent)` via
/// implicit-member lookup on `ShapeStyle`, NOT on `Color` — so the `Color`
/// statics above aren't visible there (that's the "Type 'ShapeStyle' has no
/// member …" error). Mirror them here so the brand palette works anywhere a
/// ShapeStyle is expected, exactly like the built-in `.red`/`.blue` do.
extension ShapeStyle where Self == Color {
    static var appAccent: Color    { Color.appAccent }
    static var ink: Color          { Color.ink }
    static var inkSecondary: Color { Color.inkSecondary }
    static var inkMuted: Color     { Color.inkMuted }
    static var canvas: Color       { Color.canvas }
    static var cardFill: Color     { Color.cardFill }
    static var cardStroke: Color   { Color.cardStroke }
    static var hairline: Color     { Color.hairline }
    static var linkBlue: Color     { Color.linkBlue }
    static var starGold: Color     { Color.starGold }
    static var closedRed: Color    { Color.closedRed }
    static var deepGreen: Color    { Color.deepGreen }
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
            .background(Color.cardFill, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
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

/// Light, non-intrusive haptics — makes taps feel physical.
///
/// The generators are held and `prepare()`d rather than constructed at the
/// moment of the tap. Firing a cold generator makes the Taptic Engine power up
/// synchronously, which is the "first press of any button lags, the second is
/// instant" symptom — the engine idles down again, so it isn't a one-time
/// launch cost, it recurs on every control you haven't touched recently.
@MainActor
enum Haptics {
    private static let impact = UIImpactFeedbackGenerator(style: .light)
    private static let selection = UISelectionFeedbackGenerator()
    private static let notification = UINotificationFeedbackGenerator()

    static func tap() {
        impact.impactOccurred()
        impact.prepare()
    }

    static func select() {
        selection.selectionChanged()
        selection.prepare()
    }

    static func success() {
        notification.notificationOccurred(.success)
        notification.prepare()
    }

    static func error() {
        notification.notificationOccurred(.error)
        notification.prepare()
    }

    /// Spin the Taptic Engine up before the user's first tap, not during it.
    static func warm() {
        impact.prepare()
        selection.prepare()
        notification.prepare()
    }
}

enum DistanceFormat {
    /// "450 ft", "0.3 mi", "12 mi".
    static func short(_ meters: Double) -> String {
        let miles = meters / 1609.34
        if miles < 0.1 { return "\(Int((meters * 3.28084).rounded())) ft" }
        if miles < 10 { return String(format: "%.1f mi", miles) }
        return "\(Int(miles.rounded())) mi"
    }
}
