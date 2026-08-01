import Foundation
import Security

/// The session, shared between the main app and the Share Extension.
///
/// Split on purpose:
/// - the **access token** is short-lived and lives in App Group `UserDefaults`
/// - the **refresh token** is long-lived and lives in a shared **Keychain**
///   group, because it is the credential that can mint new sessions
///
/// The refresh token matters more than it looks: the Share Extension runs in its
/// own process and can never present sign-in UI, so when the access token
/// expires mid-share it has no interactive way back. Without a refresh token it
/// could only ever queue the link and hope.
public enum AuthStore {
    public static let appGroup = "group.com.yourco.reelmap"
    /// Must match `keychain-access-groups` in BOTH targets' entitlements.
    public static let keychainGroup = "$(AppIdentifierPrefix)com.yourco.reelmap"

    private static let accessKey = "auth_jwt"
    private static let refreshKey = "auth_refresh"
    private static let userIDKey = "auth_user_id"

    private static var defaults: UserDefaults {
        UserDefaults(suiteName: appGroup) ?? .standard
    }

    // MARK: Access token

    public static var token: String? {
        get { defaults.string(forKey: accessKey) }
        set {
            if let newValue { defaults.set(newValue, forKey: accessKey) }
            else { defaults.removeObject(forKey: accessKey) }
        }
    }

    /// Cached so the UI can tell "you" from other members without a round trip.
    public static var userID: String? {
        get { defaults.string(forKey: userIDKey) }
        set {
            if let newValue { defaults.set(newValue, forKey: userIDKey) }
            else { defaults.removeObject(forKey: userIDKey) }
        }
    }

    public static var isSignedIn: Bool { token != nil || refreshToken != nil }

    // MARK: Refresh token (Keychain)

    public static var refreshToken: String? {
        get { keychainRead(refreshKey) }
        set {
            if let newValue { keychainWrite(refreshKey, newValue) }
            else { keychainDelete(refreshKey) }
        }
    }

    public static func signOut() {
        token = nil
        userID = nil
        refreshToken = nil
    }

    // MARK: Keychain

    /// The access group is only usable when the entitlement is actually present.
    /// On a build without it the query fails with errSecMissingEntitlement and
    /// would silently sign the user out on every launch — so each operation
    /// retries without the group rather than losing the session.
    private static func baseQuery(_ key: String, useGroup: Bool) -> [String: Any] {
        var q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.yourco.reelmap.auth",
            kSecAttrAccount as String: key,
        ]
        if useGroup { q[kSecAttrAccessGroup as String] = keychainGroup }
        return q
    }

    private static func keychainRead(_ key: String) -> String? {
        for useGroup in [true, false] {
            var query = baseQuery(key, useGroup: useGroup)
            query[kSecReturnData as String] = true
            query[kSecMatchLimit as String] = kSecMatchLimitOne

            var item: CFTypeRef?
            if SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
               let data = item as? Data,
               let value = String(data: data, encoding: .utf8) {
                return value
            }
        }
        return nil
    }

    private static func keychainWrite(_ key: String, _ value: String) {
        guard let data = value.data(using: .utf8) else { return }
        for useGroup in [true, false] {
            let query = baseQuery(key, useGroup: useGroup)
            SecItemDelete(query as CFDictionary)

            var insert = query
            insert[kSecValueData as String] = data
            // Readable after first unlock so the Share Extension can reach it in
            // the background; never synced to other devices.
            insert[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
            if SecItemAdd(insert as CFDictionary, nil) == errSecSuccess { return }
        }
    }

    private static func keychainDelete(_ key: String) {
        for useGroup in [true, false] {
            SecItemDelete(baseQuery(key, useGroup: useGroup) as CFDictionary)
        }
    }
}


/// Which map the user is currently looking at.
///
/// Lives in SharedKit and the App Group because the **Share Extension** reads
/// it: a share has to land on the map the user actually has open, and the
/// extension can't ask — it has no UI budget for a picker on the one-tap path.
public enum CurrentMap {
    private static let idKey = "current_map_id"
    private static let nameKey = "current_map_name"

    private static var store: UserDefaults? { UserDefaults(suiteName: AuthStore.appGroup) }

    public static var id: String? {
        get { store?.string(forKey: idKey) }
        set {
            if let newValue { store?.set(newValue, forKey: idKey) }
            else { store?.removeObject(forKey: idKey) }
        }
    }

    /// Shown on the share confirmation card so the destination is never a
    /// surprise.
    public static var name: String? {
        get { store?.string(forKey: nameKey) }
        set {
            if let newValue { store?.set(newValue, forKey: nameKey) }
            else { store?.removeObject(forKey: nameKey) }
        }
    }

    public static func clear() {
        id = nil
        name = nil
    }
}
