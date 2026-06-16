import Foundation
import Security

/// Stores the app JWT in the shared Keychain access group so the main app and
/// the Share Extension authenticate as the same user.
public enum AuthStore {
    public static let appGroup = "group.com.yourco.reelmap"
    private static let service = "com.yourco.reelmap.auth"
    private static let account = "jwt"

    /// App Groups require the paid Apple Developer Program. Leave this `false` for
    /// the free-account build (the app keeps its token in its own Keychain). Flip
    /// to `true` only when you enable the Share Extension + App Group, so the
    /// extension and app share one session.
    public static let useSharedAccessGroup = false

    public static var token: String? {
        get { read() }
        set { newValue.map(save) ?? delete() }
    }

    private static func baseQuery() -> [String: Any] {
        var q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        if useSharedAccessGroup {
            q[kSecAttrAccessGroup as String] = appGroup
        }
        return q
    }

    private static func save(_ value: String) {
        var query = baseQuery()
        SecItemDelete(query as CFDictionary)
        query[kSecValueData as String] = Data(value.utf8)
        SecItemAdd(query as CFDictionary, nil)
    }

    private static func read() -> String? {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func delete() {
        SecItemDelete(baseQuery() as CFDictionary)
    }
}
