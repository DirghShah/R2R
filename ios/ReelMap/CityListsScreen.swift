import SharedKit
import SwiftUI

struct CityListsScreen: View {
    @StateObject private var store = PlacesStore()

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22) {
                    ForEach(groupedByCity, id: \.key) { city, lists in
                        VStack(alignment: .leading, spacing: 12) {
                            Text(city).font(.title3.bold()).padding(.horizontal, 4)
                            ForEach(lists) { list in
                                NavigationLink(value: list) { ListRow(list: list) }
                                    .buttonStyle(.plain)
                            }
                        }
                    }
                }
                .padding(20)
            }
            .navigationTitle("Lists")
            .navigationDestination(for: PlaceList.self) { ListDetailScreen(list: $0, store: store) }
            .overlay { if store.lists.isEmpty && !store.isLoading { empty } }
            .task { await store.refresh() }
            .refreshable { await store.refresh() }
        }
    }

    private var groupedByCity: [(key: String, value: [PlaceList])] {
        Dictionary(grouping: store.lists) { $0.city ?? "Other" }.sorted { $0.key < $1.key }
    }

    private var empty: some View {
        ContentUnavailableView {
            Label("No lists yet", systemImage: "square.stack.3d.up")
        } description: {
            Text("Add reels and we'll build city lists automatically.")
        }
    }
}

private struct ListRow: View {
    let list: PlaceList
    private var category: PlaceCategory { PlaceCategory(rawValue: list.category ?? "other") ?? .other }

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: category.symbol)
                .font(.headline).foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(category.tint, in: .circle)
            VStack(alignment: .leading, spacing: 2) {
                Text(list.title).font(.headline)
                Text("\(list.placeCount) place\(list.placeCount == 1 ? "" : "s")")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Image(systemName: "chevron.right").foregroundStyle(.secondary)
        }
        .padding(14)
        .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 20))
    }
}

struct ListDetailScreen: View {
    let list: PlaceList
    @ObservedObject var store: PlacesStore
    @State private var selected: SavedPlace?

    private var places: [SavedPlace] {
        store.places.filter { $0.place.category == list.category }
    }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(places) { saved in
                    Button { selected = saved } label: {
                        HStack(spacing: 12) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(saved.place.name).font(.headline)
                                if let a = saved.place.address {
                                    Text(a).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                }
                            }
                            Spacer()
                            if let r = saved.place.rating {
                                Label(String(format: "%.1f", r), systemImage: "star.fill")
                                    .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                            }
                        }
                        .padding(14)
                        .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 18))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(20)
        }
        .navigationTitle(list.title)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $selected) { PlaceDetailScreen(saved: $0) }
    }
}
