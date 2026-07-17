import Foundation

/// App-Group-backed queue for links the Share Extension couldn't submit
/// (offline / backend unreachable). The main app drains it on launch.
public enum PendingQueue {
    private static let key = "pending_reels"
    private static var defaults: UserDefaults? { UserDefaults(suiteName: AuthStore.appGroup) }

    public static func enqueue(_ url: String) {
        var list = defaults?.stringArray(forKey: key) ?? []
        guard !list.contains(url) else { return }
        list.append(url)
        defaults?.set(list, forKey: key)
    }

    public static func drain() -> [String] {
        let list = defaults?.stringArray(forKey: key) ?? []
        defaults?.removeObject(forKey: key)
        return list
    }
}
