import MapKit
import SharedKit
import SwiftUI

struct MapScreen: View {
    @StateObject private var store = PlacesStore()
    @State private var selected: SavedPlace?

    private var pins: [SavedPlace] {
        store.places.filter { $0.place.lat != nil && $0.place.lng != nil }
    }

    var body: some View {
        Map {
            ForEach(pins) { saved in
                if let lat = saved.place.lat, let lng = saved.place.lng {
                    Annotation(saved.place.name,
                               coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lng)) {
                        Button { selected = saved } label: {
                            Image(systemName: category(saved).symbol)
                                .padding(8)
                                .background(.thinMaterial, in: Circle())
                        }
                    }
                }
            }
        }
        .overlay(alignment: .top) {
            if store.places.isEmpty && !store.isLoading {
                EmptyHint()
            }
        }
        .task { await store.refresh() }
        .refreshable { await store.refresh() }
        .sheet(item: $selected) { PlaceDetailScreen(saved: $0) }
    }

    private func category(_ s: SavedPlace) -> PlaceCategory {
        PlaceCategory(rawValue: s.place.category) ?? .other
    }
}

private struct EmptyHint: View {
    var body: some View {
        Text("Share an Instagram reel to ReelMap to drop your first pins.")
            .font(.callout)
            .multilineTextAlignment(.center)
            .padding()
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
            .padding()
    }
}
