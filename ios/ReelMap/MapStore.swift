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

    /// The single in-flight refresh. Launch drives this from two places that
    /// race — `startSession()` and the `scenePhase == .active` handler — and
    /// duplicate `/maps` calls were visible in the request log every cold start.
    private var refreshTask: Task<Void, Never>?
    private var generation = 0

    init() {
        currentID = CurrentMap.id
    }

    var current: MapSummary? {
        maps.first { $0.id == currentID } ?? maps.first
    }

    /// The personal map is the safe fallback — it always exists and can't be
    /// deleted, so a share never has nowhere to go.
    var personal: MapSummary? { maps.first(where: \.isPersonal) }

    /// `force` reloads even if a fetch is already running — needed after a local
    /// mutation, because an in-flight response predates it and would overwrite
    /// the optimistic row we just added.
    func refresh(force: Bool = false) async {
        if let inFlight = refreshTask {
            await inFlight.value
            if !force { return }
        }
        generation += 1
        let mine = generation
        let task = Task { await load() }
        refreshTask = task
        await task.value
        if generation == mine { refreshTask = nil }
    }

    private func load() async {
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
        // Show it immediately and reconcile in the background — waiting on a
        // second round trip before the sheet closes is the difference between
        // "instant" and "laggy".
        maps.append(created)
        currentID = created.id
        Task { await refresh(force: true) }
        return created
    }

    func rename(_ map: MapSummary, to name: String) async throws {
        try await APIClient.shared.renameMap(id: map.id, name: name)
        await refresh(force: true)
    }

    /// Owner deletes for everyone; a member leaves. The UI must say which.
    func deleteOrLeave(_ map: MapSummary) async throws {
        try await APIClient.shared.deleteOrLeaveMap(id: map.id)
        maps.removeAll { $0.id == map.id }
        if currentID == map.id { currentID = (personal ?? maps.first)?.id }
        Task { await refresh(force: true) }
    }

    @discardableResult
    func join(code: String) async throws -> MapSummary {
        let joined = try await APIClient.shared.joinMap(code: code)
        if !maps.contains(where: { $0.id == joined.id }) { maps.append(joined) }
        currentID = joined.id
        Task { await refresh(force: true) }
        return joined
    }
}
