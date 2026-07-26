import Foundation

/// App-Group-backed queue for links the Share Extension couldn't submit
/// (offline / backend unreachable). The main app retries them on launch.
///
/// Reading and removing are deliberately separate operations: the extension
/// told the user the link was saved, so nothing leaves the queue until the
/// backend has actually accepted it.
public enum PendingQueue {
    private static let key = "pending_reels"
    private static var store: UserDefaults {
        UserDefaults(suiteName: AuthStore.appGroup) ?? .standard
    }

    public static func enqueue(_ url: String) {
        var list = store.stringArray(forKey: key) ?? []
        guard !list.contains(url) else { return }
        list.append(url)
        store.set(list, forKey: key)
    }

    /// Links still waiting to reach the backend, oldest first.
    public static func pending() -> [String] {
        store.stringArray(forKey: key) ?? []
    }

    public static func remove(_ url: String) {
        let list = pending().filter { $0 != url }
        if list.isEmpty { store.removeObject(forKey: key) }
        else { store.set(list, forKey: key) }
    }
}
