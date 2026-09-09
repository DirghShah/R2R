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

    /// Presented *over* the app being shared from, not instead of it.
    ///
    /// The host presents this controller, and with the default .fullScreen it
    /// tears the source app out of the hierarchy — so a clear background has
    /// nothing behind it but black, and a small toast ends up floating in a
    /// void. Overriding the getter rather than assigning in viewDidLoad is
    /// what makes it stick: the host reads this before it presents.
    override var modalPresentationStyle: UIModalPresentationStyle {
        get { .overFullScreen }
        set { _ = newValue }
    }

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
            state.platform = SharePlatform(link: link)
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

/// Which platform the link came from, so the confirmation names the thing the
/// user actually shared. "Saved" is vague; "Reel shared" is the receipt.
enum SharePlatform {
    case instagram, tiktok, youtube

    init(link: String) {
        let u = link.lowercased()
        if u.contains("tiktok") { self = .tiktok }
        else if u.contains("youtu") { self = .youtube }
        else { self = .instagram }
    }

    var sharedLabel: String {
        switch self {
        case .instagram: return "Reel shared"
        case .tiktok:    return "TikTok shared"
        case .youtube:   return "Short shared"
        }
    }
}

@MainActor
final class ShareState: ObservableObject {
    enum Phase { case working, saved, offline, failed, unsupported }
    @Published var phase: Phase = .working
    @Published var mapName: String?
    @Published var platform: SharePlatform = .instagram
}

/// A success toast, not a sheet.
///
/// Sharing a reel is a one-tap action with a one-line outcome, so the
/// confirmation is a small rounded box floating in the middle of whatever app
/// you shared from. It is sized to its own text rather than to the screen, and
/// the backdrop is barely there — the point is that the app underneath is still
/// visible and you are still in it.
private struct ShareConfirmView: View {
    @ObservedObject var state: ShareState

    var body: some View {
        ZStack {
            // Just enough to lift the box off a bright photo. Any more and it
            // reads as a modal that has taken the screen.
            Color.black.opacity(0.12).ignoresSafeArea()
            toast
                .padding(.horizontal, 40)
                .transition(.scale(scale: 0.92).combined(with: .opacity))
        }
        .animation(.spring(response: 0.32, dampingFraction: 0.85), value: state.phase)
    }

    private var toast: some View {
        VStack(spacing: 9) {
            leading
                .frame(width: 34, height: 34)
            Text(title)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(.primary)
            if let detail {
                Text(detail)
                    .font(.system(size: 12.5))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .multilineTextAlignment(.center)
        .padding(.horizontal, 24)
        .padding(.vertical, 20)
        // Sized to the text, with a floor so a two-word confirmation isn't a
        // cramped little tag.
        .frame(minWidth: 190)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.07))
        )
        .shadow(color: .black.opacity(0.22), radius: 24, y: 8)
    }

    @ViewBuilder private var leading: some View {
        switch state.phase {
        case .working:
            ProgressView()
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
        case .working:     return "Saving…"
        case .saved:       return state.platform.sharedLabel
        case .offline:     return "Can't reach Nosh"
        case .failed:      return "Couldn't save that"
        case .unsupported: return "Unsupported link"
        }
    }

    private var detail: String? {
        switch state.phase {
        case .working:     return nil
        case .saved:
            guard let name = state.mapName else { return "Analyzing — pins coming up" }
            return "Analyzing — pins coming to \(name)"
        case .offline:     return "Saved — it'll upload when you're back online."
        case .failed:      return "Saved to retry — open Nosh to finish."
        case .unsupported: return "Share an Instagram, TikTok, or YouTube link."
        }
    }

    private func icon(_ name: String, _ color: Color) -> some View {
        Image(systemName: name)
            .font(.system(size: 30, weight: .semibold))
            .foregroundStyle(color)
    }
}
