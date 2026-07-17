import SharedKit
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Receives a share from Instagram / TikTok / YouTube, extracts the link, and
/// submits it to the backend. Deliberately tiny: all heavy work is server-side,
/// and extensions are memory-limited. If the network call fails, the link is
/// queued in the App Group and the main app submits it on next launch.
final class ShareViewController: UIViewController {
    private let state = ShareState()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear
        let hosting = UIHostingController(rootView: ShareConfirmView(state: state))
        hosting.view.backgroundColor = .clear
        addChild(hosting)
        hosting.view.frame = view.bounds
        hosting.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(hosting.view)
        hosting.didMove(toParent: self)

        Task { await handleShare() }
    }

    private func handleShare() async {
        guard let raw = await extractSharedText(),
              let link = LinkValidator.firstSupportedLink(in: raw) else {
            state.phase = .unsupported
            return finish(after: 1.4)
        }
        do {
            // Submit under the shared session; the reel now appears in the
            // user's activity feed (GET /reels), which the app polls on open.
            _ = try await APIClient.shared.submitReel(url: link)
            state.phase = .saved
        } catch {
            // Offline or backend unreachable — hand off to the main app.
            PendingQueue.enqueue(link)
            state.phase = .queued
        }
        finish(after: 1.0)
    }

    /// Shared payloads arrive as URL or plain-text items depending on the app.
    private func extractSharedText() async -> String? {
        guard let items = extensionContext?.inputItems as? [NSExtensionItem] else { return nil }
        for item in items {
            for provider in item.attachments ?? [] {
                if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
                   let loaded = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier),
                   let url = loaded as? URL {
                    return url.absoluteString
                }
                if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
                   let loaded = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier),
                   let s = loaded as? String {
                    return s
                }
            }
        }
        return nil
    }

    private func finish(after seconds: Double) {
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { [weak self] in
            self?.extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
        }
    }
}

// MARK: - UI

@MainActor
final class ShareState: ObservableObject {
    enum Phase { case working, saved, queued, unsupported }
    @Published var phase: Phase = .working
}

private struct ShareConfirmView: View {
    @ObservedObject var state: ShareState

    var body: some View {
        VStack(spacing: 12) {
            switch state.phase {
            case .working:
                ProgressView()
                Text("Saving to ReelMap…").font(.headline)
            case .saved:
                Image(systemName: "checkmark.circle.fill")
                    .font(.largeTitle).foregroundStyle(.green)
                Text("Analyzing — pins coming up").font(.headline)
            case .queued:
                Image(systemName: "tray.and.arrow.down.fill")
                    .font(.largeTitle).foregroundStyle(.secondary)
                Text("Saved — will analyze when you open ReelMap").font(.headline)
            case .unsupported:
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.largeTitle).foregroundStyle(.orange)
                Text("Share an Instagram, TikTok, or YouTube link").font(.headline)
            }
        }
        .multilineTextAlignment(.center)
        .padding(28)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
