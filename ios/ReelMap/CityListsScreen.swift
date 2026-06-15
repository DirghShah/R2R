import SharedKit
import SwiftUI

struct CityListsScreen: View {
    @StateObject private var store = PlacesStore()

    var body: some View {
        NavigationStack {
            List {
                ForEach(groupedByCity, id: \.key) { city, lists in
                    Section(city) {
                        ForEach(lists) { list in
                            NavigationLink(value: list) {
                                Label("\(list.title) · \(list.placeCount)",
                                      systemImage: icon(list))
                            }
                        }
                    }
                }
            }
            .navigationTitle("Lists")
            .navigationDestination(for: PlaceList.self) { ListDetailScreen(list: $0, store: store) }
            .overlay { if store.lists.isEmpty { ContentUnavailableView(
                "No saved places yet", systemImage: "list.bullet",
                description: Text("Share reels to build city lists automatically.")) } }
            .task { await store.refresh() }
            .refreshable { await store.refresh() }
        }
    }

    private var groupedByCity: [(key: String, value: [PlaceList])] {
        Dictionary(grouping: store.lists) { $0.city ?? "Other" }
            .sorted { $0.key < $1.key }
    }

    private func icon(_ list: PlaceList) -> String {
        PlaceCategory(rawValue: list.category ?? "other")?.symbol ?? "mappin"
    }
}

struct ListDetailScreen: View {
    let list: PlaceList
    @ObservedObject var store: PlacesStore
    @State private var selected: SavedPlace?

    private var places: [SavedPlace] {
        store.places.filter {
            $0.place.category == list.category
        }
    }

    var body: some View {
        List(places) { saved in
            Button { selected = saved } label: {
                VStack(alignment: .leading) {
                    Text(saved.place.name).font(.headline)
                    if let a = saved.place.address {
                        Text(a).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .navigationTitle(list.title)
        .sheet(item: $selected) { PlaceDetailScreen(saved: $0) }
    }
}
