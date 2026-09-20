import CoreLocation
import SharedKit
import SwiftData
import SwiftUI

struct CityListsScreen: View {
    var openSearch: () -> Void = {}
    var openAdd: () -> Void = {}

    @Environment(\.modelContext) private var context
    @EnvironmentObject private var maps: MapStore
    @Query(sort: \CachedPlace.savedAt, order: .reverse) private var cachedPlaces: [CachedPlace]
    @Query private var marks: [PlaceMark]
    @StateObject private var location = LocationManager()

    @State private var expanded: Set<String> = []
    @State private var selected: CachedPlace?
    @State private var searchText = ""
    @State private var sortMode: SortMode = .recent
    /// The pin queued for deletion, as plain values.
    ///
    /// Deliberately not the CachedPlace. Deleting the model invalidates it, and
    /// this dialog keeps reading its title while SwiftUI tears the sheet down —
    /// reading a property off a deleted SwiftData object is a hard crash, which
    /// is exactly what "the app crashes every time I delete a pin" was.
    /// PlaceDetailScreen already avoided this; here it was still live.
    @State private var pendingDelete: PendingDelete?

    struct PendingDelete: Identifiable {
        let id: String
        let name: String
    }
    @State private var deleteError: String?

    // Vibe search. Typing filters by name instantly and offline, as it always
    // has; submitting asks the server what matches the *feeling*. Keeping them
    // separate means the cheap path stays instant and the model call only runs
    // when somebody actually asks a question.
    @State private var vibeQuery: String?
    @State private var vibeMatches: [VibeSearchResponse.Match] = []
    @State private var vibeSearching = false
    @State private var vibeError: String?
    @FocusState private var searchFocused: Bool

    /// Until somebody has actually run one, the examples show without needing
    /// the field focused. A capability that lives inside a search box is
    /// invisible to anyone who never opens the search box, and this is the only
    /// surface that reaches them — short of a modal nobody reads.
    ///
    /// Self-limiting on purpose: it disappears the moment it has done its job,
    /// or when dismissed.
    @AppStorage("hasUsedVibeSearch") private var hasUsedVibeSearch = false

    /// Shown when the field is focused and empty. A search box can only teach
    /// its own capability before anything is typed — afterwards the person is
    /// already committed to a query, and if it was a name query they have
    /// already been told it failed.
    private let vibeExamples = [
        "quiet enough to work",
        "impressive for a date",
        "cheap and late night",
    ]

    enum SortMode: String, CaseIterable, Identifiable {
        case recent = "Recent", rating = "Top rated", name = "Name"
        var id: String { rawValue }
        var icon: String {
            switch self {
            case .recent: return "clock"
            case .rating: return "star"
            case .name: return "textformat"
            }
        }
    }

    private var visitedIDs: Set<String> { Set(marks.filter(\.visited).map(\.placeID)) }

    /// Scoped to the map you're looking at; the response carries all of them.
    private var places: [CachedPlace] {
        guard let mapID = maps.currentID else { return cachedPlaces }
        return cachedPlaces.filter { $0.mapID == mapID }
    }

