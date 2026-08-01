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
            return finish(after: 1.6)
        }
        do {
            // Submit under the shared session, into whichever map the user last
            // had open. No picker here on purpose: this is the one-tap path the
            // app exists for, so the destination is shown rather than asked.
            _ = try await APIClient.shared.submitReel(url: link, mapID: CurrentMap.id)
            state.mapName = CurrentMap.name
            state.phase = .saved
            finish(after: 0.9)
        } catch {
            // Keep the link either way — the app drains this queue on next open.
            PendingQueue.enqueue(link)
            // Be honest about *why* it didn't go through.
            state.phase = (error as? APIError)?.isNetwork == true ? .offline : .failed
            finish(after: 2.0)
        }
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
    enum Phase { case working, saved, offline, failed, unsupported }
    @Published var phase: Phase = .working
    @Published var mapName: String?
}

private struct ShareConfirmView: View {
    @ObservedObject var state: ShareState

    var body: some View {
        VStack(spacing: 10) {
            switch state.phase {
            case .working:
                ProgressView()
                Text("Saving to ReelMap…").font(.headline)
            case .saved:
                icon("checkmark.circle.fill", .green)
                Text("Analyzing — pins coming up").font(.headline)
                if let name = state.mapName {
                    Text("Saving to \(name)")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
            case .offline:
                icon("wifi.slash", .orange)
                Text("Can't reach ReelMap").font(.headline)
                Text("Network lost. Saved — it'll upload when your phone can reach the backend again.")
                    .font(.subheadline).foregroundStyle(.secondary)
            case .failed:
                icon("exclamationmark.triangle.fill", .orange)
                Text("Couldn't save that reel").font(.headline)
                Text("Saved to retry — open ReelMap once the backend is reachable.")
                    .font(.subheadline).foregroundStyle(.secondary)
            case .unsupported:
                icon("link.badge.plus", .orange)
                Text("Unsupported link").font(.headline)
                Text("Share an Instagram, TikTok, or YouTube link.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
        }
        .multilineTextAlignment(.center)
        .padding(28)
        .frame(maxWidth: 320)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func icon(_ name: String, _ color: Color) -> some View {
        Image(systemName: name).font(.largeTitle).foregroundStyle(color)
    }
}
