import Foundation

/// Stores the session JWT in the App Group's shared UserDefaults so the main app
/// and the Share Extension read the same token (they run in separate processes).
///
/// We use the App Group container rather than a shared Keychain group on purpose:
/// keychain sharing needs a `keychain-access-groups` entitlement (separate from
/// the App Group), and getting that wrong silently fails every read/write. The
/// App Group is already required for the extension, so this "just works".
///
/// Note: a bearer JWT in App Group UserDefaults is readable by our own app +
/// extension only. Before App Store release, move to a Keychain access group for
/// at-rest encryption (see the README release checklist).
public enum AuthStore {
    public static let appGroup = "group.com.yourco.reelmap"
    private static let key = "auth_jwt"

    /// App Group suite when available; falls back to standard defaults (app-only)
    /// if the App Group isn't configured yet, so the app still works standalone.
    private static var store: UserDefaults {
        UserDefaults(suiteName: appGroup) ?? .standard
    }

    public static var token: String? {
        get { store.string(forKey: key) }
        set {
            if let newValue {
                store.set(newValue, forKey: key)
            } else {
                store.removeObject(forKey: key)
            }
        }
    }
}
