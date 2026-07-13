import SharedKit
import SwiftData
import SwiftUI

/// Bridges the Share Extension and the app. Every time the app comes to the
/// foreground it: (1) submits links the extension queued while offline,
/// (2) polls reels the extension submitted until they finish — showing an
/// "Analyzing shared reel…" banner — then (3) refreshes the local cache so the
/// new pins appear with no manual action.
@MainActor
final class ShareInbox: ObservableObject {
    enum Banner: Equatable {
        case analyzing
        case added(Int)
        case failed
    }

    @Published var banner: Banner?

    private var syncTask: Task<Void, Never>?

    /// Call on every scene-active transition. Cancels any previous run.
    func activate(_ context: ModelContext) {
        syncTask?.cancel()
        syncTask = Task { await run(context) }
    }

    func deactivate() {
        syncTask?.cancel()
        syncTask = nil
    }

    private func run(_ context: ModelContext) async {
        // 1. Links the extension couldn't submit (offline) — submit them now.
        for url in PendingQueue.drain() {
            if let submitted = try? await APIClient.shared.submitReel(url: url) {
                InFlightReels.add(submitted.reelID)
            }
        }

        // 2. Poll in-flight reels until they all settle (or we're cancelled).
        var placesAdded = 0
        var anyFailed = false
        while !Task.isCancelled, !InFlightReels.all().isEmpty {
            banner = .analyzing
            for reelID in InFlightReels.all() {
                guard let status = try? await APIClient.shared.reelStatus(reelID) else { continue }
                switch status.status {
                case "done":
                    InFlightReels.remove(reelID)
                    placesAdded += status.placeCount
                case "failed":
                    InFlightReels.remove(reelID)
                    anyFailed = true
                default:
                    break  // still pending/processing — keep polling
                }
            }
            if InFlightReels.all().isEmpty { break }
            try? await Task.sleep(for: .seconds(3))
        }
        if Task.isCancelled { return }

        // 3. Refresh the cache so pins/lists reflect whatever just landed.
        await Syncer.refresh(context, force: true)

        if placesAdded > 0 {
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            banner = .added(placesAdded)
        } else if anyFailed {
            banner = .failed
        } else {
            banner = nil
            return
        }
        try? await Task.sleep(for: .seconds(4))
        if !Task.isCancelled { banner = nil }
    }
}
