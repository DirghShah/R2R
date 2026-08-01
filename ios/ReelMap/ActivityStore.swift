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

    enum Toast: Equatable { case added(Int), noPlaces, failed }

    var activeCount: Int { items.filter(\.isActive).count }
    var hasItems: Bool { !items.isEmpty }

    private var loopTask: Task<Void, Never>?
    /// Reels already reported on (done *or* failed), so each settles once.
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
        await submitQueuedLinks()
        // Poll while anything is in flight; stop once everything has settled.
        repeat {
            await fetchOnce(context)
            if Task.isCancelled || activeCount == 0 { break }
            try? await Task.sleep(for: .seconds(3))
        } while !Task.isCancelled
    }

    /// Retry links the Share Extension couldn't submit. A link only leaves the
    /// queue once the backend has taken it (or definitively rejected it) —
    /// dropping it on a network failure would silently lose a share the
    /// extension already told the user was saved.
    private func submitQueuedLinks() async {
        for url in PendingQueue.pending() {
            do {
                _ = try await APIClient.shared.submitReel(url: url, mapID: CurrentMap.id)
                PendingQueue.remove(url)
                // A link shared from Instagram is exactly the case push exists
                // for — the user isn't in the app to watch it finish.
                await PushManager.shared.requestOnFirstReel()
            } catch let error as APIError where !error.isNetwork {
                // The backend saw it and said no (unsupported link, over quota).
                // Retrying forever would wedge the queue behind a dead link.
                PendingQueue.remove(url)
            } catch {
                // Still unreachable — keep this and everything after it.
                break
            }
        }
    }

    private func fetchOnce(_ context: ModelContext) async {
        isRefreshing = true
        defer { isRefreshing = false }
        guard let list = try? await APIClient.shared.activity() else { return }

        // Track failures too: a reel that errored used to settle silently, so
        // the only way to find out was to go looking in the Add tab.
        let settledNow = Set(list.filter { !$0.isActive }.map(\.reelID))
        // First fetch seeds the baseline so we don't toast pre-existing reels.
        let newlySettled = seeded ? settledNow.subtracting(seenDone) : []
        seenDone = settledNow
        seeded = true
        items = list

        guard !newlySettled.isEmpty else { return }
        let finished = list.filter { newlySettled.contains($0.reelID) }
        let succeeded = finished.filter { $0.status == "done" }

        if !succeeded.isEmpty { await Syncer.refresh(context, force: true) }

        let added = succeeded.reduce(0) { $0 + $1.placeCount }
        if added > 0 {
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            showToast(.added(added))
        } else if finished.contains(where: { $0.status == "failed" }) {
            UINotificationFeedbackGenerator().notificationOccurred(.error)
            showToast(.failed)
        } else if !succeeded.isEmpty {
            // Analyzed fine, just no venues in it. Saying "couldn't analyze"
            // here (as we used to) blames the app for an empty reel.
            showToast(.noPlaces)
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
