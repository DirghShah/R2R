import Foundation

/// Client-side mirror of the backend's `parse_source` — validates that a string
/// is a supported Instagram / TikTok / YouTube link before we ever hit the API.
public enum ReelPlatform: String, Sendable {
    case instagram = "Instagram"
    case tiktok = "TikTok"
    case youtube = "YouTube"
}

public enum LinkValidator {
    private static let patterns: [(ReelPlatform, NSRegularExpression)] = {
        let raw: [(ReelPlatform, String)] = [
            (.instagram, #"instagram\.com/(reel|reels|p|tv)/[A-Za-z0-9_-]+"#),
            (.tiktok, #"tiktok\.com/@[\w.]+/video/\d+"#),
            (.tiktok, #"(vm|vt)\.tiktok\.com/[A-Za-z0-9]+"#),
            (.tiktok, #"tiktok\.com/t/[A-Za-z0-9]+"#),
            (.youtube, #"youtube\.com/shorts/[A-Za-z0-9_-]+"#),
            (.youtube, #"youtube\.com/watch\?v=[A-Za-z0-9_-]+"#),
            (.youtube, #"youtu\.be/[A-Za-z0-9_-]+"#),
        ]
        return raw.compactMap { platform, pattern in
            (try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]))
                .map { (platform, $0) }
        }
    }()

    /// The platform of a supported link, or nil if the text isn't one.
    public static func platform(of text: String) -> ReelPlatform? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let range = NSRange(trimmed.startIndex..., in: trimmed)
        for (platform, regex) in patterns
        where regex.firstMatch(in: trimmed, range: range) != nil {
            return platform
        }
        return nil
    }

    /// Extracts the first supported link out of arbitrary shared text
    /// (share sheets often wrap the URL in a sentence).
    public static func firstSupportedLink(in text: String) -> String? {
        guard let detector = try? NSDataDetector(
            types: NSTextCheckingResult.CheckingType.link.rawValue) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        for match in detector.matches(in: text, range: range) {
            if let url = match.url, platform(of: url.absoluteString) != nil {
                return url.absoluteString
            }
        }
        return platform(of: text) != nil ? text : nil
    }
}
