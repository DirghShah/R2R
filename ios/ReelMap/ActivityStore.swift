import SharedKit
import SwiftData
import SwiftUI

/// The single source of truth for the reel queue/activity feed.
///
/// Backed by the backend `GET /reels` — it lists every reel the user submitted
/// (from the Add tab *or* the Share Extension), newest first, with live status.
/// While any reel is pending/processing it polls; when one finishes it refreshes
/// the SwiftData cache so pins appear, and shows a brief success toast.
///
/// The user never waits: shares are submitted by the extension and processed
/// one-by-one on the server; this just surfaces the status.
@MainActor
final class ActivityStore: ObservableObject {
    @Published private(set) var items: [ReelActivity] = []
    @Published var toast: Toast?
    @Published private(set) var isRefreshing = false

    enum Toast: Equatable { case added(Int), failed }

    var activeCount: Int { items.filter(\.isActive).count }
    var hasItems: Bool { !items.isEmpty }

    private var loopTask: Task<Void, Never>?
    private var seenDone: Set<String> = []
    private var seeded = false

    /// Kick off on launch and every time the app returns to the foreground.
    func resume(_ context: ModelContext) {
        loopTask?.cancel()
        loopTask = Task { await run(context) }
    }

    func pause() {
        loopTask?.cancel()
        loopTask = nil
    }

    /// Manual pull-to-refresh from the Activity sheet.
    func refreshNow(_ context: ModelContext) async {
        await fetchOnce(context)
    }

    // MARK: - Internals

    private func run(_ context: ModelContext) async {
        // Submit links the extension queued while the backend was unreachable.
        for url in PendingQueue.drain() {
            _ = try? await APIClient.shared.submitReel(url: url)
        }
        // Poll while anything is in flight; stop once everything has settled.
        repeat {
            await fetchOnce(context)
            if Task.isCancelled || activeCount == 0 { break }
            try? await Task.sleep(for: .seconds(3))
        } while !Task.isCancelled
    }

    private func fetchOnce(_ context: ModelContext) async {
        isRefreshing = true
        defer { isRefreshing = false }
        guard let list = try? await APIClient.shared.activity() else { return }

        let doneNow = Set(list.filter { $0.status == "done" }.map(\.reelID))
        // First fetch seeds the baseline so we don't toast pre-existing reels.
        let newlyDone = seeded ? doneNow.subtracting(seenDone) : []
        seenDone = doneNow
        seeded = true
        items = list

        if !newlyDone.isEmpty {
            await Syncer.refresh(context, force: true)
            let added = list.filter { newlyDone.contains($0.reelID) }
                .reduce(0) { $0 + $1.placeCount }
            if added > 0 {
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                showToast(.added(added))
            } else if list.contains(where: { newlyDone.contains($0.reelID) && $0.placeCount == 0 }) {
                showToast(.failed)
            }
        }
    }

    private func showToast(_ toast: Toast) {
        self.toast = toast
        Task {
            try? await Task.sleep(for: .seconds(4))
            if self.toast == toast { self.toast = nil }
        }
    }
}
