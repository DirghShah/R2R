import SharedKit
import SwiftUI

/// The user's maps and which one is currently in view.
///
/// The selection lives in App Group defaults rather than `@AppStorage`, because
/// the Share Extension needs to read it: a share has to land on the map the
/// user is actually looking at, and the extension can't ask.
@MainActor
final class MapStore: ObservableObject {
    @Published private(set) var maps: [MapSummary] = []
    @Published private(set) var isLoading = false
    @Published var currentID: String? {
        didSet {
            CurrentMap.id = currentID
            CurrentMap.name = maps.first { $0.id == currentID }?.name
        }
    }

    init() {
        currentID = CurrentMap.id
    }

    var current: MapSummary? {
        maps.first { $0.id == currentID } ?? maps.first
    }

    /// The personal map is the safe fallback — it always exists and can't be
    /// deleted, so a share never has nowhere to go.
    var personal: MapSummary? { maps.first(where: \.isPersonal) }

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        guard let fetched = try? await APIClient.shared.maps() else { return }
        maps = fetched
        CurrentMap.name = fetched.first { $0.id == currentID }?.name

        // The selected map can vanish underneath us — the owner deleted it, or
        // we left it on another device. Fall back rather than showing nothing.
        if currentID == nil || !fetched.contains(where: { $0.id == currentID }) {
            currentID = (personal ?? fetched.first)?.id
        }
    }

    @discardableResult
    func create(name: String, emoji: String?) async throws -> MapSummary {
        let created = try await APIClient.shared.createMap(name: name, emoji: emoji)
        await refresh()
        currentID = created.id
        return created
    }

    func rename(_ map: MapSummary, to name: String) async throws {
        try await APIClient.shared.renameMap(id: map.id, name: name)
        await refresh()
    }

    /// Owner deletes for everyone; a member leaves. The UI must say which.
    func deleteOrLeave(_ map: MapSummary) async throws {
        try await APIClient.shared.deleteOrLeaveMap(id: map.id)
        if currentID == map.id { currentID = nil }
        await refresh()
    }

    @discardableResult
    func join(code: String) async throws -> MapSummary {
        let joined = try await APIClient.shared.joinMap(code: code)
        await refresh()
        currentID = joined.id
        return joined
    }
}
