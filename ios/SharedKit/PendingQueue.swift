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

/// Reels the Share Extension successfully submitted that are still being
/// analyzed. The main app polls these on foreground so the user sees an
/// "analyzing…" banner and the pins appear without any manual refresh.
public enum InFlightReels {
    private static let key = "inflight_reels"
    private static var defaults: UserDefaults? { UserDefaults(suiteName: AuthStore.appGroup) }

    public static func add(_ reelID: String) {
        var list = defaults?.stringArray(forKey: key) ?? []
        guard !list.contains(reelID) else { return }
        list.append(reelID)
        defaults?.set(list, forKey: key)
    }

    public static func all() -> [String] {
        defaults?.stringArray(forKey: key) ?? []
    }

    public static func remove(_ reelID: String) {
        var list = defaults?.stringArray(forKey: key) ?? []
        list.removeAll { $0 == reelID }
        defaults?.set(list, forKey: key)
    }
}
