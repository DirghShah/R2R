import SharedKit
import SwiftUI

/// Small design system: category colors, names, map filters, and a subtle
/// material card style (clean and modern, a touch of depth — not flashy).

extension PlaceCategory {
    var tint: Color {
        switch self {
        case .cafe: return Color(red: 0.74, green: 0.49, blue: 0.24)
        case .restaurant: return Color(red: 0.92, green: 0.45, blue: 0.20)
        case .hotel: return Color(red: 0.36, green: 0.42, blue: 0.85)
        case .bar: return Color(red: 0.55, green: 0.35, blue: 0.80)
        case .club: return Color(red: 0.86, green: 0.30, blue: 0.55)
        case .sight: return Color(red: 0.20, green: 0.62, blue: 0.58)
        case .event: return Color(red: 0.88, green: 0.30, blue: 0.32)
        case .other: return Color(red: 0.45, green: 0.50, blue: 0.55)
        }
    }

    var displayName: String {
        switch self {
        case .cafe: return "Cafe"
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

enum MapFilter: String, CaseIterable, Identifiable {
    case all, cafes, food, stays, nightlife, sights
    var id: String { rawValue }

    var label: String {
        switch self {
        case .all: return "All"
        case .cafes: return "Cafes"
        case .food: return "Food"
        case .stays: return "Stays"
        case .nightlife: return "Nightlife"
        case .sights: return "Sights"
        }
    }

    var icon: String {
        switch self {
        case .all: return "circle.grid.2x2.fill"
        case .cafes: return "cup.and.saucer.fill"
        case .food: return "fork.knife"
        case .stays: return "bed.double.fill"
        case .nightlife: return "wineglass.fill"
        case .sights: return "binoculars.fill"
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

/// The app accent — a calm, cool eucalyptus green.
extension Color {
    static let appAccent = Color(red: 0.16, green: 0.52, blue: 0.42)
}

/// Subtle material card: thin material, hairline border, soft shadow.
struct CardBackground: ViewModifier {
    var radius: CGFloat = 16
    func body(content: Content) -> some View {
        content
            .background(.regularMaterial,
                        in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.06)))
            .shadow(color: .black.opacity(0.06), radius: 8, y: 3)
    }
}

extension View {
    func card(_ radius: CGFloat = 16) -> some View { modifier(CardBackground(radius: radius)) }
}
