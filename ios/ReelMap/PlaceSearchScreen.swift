import CoreLocation
import SharedKit
import SwiftData
import SwiftUI

/// Add a place by looking it up, rather than by sharing a reel of it.
///
/// Two first-time testers opened this app wanting to build a list of places
/// they had already been to, and one of them doesn't use social media at all.
/// Every path in was reel-shaped, so the map stayed blank and there was nothing
/// to do. This is the other door.
///
/// Suggestions appear while typing because that is what a search field is
/// expected to do. It is affordable only because the suggestion call is a
/// tenth of a cent against three cents for a full lookup — so nothing is
/// actually resolved until a row is tapped.
struct PlaceSearchScreen: View {
    @EnvironmentObject private var maps: MapStore
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @StateObject private var location = LocationManager()

    /// Where the pin lands. Defaults to the map being looked at.
    @State private var targetMapID: String?
    @State private var query = ""
    @State private var suggestions: [PlaceSuggestion] = []
    @State private var searching = false
    @State private var adding: String?
    @State private var errorText: String?
    @State private var added: String?
    @FocusState private var focused: Bool

    /// Cancels the previous request when another keystroke lands, so a fast
    /// typist pays for one search rather than one per letter.
    @State private var pending: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            ZStack {
                Color.canvas.ignoresSafeArea()
                VStack(spacing: 0) {
                    field
                    destination
                    results
                }
            }
            .navigationTitle("Add a place")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .alert("Couldn't add that", isPresented: .init(
                get: { errorText != nil }, set: { if !$0 { errorText = nil } })) {
                Button("OK", role: .cancel) {}
            } message: { Text(errorText ?? "") }
        }
        .onAppear {
            targetMapID = targetMapID ?? maps.currentID
            focused = true
        }
    }

    // MARK: Field

    private var field: some View {
        HStack(spacing: 9) {
            if searching {
                ProgressView().controlSize(.small).frame(width: 15)
            } else {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.inkMuted).frame(width: 15)
            }
            TextField("", text: $query,
                      prompt: Text("Restaurant, café or bar").foregroundColor(.inkMuted))
                .font(.system(size: 15)).foregroundStyle(.ink)
                .autocorrectionDisabled().textInputAutocapitalization(.words)
                .focused($focused)
                .onChange(of: query) { _, q in schedule(q) }
            if !query.isEmpty {
                Button { query = ""; suggestions = [] } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.inkMuted)
                }.buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .card(14)
        .padding(.horizontal, 20).padding(.top, 8)
    }

    /// Which map this lands on. Shown rather than asked: with several maps an
    /// unlabelled destination is a guessing game, and it is one tap to change.
    @ViewBuilder private var destination: some View {
        if maps.maps.count > 1 {
            Menu {
                ForEach(maps.maps) { map in
                    Button {
                        targetMapID = map.id
                        Haptics.select()
                    } label: {
                        Label("\(map.emoji ?? "📍") \(map.name)",
                              systemImage: map.id == targetMapID ? "checkmark" : "")
                    }
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "arrow.down.right.circle")
                    Text("Saving to \(destinationName)")
                    Image(systemName: "chevron.down").font(.system(size: 10, weight: .bold))
                }
                .font(.system(size: 13)).foregroundStyle(.inkSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 22).padding(.top, 10)
            }
        }
    }

    private var destinationName: String {
        guard let map = maps.maps.first(where: { $0.id == targetMapID }) else { return "your map" }
        return "\(map.emoji ?? "📍") \(map.name)"
    }

    // MARK: Results

    @ViewBuilder private var results: some View {
        if let added {
            confirmation(added)
        } else if suggestions.isEmpty {
            hint
        } else {
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(Array(suggestions.enumerated()), id: \.element.id) { i, s in
                        Button { Task { await add(s) } } label: { row(s, first: i == 0) }
                            .buttonStyle(.plain)
                            .disabled(adding != nil)
                    }
                }
                .padding(.horizontal, 20).padding(.top, 14)
            }
            .scrollIndicators(.hidden)
            .scrollDismissesKeyboard(.immediately)
        }
    }

    private func row(_ s: PlaceSuggestion, first: Bool) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "mappin.circle.fill")
                .font(.system(size: 20)).foregroundStyle(.appAccent)
            VStack(alignment: .leading, spacing: 1) {
                Text(s.name).font(.system(size: 15, weight: .medium))
                    .foregroundStyle(.ink).lineLimit(1)
                if let detail = s.detail {
                    Text(detail).font(.system(size: 12.5))
                        .foregroundStyle(.inkSecondary).lineLimit(1)
                }
            }
            Spacer(minLength: 0)
            if adding == s.placeID {
                ProgressView().controlSize(.small)
            } else {
                Image(systemName: "plus.circle")
                    .font(.system(size: 17)).foregroundStyle(.inkMuted)
            }
        }
        .padding(.vertical, 12)
        .contentShape(Rectangle())
        .overlay(alignment: .top) {
            if !first { Rectangle().fill(Color.hairline).frame(height: 1) }
        }
    }

    private var hint: some View {
        VStack(spacing: 7) {
            Spacer()
            Image(systemName: "text.magnifyingglass")
                .font(.system(size: 26)).foregroundStyle(.inkMuted)
            Text(query.count >= 2 && !searching ? "No places found" : "Start typing a name")
                .font(.system(size: 15, weight: .medium)).foregroundStyle(.ink)
            Text("Add somewhere you've already been, or somewhere you want to try. No reel needed.")
                .font(.system(size: 13)).foregroundStyle(.inkSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 44)
            Spacer()
        }
    }

    private func confirmation(_ name: String) -> some View {
        VStack(spacing: 9) {
            Spacer()
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 34)).foregroundStyle(.green)
            Text("\(name) added").font(.display(19, .semibold)).foregroundStyle(.ink)
            Text("It's on \(destinationName).")
                .font(.system(size: 14)).foregroundStyle(.inkSecondary)
            Button("Add another") {
                added = nil
                query = ""
                suggestions = []
                focused = true
            }
            .font(.system(size: 14, weight: .semibold)).foregroundStyle(.linkBlue)
            .padding(.top, 4)
            Spacer()
        }
    }

    // MARK: Actions

    /// Debounced. Each keystroke cancels the last request rather than queueing
    /// another, because every one of them is a billed call.
    private func schedule(_ text: String) {
        pending?.cancel()
        added = nil
        let q = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard q.count >= 2 else {
            suggestions = []
            searching = false
            return
        }
        pending = Task {
            try? await Task.sleep(for: .milliseconds(320))
            guard !Task.isCancelled else { return }
            searching = true
            defer { searching = false }
            let here = location.current?.coordinate
            let found = try? await APIClient.shared.suggestPlaces(
                query: q, lat: here?.latitude, lng: here?.longitude)
            guard !Task.isCancelled else { return }
            suggestions = found ?? []
        }
    }

    private func add(_ s: PlaceSuggestion) async {
        adding = s.placeID
        defer { adding = nil }
        do {
            _ = try await APIClient.shared.addPlace(placeID: s.placeID, mapID: targetMapID)
            Haptics.success()
            added = s.name
            // The pin has to exist locally before the sheet closes, or the map
            // behind it still looks empty.
            await Syncer.refresh(context, force: true)
            await maps.refresh(force: true)
        } catch {
            errorText = error.localizedDescription
        }
    }
}
