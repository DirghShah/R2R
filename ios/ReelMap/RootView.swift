import SharedKit
import SwiftUI

struct RootView: View {
    var body: some View {
        TabView {
            MapScreen()
                .tabItem { Label("Map", systemImage: "map.fill") }
            CityListsScreen()
                .tabItem { Label("Lists", systemImage: "list.bullet") }
            AddReelScreen()
                .tabItem { Label("Add", systemImage: "plus.circle.fill") }
        }
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
