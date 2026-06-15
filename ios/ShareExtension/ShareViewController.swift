import SharedKit
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Receives an Instagram reel share, extracts the URL, and submits it to the
/// backend. Stays intentionally tiny — all heavy work is server-side.
final class ShareViewController: UIViewController {
    override func viewDidLoad() {
        super.viewDidLoad()
        let hosting = UIHostingController(rootView: ShareConfirmView())
        addChild(hosting)
        hosting.view.frame = view.bounds
        hosting.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(hosting.view)
        hosting.didMove(toParent: self)

        Task { await handleShare() }
    }

    private func handleShare() async {
        guard let url = await extractURL() else { return finish(success: false) }
        do {
            _ = try await APIClient.shared.submitReel(url: url.absoluteString)
            finish(success: true)
        } catch {
            // Offline / failure: queue locally for the app to retry on next launch.
            PendingQueue.enqueue(url.absoluteString)
            finish(success: true)
        }
    }

    private func extractURL() async -> URL? {
        guard let items = extensionContext?.inputItems as? [NSExtensionItem] else { return nil }
        for item in items {
            for provider in item.attachments ?? [] {
                if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
                   let u = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL {
                    return u
                }
                if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
                   let s = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String,
                   let u = firstURL(in: s) {
                    return u
                }
            }
        }
        return nil
    }

    private func firstURL(in text: String) -> URL? {
        let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        let range = NSRange(text.startIndex..., in: text)
        return detector?.firstMatch(in: text, range: range)?.url
    }

    private func finish(success: Bool) {
        DispatchQueue.main.asyncAfter(deadline: .now() + (success ? 0.8 : 0.2)) {
            self.extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
        }
    }
}

private struct ShareConfirmView: View {
    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "mappin.and.ellipse").font(.largeTitle)
            Text("Saving to ReelMap…").font(.headline)
            ProgressView()
        }
        .padding(40)
    }
}

/// Local fallback queue (App Group) for shares submitted while offline.
enum PendingQueue {
    private static let key = "pending_reels"
    private static var defaults: UserDefaults? { UserDefaults(suiteName: AuthStore.appGroup) }

    static func enqueue(_ url: String) {
        var list = defaults?.stringArray(forKey: key) ?? []
        list.append(url)
        defaults?.set(list, forKey: key)
    }

    static func drain() -> [String] {
        let list = defaults?.stringArray(forKey: key) ?? []
        defaults?.removeObject(forKey: key)
        return list
    }
}
