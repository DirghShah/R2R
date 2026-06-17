import SwiftData
import SharedKit
import SwiftUI

struct CityListsScreen: View {
    @Environment(\.modelContext) private var context
    @Query(sort: \CachedList.title) private var lists: [CachedList]

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22) {
                    ForEach(groupedByCity, id: \.key) { city, lists in
                        VStack(alignment: .leading, spacing: 12) {
                            Text(city).font(.title3.bold()).padding(.horizontal, 4)
                            ForEach(lists) { list in
                                NavigationLink(value: list.id) { ListRow(list: list) }
                                    .buttonStyle(.plain)
                            }
                        }
                    }
                }
                .padding(20)
            }
            .navigationTitle("Lists")
            .navigationDestination(for: String.self) { listID in
                if let list = lists.first(where: { $0.id == listID }) {
                    ListDetailScreen(list: list)
                }
            }
            .overlay { if lists.isEmpty { empty } }
            .task { await Syncer.refresh(context) }
            .refreshable { await Syncer.refresh(context) }
        }
    }

    private var groupedByCity: [(key: String, value: [CachedList])] {
        Dictionary(grouping: lists) { $0.city ?? "Other" }.sorted { $0.key < $1.key }
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
    let list: CachedList
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
        .card(20)
    }
}

struct ListDetailScreen: View {
    let list: CachedList
    @Query private var places: [CachedPlace]
    @State private var selected: CachedPlace?

    init(list: CachedList) {
        self.list = list
        let category = list.category
        let city = list.city
        _places = Query(filter: #Predicate<CachedPlace> { p in
            p.category == category ?? "" && p.city == city
        }, sort: \CachedPlace.name)
    }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(places) { place in
                    Button { selected = place } label: {
                        HStack(spacing: 12) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(place.name).font(.headline)
                                if let a = place.address {
                                    Text(a).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                }
                            }
                            Spacer()
                            if let r = place.rating {
                                Label(String(format: "%.1f", r), systemImage: "star.fill")
                                    .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                            }
                        }
                        .padding(14)
                        .card(18)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(20)
        }
        .navigationTitle(list.title)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $selected) { PlaceDetailScreen(place: $0) }
    }
}
