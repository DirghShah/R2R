import Foundation
import SharedKit
import SwiftData

/// Builds the SwiftData container.
///
/// Two things this does that the one-line `ModelContainer(for:)` did not:
///
/// 1. **Creates the store directory first.** With an app-group entitlement
///    present, SwiftData puts the store in the group container — but nothing
///    creates `Library/Application Support` in there. Every launch failed to
///    open the store, logged a multi-hundred-line filesystem diagnostic,
///    recovered, and only then rendered. That whole dance is synchronous and
///    happens before the first frame.
///
/// 2. **Doesn't crash on a bad store.** Everything cached here is derived from
///    the server, so an unopenable store is a nuisance, not data loss. Rebuild
///    it; if even that fails, run in memory so the app still works.
enum LocalStore {
    static func makeContainer() -> ModelContainer {
        let schema = Schema([CachedPlace.self, CachedList.self, PlaceMark.self])
        let url = storeURL()

        if let url {
            try? FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            if let container = try? ModelContainer(
                for: schema, configurations: ModelConfiguration(url: url)) {
                return container
            }
            // Corrupt or written by an incompatible schema — throw it away and
            // let the next sync repopulate from the server.
            removeStore(at: url)
            if let container = try? ModelContainer(
                for: schema, configurations: ModelConfiguration(url: url)) {
                return container
            }
        }

        // Last resort: no cache, no offline mode, but a working app.
        return try! ModelContainer(
            for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
    }

    /// Same path SwiftData was already using, so existing caches survive.
    private static func storeURL() -> URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: AuthStore.appGroup)?
            .appending(path: "Library/Application Support/default.store")
    }

    /// SQLite keeps `-wal` and `-shm` sidecars; leaving them behind would make
    /// the retry fail exactly the same way.
    private static func removeStore(at url: URL) {
        for suffix in ["", "-wal", "-shm"] {
            try? FileManager.default.removeItem(
                at: url.deletingLastPathComponent()
                    .appending(path: url.lastPathComponent + suffix))
        }
    }
}
