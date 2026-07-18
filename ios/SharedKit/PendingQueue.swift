import Foundation

/// App-Group-backed queue for links the Share Extension couldn't submit
/// (offline / backend unreachable). The main app drains it on launch.
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

    public static func drain() -> [String] {
        let list = store.stringArray(forKey: key) ?? []
        store.removeObject(forKey: key)
        return list
    }
}
