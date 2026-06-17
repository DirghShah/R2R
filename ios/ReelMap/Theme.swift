import CoreLocation
import SharedKit
import SwiftUI

/// Small design system: category colors, display names, and convenience accessors
/// used across the Liquid Glass UI.

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

extension SavedPlace {
    var categoryEnum: PlaceCategory { PlaceCategory(rawValue: place.category) ?? .other }

    var coordinate: CLLocationCoordinate2D? {
        guard let lat = place.lat, let lng = place.lng else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }
}

/// Map filter chips grouped into the user's mental model (food / stays / etc.).
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
