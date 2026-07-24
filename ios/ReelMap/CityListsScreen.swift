import SwiftData
import SwiftUI

struct CityListsScreen: View {
    @Environment(\.modelContext) private var context
    @Query(sort: \CachedPlace.savedAt, order: .reverse) private var places: [CachedPlace]

    @State private var expanded: Set<String> = []
    @State private var selected: CachedPlace?

    private var cities: [(name: String, places: [CachedPlace])] {
        let groups = Dictionary(grouping: places) { $0.city ?? "Other" }
        return groups
            .map { key, value in
                // Deterministic within-city order: rating desc, then name.
                let sorted = value.sorted {
                    ($0.rating ?? 0) != ($1.rating ?? 0)
                        ? ($0.rating ?? 0) > ($1.rating ?? 0)
                        : $0.name < $1.name
                }
                return (name: key, places: sorted)
            }
            // Total order (count desc, then name) so expanding a city never
            // reshuffles the list — Dictionary order + an unstable sort otherwise
            // let equal-count cities swap on every re-render.
            .sorted {
                $0.places.count != $1.places.count
                    ? $0.places.count > $1.places.count
                    : $0.name < $1.name
            }
    }

    var body: some View {
        ZStack {
            Color.canvas.ignoresSafeArea()
            if places.isEmpty {
                empty
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        header
                        ForEach(cities, id: \.name) { city in
                            CityRow(
                                name: city.name,
                                places: city.places,
                                expanded: expanded.contains(city.name),
                                toggle: { toggle(city.name) },
                                openPlace: { selected = $0 })
                        }
                    }
                    .padding(.bottom, 24)
                }
                .scrollIndicators(.hidden)
            }
        }
        .task { await Syncer.refresh(context) }
        .refreshable { await Syncer.refresh(context, force: true) }
        .sheet(item: $selected) { PlaceDetailScreen(place: $0) }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("SAVED FROM REELS")
                .font(.system(size: 13, weight: .semibold)).tracking(0.4)
                .foregroundStyle(.appAccent)
            Text("Your Lists").font(.display(30, .bold)).foregroundStyle(.ink)
            Text("\(places.count) place\(places.count == 1 ? "" : "s") across \(cities.count) cit\(cities.count == 1 ? "y" : "ies")")
                .font(.system(size: 14)).foregroundStyle(.inkSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 22).padding(.top, 8).padding(.bottom, 18)
    }

    private var empty: some View {
        VStack(spacing: 8) {
            Image(systemName: "square.stack.3d.up").font(.largeTitle).foregroundStyle(.inkMuted)
            Text("No saved places yet").font(.display(18, .semibold)).foregroundStyle(.ink)
            Text("Analyze a reel and we'll build city lists automatically.")
                .font(.callout).foregroundStyle(.inkSecondary).multilineTextAlignment(.center)
        }
        .padding(32)
    }

    private func toggle(_ city: String) {
        withAnimation(.snappy) {
            if expanded.contains(city) { expanded.remove(city) } else { expanded.insert(city) }
        }
    }
}

private struct CityRow: View {
    let name: String
    let places: [CachedPlace]
    let expanded: Bool
    let toggle: () -> Void
    let openPlace: (CachedPlace) -> Void

    var body: some View {
        VStack(spacing: 0) {
            Button(action: toggle) {
                HStack(spacing: 13) {
                    Text(String(name.prefix(1)).uppercased())
                        .font(.display(20, .bold)).foregroundStyle(.ink)
                        .frame(width: 44, height: 44)
                        .background(Color(hex: 0xEEF1EC), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    VStack(alignment: .leading, spacing: 1) {
                        Text(name).font(.display(18, .semibold)).foregroundStyle(.ink)
                        Text("\(places.count) place\(places.count == 1 ? "" : "s")")
                            .font(.system(size: 13)).foregroundStyle(.inkSecondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.system(size: 14, weight: .bold)).foregroundStyle(.inkMuted)
                        .rotationEffect(.degrees(expanded ? 180 : 0))
                }
                .padding(.horizontal, 22).padding(.vertical, 16)
            }
            .buttonStyle(.plain)

            if expanded {
                VStack(spacing: 9) {
                    ForEach(Array(places.enumerated()), id: \.element.id) { idx, place in
                        PlaceListCard(place: place, rank: idx + 1) { openPlace(place) }
                    }
                }
                .padding(.horizontal, 14).padding(.bottom, 8)
                .transition(.opacity)
            }
        }
        .overlay(alignment: .top) { Rectangle().fill(Color.cardStroke).frame(height: 1) }
    }
}

private struct PlaceListCard: View {
    let place: CachedPlace
    let rank: Int
    let open: () -> Void
    private var tint: Color { place.pinColor }

    /// "Italian · Downtown" — cuisine label first, then the area when we have it.
    private var subtitle: String {
        let area = place.address ?? place.city
        if let cuisine = place.cuisine?.trimmingCharacters(in: .whitespacesAndNewlines), !cuisine.isEmpty {
            if let area, !area.isEmpty { return "\(cuisine) · \(area)" }
            return cuisine
        }
        return area ?? place.categoryEnum.displayName
    }

    var body: some View {
        Button(action: open) {
            HStack(spacing: 13) {
                ZStack(alignment: .bottomTrailing) {
                    InitialThumb(text: place.initialLetter, color: tint)
                    Text("\(rank)")
                        .font(.system(size: 11, weight: .bold)).foregroundStyle(.ink)
                        .frame(width: 20, height: 20)
                        .background(Color.white, in: Circle())
                        .overlay(Circle().strokeBorder(Color.canvas, lineWidth: 2))
                        .offset(x: 5, y: 5)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(place.name).font(.display(16, .semibold)).foregroundStyle(.ink).lineLimit(1)
                    Text(subtitle)
                        .font(.system(size: 13)).foregroundStyle(.inkSecondary).lineLimit(1)
                }
                Spacer(minLength: 6)
                if let rating = place.rating {
                    HStack(spacing: 4) {
                        Image(systemName: "star.fill").font(.system(size: 11)).foregroundStyle(.appAccent)
                        Text(String(format: "%.1f", rating)).font(.system(size: 14, weight: .bold)).foregroundStyle(.ink)
                    }
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .background(Color(hex: 0xF3F6F1), in: RoundedRectangle(cornerRadius: 11, style: .continuous))
                }
            }
            .padding(10)
            .background(Color.white, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Color.cardStroke))
        }
        .buttonStyle(.plain)
    }
}
