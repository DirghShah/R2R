import SharedKit
import SwiftUI

struct RootView: View {
    var body: some View {
        // iOS 26 renders the tab bar in Liquid Glass automatically.
        TabView {
            Tab("Map", systemImage: "map.fill") { MapScreen() }
            Tab("Lists", systemImage: "square.stack.3d.up.fill") { CityListsScreen() }
            Tab("Add", systemImage: "plus.circle.fill") { AddReelScreen() }
        }
        .tint(Color(red: 0.92, green: 0.45, blue: 0.20)) // warm app accent
    }
}

@MainActor
final class PlacesStore: ObservableObject {
    @Published var places: [SavedPlace] = []
    @Published var lists: [PlaceList] = []
    @Published var isLoading = false

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        async let p = try? await APIClient.shared.places()
        async let l = try? await APIClient.shared.lists()
        places = await p ?? []
        lists = await l ?? []
    }
}