    private var filtered: [CachedPlace] {
        // A vibe result replaces the name filter entirely and keeps the
        // server's ranking — re-sorting it would throw away the ordering that
        // is the point of asking.
        if vibeQuery != nil {
            let byID = Dictionary(uniqueKeysWithValues: places.map { ($0.id, $0) })
            return vibeMatches.compactMap { byID[$0.placeID] }
        }
        let q = searchText.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return places }
        return places.filter {
            $0.name.lowercased().contains(q)
                || ($0.cuisine?.lowercased().contains(q) ?? false)
                || ($0.cityLabel?.lowercased().contains(q) ?? false)
                || ($0.vibe.contains { v in v.lowercased().contains(q) })
        }
    }

    /// The clause the server gave for why this place matched, if it did.
    private func vibeReason(_ place: CachedPlace) -> String? {
        vibeMatches.first { $0.placeID == place.id }?.reason
    }

    private func withinCitySort(_ a: CachedPlace, _ b: CachedPlace) -> Bool {
        switch sortMode {
        case .rating:
            return (a.rating ?? 0) != (b.rating ?? 0) ? (a.rating ?? 0) > (b.rating ?? 0) : a.name < b.name
        case .recent:
            return a.savedAt != b.savedAt ? a.savedAt > b.savedAt : a.name < b.name
        case .name:
            return a.name < b.name
        }
    }

    private var cities: [(name: String, places: [CachedPlace])] {
        Dictionary(grouping: filtered) { $0.cityLabel ?? "Other" }
            .map { (name: $0.key, places: $0.value.sorted(by: withinCitySort)) }
            // Total order so expanding a city never reshuffles the list.
            .sorted { $0.places.count != $1.places.count ? $0.places.count > $1.places.count : $0.name < $1.name }
    }

    var body: some View {
        ZStack {
            Color.canvas.ignoresSafeArea()
            if places.isEmpty {
                empty
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        MapHeaderBar().padding(.top, 6).padding(.bottom, 4)
                        header
                        searchBar
                        vibePrompts
                            .animation(.snappy(duration: 0.22), value: showsVibePrompts)
                        if cities.isEmpty {
                            noResults
                        } else {
                            vibeOffer
                            ForEach(cities, id: \.name) { city in
                                CityRow(
                                    name: city.name,
                                    places: city.places,
                                    visitedIDs: visitedIDs,
                                    userLocation: location.current,
                                    reasonFor: vibeReason,
                                    expanded: expanded.contains(city.name),
                                    toggle: { toggle(city.name) },
                                    openPlace: { Haptics.tap(); selected = $0 },
                                    deletePlace: {
                                        pendingDelete = PendingDelete(id: $0.id, name: $0.name)
                                    },
                                    showsAttribution: maps.current?.isShared ?? false)
                            }
                        }
                    }
                    .padding(.bottom, 24)
                }
                .scrollIndicators(.hidden)
            }
        }
        // Not forced: MapScreen's .task usually got here first, and the
        // single-flight guard in Syncer means this is a no-op rather than a
        // second round trip.
        .task { await Syncer.refresh(context) }
        .refreshable { await Syncer.refresh(context, force: true) }
        .sheet(item: $selected) {
            PlaceDetailScreen(place: $0, userLocation: location.current,
                              showsAttribution: maps.current?.isShared ?? false)
        }
        .confirmationDialog("Remove \(pendingDelete?.name ?? "this place")?",
                            isPresented: .init(get: { pendingDelete != nil },
                                               set: { if !$0 { pendingDelete = nil } }),
                            titleVisibility: .visible) {
            Button("Remove pin", role: .destructive) {
                guard let target = pendingDelete else { return }
                // Cleared before the delete, not after: leaving it set means
                // the dialog re-reads a name that no longer exists.
                pendingDelete = nil
                Task { await delete(target.id) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("It disappears from your map and lists. Sharing the reel again brings it back.")
        }
        .alert("Couldn't remove", isPresented: .init(get: { deleteError != nil },
                                                    set: { if !$0 { deleteError = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(deleteError ?? "")
        }
    }

    private func delete(_ placeID: String) async {
        do {
            try await Syncer.delete(placeID: placeID, context)
            Haptics.success()
        } catch {
            deleteError = error.localizedDescription
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text("SAVED FROM REELS")
                    .font(.system(size: 13, weight: .semibold)).tracking(0.4)
                    .foregroundStyle(.appAccent)
                Text("Your Lists").font(.display(30, .bold)).foregroundStyle(.ink)
                Text("\(places.count) place\(places.count == 1 ? "" : "s") across \(cities.count) cit\(cities.count == 1 ? "y" : "ies")")
                    .font(.system(size: 14)).foregroundStyle(.inkSecondary)
            }
            Spacer()
            sortMenu
        }
        .padding(.horizontal, 22).padding(.top, 8).padding(.bottom, 14)
    }

    private var sortMenu: some View {
        Menu {
            Picker("Sort", selection: $sortMode) {
                ForEach(SortMode.allCases) { Label($0.rawValue, systemImage: $0.icon).tag($0) }
            }
        } label: {
            Image(systemName: "arrow.up.arrow.down")
                .font(.system(size: 15, weight: .semibold)).foregroundStyle(.ink)
                .frame(width: 40, height: 40).card(13)
        }
        .onChange(of: sortMode) { _, _ in Haptics.select() }
    }

    private var searchBar: some View {
        VStack(spacing: 8) {
            HStack(spacing: 9) {
                if vibeSearching {
                    ProgressView().controlSize(.small).frame(width: 15)
                } else {
                    Image(systemName: vibeQuery == nil ? "magnifyingglass" : "sparkles")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(vibeQuery == nil ? Color.inkMuted : .appAccent)
                        .frame(width: 15)
                }
                TextField("", text: $searchText,
                          prompt: Text("Search a name, or describe a vibe").foregroundColor(.inkMuted))
                    .font(.system(size: 14)).foregroundStyle(.ink)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                    .submitLabel(.search)
                    // Return runs the vibe search. Typing keeps filtering by
                    // name, so nothing gets slower and nothing costs anything
                    // until a question is actually asked.
                    .focused($searchFocused)
                    .onSubmit { Task { await runVibeSearch() } }
                    .onChange(of: searchText) { _, _ in clearVibeResults() }
                if !searchText.isEmpty {
                    Button {
                        searchText = ""
                        clearVibeResults()
                    } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.inkMuted)
                    }.buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 11)
            .card(14)

            if let vibeError {
                Text(vibeError)
                    .font(.system(size: 12)).foregroundStyle(.closedRed)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if vibeQuery != nil {
                HStack(spacing: 6) {
                    Image(systemName: "sparkles").font(.system(size: 10, weight: .semibold))
                    Text(vibeMatches.isEmpty
                         ? "Nothing saved matches that yet"
                         : "\(vibeMatches.count) match\(vibeMatches.count == 1 ? "" : "es") for what you described")
                    Spacer()
                    Button("Clear") { clearVibeResults() }
                        .font(.system(size: 12, weight: .semibold))
                }
                .font(.system(size: 12)).foregroundStyle(.inkSecondary)
            }
        }
        .padding(.horizontal, 22).padding(.bottom, 12)
    }

    /// On focus with an empty field — and, until vibe search has been used
    /// once, without focus at all.
    private var showsVibePrompts: Bool {
        guard searchText.isEmpty, vibeQuery == nil else { return false }
        return searchFocused || !hasUsedVibeSearch
    }

    /// Tappable example queries, where the results would be.
    ///
    /// This replaced a line of grey text under the field reading "press return
    /// to search by vibe". Nobody reads that: it appeared only after you had
    /// typed, which is after a natural-language query has already come back
    /// empty from the name filter and been reported as a failure.
    @ViewBuilder private var vibePrompts: some View {
        if showsVibePrompts {
            // One scrolling row of pills, not three stacked cards. The cards
            // took roughly half the screen above the list, which made a
            // suggestion feel like a takeover — and pushed the thing the person
            // actually came for below the fold.
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 6) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 10, weight: .semibold)).foregroundStyle(.appAccent)
                    Text(hasUsedVibeSearch ? "Or describe what you're after"
                                           : "You can also search by how a place feels")
                        .font(.system(size: 12)).foregroundStyle(.inkSecondary)
                    Spacer(minLength: 0)
                    // Only while it is unsolicited. Once it is a response to
                    // focus, dismissing it makes no sense.
                    if !hasUsedVibeSearch && !searchFocused {
                        Button {
                            Haptics.tap()
                            hasUsedVibeSearch = true
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 10, weight: .bold))
                                .foregroundStyle(.inkMuted)
                                .frame(width: 24, height: 24)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 22)

                ScrollView(.horizontal) {
                    HStack(spacing: 7) {
                        ForEach(vibeExamples, id: \.self) { example in
                            Button {
                                Haptics.tap()
                                searchText = example
                                Task { await runVibeSearch() }
                            } label: {
                                Text(example)
                                    .font(.system(size: 13))
                                    .foregroundStyle(.ink)
                                    .lineLimit(1)
                                    .padding(.horizontal, 13).padding(.vertical, 8)
                                    .background(Color.appAccent.opacity(0.10), in: Capsule())
                                    .overlay(Capsule().strokeBorder(Color.appAccent.opacity(0.22)))
                                    .contentShape(Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 22)
                }
                .scrollIndicators(.hidden)
            }
            .padding(.bottom, 10)
            // Appearing and disappearing as focus changes; without this the
            // list under it jumps.
            .transition(.opacity.combined(with: .move(edge: .top)))
        }
    }

    /// A compact offer above the results while a name search is showing.
    ///
    /// Return still runs the search, but return is invisible — it can't be the
    /// only way in. This is the visible one.
    @ViewBuilder private var vibeOffer: some View {
        if vibeQuery == nil, !vibeSearching, !searchText.isEmpty, !cities.isEmpty {
            Button {
                Haptics.tap()
                Task { await runVibeSearch() }
            } label: {
                HStack(spacing: 9) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 13, weight: .semibold)).foregroundStyle(.appAccent)
                    Text("Search “\(searchText)” by vibe instead")
                        .font(.system(size: 13, weight: .medium)).foregroundStyle(.ink)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right")
                        .font(.system(size: 11, weight: .bold)).foregroundStyle(.inkMuted)
                }
                .padding(.horizontal, 13).padding(.vertical, 10)
                .frame(maxWidth: .infinity)
                .background(Color.appAccent.opacity(0.09),
                            in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 22).padding(.bottom, 10)
        }
    }

    private func clearVibeResults() {
        guard vibeQuery != nil || vibeError != nil else { return }
        vibeQuery = nil
        vibeMatches = []
        vibeError = nil
    }

    private func runVibeSearch() async {
        let q = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard q.count >= 2 else { return }
        vibeSearching = true
        vibeError = nil
        defer { vibeSearching = false }
        do {
            let result = try await APIClient.shared.vibeSearch(query: q, mapID: maps.currentID)
            vibeMatches = result.matches
            vibeQuery = q
            // Otherwise the keyboard covers the answer you just asked for.
            searchFocused = false
            // It has done its job; stop volunteering it.
            hasUsedVibeSearch = true
            Haptics.success()
        } catch {
            // Never render a failure as "no results" — that reads as though
            // the places themselves are gone.
            vibeError = "Couldn't search that just now. Your name search still works."
            vibeQuery = nil
            vibeMatches = []
        }
    }

    /// The best place in the app to teach vibe search, because it is exactly
    /// when someone needs it.
    ///
    /// A typed phrase finds no place *named* that, so this used to say "No
    /// matches" and stop — telling the person the search failed at the precise
    /// moment the app could have impressed them. The dead end is now the offer.
    @ViewBuilder private var noResults: some View {
        if vibeQuery != nil {
            // Already a vibe search. Nothing to upsell — just be honest about
            // why: it can only find what a reel actually said.
            VStack(spacing: 6) {
                Image(systemName: "sparkles").font(.title2).foregroundStyle(.inkMuted)
                Text("No matches").font(.display(17, .semibold)).foregroundStyle(.ink)
                Text("None of your saved places were described that way. Try a different feeling, or fewer conditions.")
                    .font(.callout).foregroundStyle(.inkSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 32)
            }
            .padding(.top, 40)
        } else if searchText.trimmingCharacters(in: .whitespacesAndNewlines).count < 2 {
            // Too short to search on. Offering a button that refuses to run is
            // worse than offering nothing.
            VStack(spacing: 6) {
                Image(systemName: "magnifyingglass").font(.title2).foregroundStyle(.inkMuted)
                Text("No matches").font(.display(17, .semibold)).foregroundStyle(.ink)
                Text("Nothing saved matches “\(searchText)”.")
                    .font(.callout).foregroundStyle(.inkSecondary)
            }
            .padding(.top, 40)
        } else {
            VStack(spacing: 8) {
                Image(systemName: "sparkles")
                    .font(.system(size: 26)).foregroundStyle(.appAccent)
                Text("No place is called that")
                    .font(.display(17, .semibold)).foregroundStyle(.ink)
                // Verb-led rather than "vibe" here: at the moment somebody is
                // stuck, being understood beats being on-brand.
                Text("But Nosh can search by what a place feels like, not just its name.")
                    .font(.callout).foregroundStyle(.inkSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 30)

                Button {
                    Haptics.tap()
                    Task { await runVibeSearch() }
                } label: {
                    HStack(spacing: 8) {
                        if vibeSearching {
                            ProgressView().tint(.white).controlSize(.small)
                        } else {
                            Image(systemName: "sparkles").font(.system(size: 13, weight: .semibold))
                        }
                        Text(vibeSearching ? "Looking…" : "Search “\(searchText)”")
                            .font(.system(size: 15, weight: .semibold))
                            .lineLimit(1)
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 20).padding(.vertical, 13)
                    .background(Color.appAccent,
                                in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(vibeSearching)
                .padding(.top, 6)
            }
            .padding(.top, 34).padding(.horizontal, 22)
        }
    }

    /// An empty state that can be acted on, not one that describes the app at
    /// you. Both first-time testers stopped at the old version of this screen.
    private var empty: some View {
        VStack(spacing: 10) {
            ZStack {
                Circle().fill(Color.appAccent.opacity(0.12)).frame(width: 56, height: 56)
                Image(systemName: "square.stack.3d.up.fill").font(.system(size: 24, weight: .semibold)).foregroundStyle(.appAccent)
            }
            Text("No saved places yet").font(.display(19, .semibold)).foregroundStyle(.ink)
            Text("Add somewhere you've been, or share a reel and Nosh pins every place in it.")
                .font(.callout).foregroundStyle(.inkSecondary).multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)

            VStack(spacing: 9) {
                Button { Haptics.tap(); openSearch() } label: {
                    Label("Search for a place", systemImage: "magnifyingglass")
                        .font(.system(size: 15, weight: .semibold)).foregroundStyle(.white)
                        .frame(maxWidth: .infinity).padding(.vertical, 13)
                        .background(Color.appAccent,
                                    in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }.buttonStyle(.plain)
                Button { Haptics.tap(); openAdd() } label: {
                    Label("Paste a reel link", systemImage: "link")
                        .font(.system(size: 15, weight: .semibold)).foregroundStyle(.ink)
                        .frame(maxWidth: .infinity).padding(.vertical, 13)
                        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .strokeBorder(Color.cardStroke))
                }.buttonStyle(.plain)
            }
            .padding(.top, 8)

            // The two lists Jeff described wanting before he had used the app
            // at all. Offered rather than created: two maps nobody asked for
            // is clutter, and one tap is cheap.
            if !maps.maps.contains(where: { !$0.isPersonal }) {
                HStack(spacing: 8) {
                    Text("Start a list:").font(.system(size: 12.5)).foregroundStyle(.inkMuted)
                    quickList("Want to try", emoji: "🔖")
                    quickList("Been to", emoji: "✅")
                }
                .padding(.top, 10)
            }
        }
        .padding(32)
    }

    private func quickList(_ name: String, emoji: String) -> some View {
        Button {
            Haptics.tap()
            Task { try? await maps.create(name: name, emoji: emoji) }
        } label: {
            Text("\(emoji) \(name)")
                .font(.system(size: 12.5, weight: .medium)).foregroundStyle(.ink)
                .padding(.horizontal, 11).padding(.vertical, 6)
                .overlay(Capsule().strokeBorder(Color.cardStroke))
        }.buttonStyle(.plain)
    }

    private func toggle(_ city: String) {
        Haptics.select()
        withAnimation(.snappy) {
            if expanded.contains(city) { expanded.remove(city) } else { expanded.insert(city) }
        }
    }
}

