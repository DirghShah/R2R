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
        view.isOpaque = false
        let hosting = UIHostingController(rootView: ShareConfirmView(state: state))
        hosting.view.backgroundColor = .clear
        // backgroundColor alone isn't enough — a hosting controller's view is
        // opaque by default and paints black behind the toast, which is what
        // made a one-line confirmation look like a full-screen takeover.
        hosting.view.isOpaque = false
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
            // Long enough to read one line, short enough that it feels like a
            // confirmation rather than a screen you have to wait out.
            finish(after: 0.75)
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

/// A toast, not a screen.
///
/// This was a centred card inside a full-bleed container, which reads as a
/// modal you have to acknowledge — a lot of ceremony for "got it, it's
/// processing". Sharing a reel should feel like the share sheet closing with a
/// note left behind, so the confirmation is a single compact row pinned to the
/// bottom, sized to its text, over as much of the underlying app as the system
/// will let an extension show.
private struct ShareConfirmView: View {
    @ObservedObject var state: ShareState

    var body: some View {
        VStack {
            Spacer()
            toast
                .padding(.horizontal, 14)
                .padding(.bottom, 14)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .animation(.spring(response: 0.34, dampingFraction: 0.86), value: state.phase)
    }

    private var toast: some View {
        HStack(spacing: 11) {
            leading
                .frame(width: 26, height: 26)
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.primary)
                if let detail {
                    Text(detail)
                        .font(.system(size: 12.5))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 15)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.07))
        )
        .shadow(color: .black.opacity(0.18), radius: 16, y: 6)
    }

    @ViewBuilder private var leading: some View {
        switch state.phase {
        case .working:
            ProgressView().controlSize(.small)
        case .saved:
            icon("checkmark.circle.fill", .green)
        case .offline:
            icon("wifi.slash", .orange)
        case .failed:
            icon("exclamationmark.triangle.fill", .orange)
        case .unsupported:
            icon("link.badge.plus", .orange)
        }
    }

    private var title: String {
        switch state.phase {
        case .working:     return "Saving to Nosh…"
        case .saved:       return "Analyzing — pins coming up"
        case .offline:     return "Can't reach Nosh"
        case .failed:      return "Couldn't save that reel"
        case .unsupported: return "Unsupported link"
        }
    }

    private var detail: String? {
        switch state.phase {
        case .working:     return nil
        case .saved:       return state.mapName.map { "Saving to \($0)" }
        case .offline:     return "Saved — it'll upload when you're back online."
        case .failed:      return "Saved to retry — open Nosh to finish."
        case .unsupported: return "Share an Instagram, TikTok, or YouTube link."
        }
    }

    private func icon(_ name: String, _ color: Color) -> some View {
        Image(systemName: name)
            .font(.system(size: 21, weight: .semibold))
            .foregroundStyle(color)
    }
}