private struct CityRow: View {
    let name: String
    let places: [CachedPlace]
    let visitedIDs: Set<String>
    let userLocation: CLLocation?
    /// Why each place matched a vibe search, when one is showing. Saying what
    /// matched is most of what makes the answer trustworthy.
    var reasonFor: (CachedPlace) -> String? = { _ in nil }
    let expanded: Bool
    let toggle: () -> Void
    let openPlace: (CachedPlace) -> Void
    let deletePlace: (CachedPlace) -> Void
    let showsAttribution: Bool

    private var shareText: String {
        let lines = places.map { p -> String in
            let area = p.address ?? p.cityLabel ?? ""
            return "• \(p.name)\(area.isEmpty ? "" : " — \(area)")"
        }
        return "\(name) — saved on Nosh\n" + lines.joined(separator: "\n")
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 13) {
                Button(action: toggle) {
                    HStack(spacing: 13) {
                        Text(String(name.prefix(1)).uppercased())
                            .font(.display(20, .bold)).foregroundStyle(.ink)
                            .frame(width: 44, height: 44)
                            .background(Color.cardStroke, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
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
                }
                .buttonStyle(.plain)
                ShareLink(item: shareText) {
                    Image(systemName: "square.and.arrow.up").font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(.inkMuted).frame(width: 30, height: 30)
                }
            }
            .padding(.horizontal, 22).padding(.vertical, 16)

            if expanded {
                VStack(spacing: 9) {
                    ForEach(Array(places.enumerated()), id: \.element.id) { idx, place in
                        PlaceListCard(place: place, rank: idx + 1,
                                      visited: visitedIDs.contains(place.id),
                                      userLocation: userLocation,
                                      matchReason: reasonFor(place),
                                      open: { openPlace(place) },
                                      delete: { deletePlace(place) },
                                      showsAttribution: showsAttribution)
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
    let visited: Bool
    let userLocation: CLLocation?
    var matchReason: String? = nil
    let open: () -> Void
    let delete: () -> Void
    var showsAttribution: Bool = false
    private var tint: Color { place.pinColor }

    /// "Italian · Downtown · 0.3 mi" — cuisine, area, then distance when known.
    private var subtitle: String {
        var parts: [String] = []
        if let cuisine = place.cuisine?.trimmingCharacters(in: .whitespacesAndNewlines), !cuisine.isEmpty {
            parts.append(cuisine)
        }
        if let area = place.address ?? place.cityLabel, !area.isEmpty { parts.append(area) }
        if let d = place.distanceMeters(from: userLocation) { parts.append(DistanceFormat.short(d)) }
        return parts.isEmpty ? place.categoryEnum.displayName : parts.joined(separator: " · ")
    }

    @ViewBuilder private var thumb: some View {
        if let url = place.firstPhotoURL {
            AsyncImage(url: url) { img in
                img.resizable().scaledToFill()
            } placeholder: {
                InitialThumb(text: place.initialLetter, color: tint)
            }
            .frame(width: 52, height: 52)
            .clipShape(RoundedRectangle(cornerRadius: 15, style: .continuous))
        } else {
            InitialThumb(text: place.initialLetter, color: tint)
        }
    }

    var body: some View {
        Button(action: open) {
            HStack(spacing: 13) {
                ZStack(alignment: .bottomTrailing) {
                    thumb
                    Text("\(rank)")
                        .font(.system(size: 11, weight: .bold)).foregroundStyle(.ink)
                        .frame(width: 20, height: 20)
                        .background(Color.cardFill, in: Circle())
                        .overlay(Circle().strokeBorder(Color.canvas, lineWidth: 2))
                        .offset(x: 5, y: 5)
                }
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 5) {
                        Text(place.name).font(.display(16, .semibold)).foregroundStyle(.ink).lineLimit(1)
                        if visited {
                            Image(systemName: "checkmark.seal.fill").font(.system(size: 12)).foregroundStyle(.appAccent)
                        }
                    }
                    Text(subtitle)
                        .font(.system(size: 13)).foregroundStyle(.inkSecondary).lineLimit(1)
                    // Say it plainly rather than letting the place quietly miss
                    // the map with no explanation.
                    // What matched, when this row came from a vibe search.
                    // Without it the answer is a list you have to take on
                    // trust; with it you can see the search understood you.
                    if let matchReason, !matchReason.isEmpty {
                        HStack(alignment: .top, spacing: 5) {
                            Image(systemName: "sparkles")
                                .font(.system(size: 9, weight: .semibold))
                                .padding(.top, 2)
                            Text(matchReason)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .font(.system(size: 11.5))
                        .foregroundStyle(.appAccent)
                        .padding(.top, 3)
                    }
                    if place.isUnmapped {
                        Label("No map location", systemImage: "mappin.slash")
                            .font(.system(size: 11, weight: .semibold)).foregroundStyle(.orange)
                            .padding(.top, 3)
                    }
                    // Only in shared maps: a personal map has one contributor,
                    // so naming them every time is just noise.
                    if showsAttribution, place.addedBySomeoneElse {
                        AddedByChip(name: place.addedByName, colorHex: place.addedByColor)
                            .padding(.top, 4)
                    }
                }
                Spacer(minLength: 6)
                if let rating = place.rating {
                    HStack(spacing: 4) {
                        Image(systemName: "star.fill").font(.system(size: 11)).foregroundStyle(.appAccent)
                        Text(String(format: "%.1f", rating)).font(.system(size: 14, weight: .bold)).foregroundStyle(.ink)
                    }
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .background(Color.appAccent.opacity(0.10), in: RoundedRectangle(cornerRadius: 11, style: .continuous))
                }
            }
            .padding(10)
            .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Color.cardStroke))
        }
        .buttonStyle(.plain)
        // Long-press to remove — these cards live in a LazyVStack, not a List,
        // so there are no swipe actions to hang this off.
        .contextMenu {
            Button("Open", systemImage: "info.circle", action: open)
            Button("Remove pin", systemImage: "trash", role: .destructive, action: delete)
        }
    }
}
