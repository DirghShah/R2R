import SharedKit
import SwiftData
import SwiftUI

/// One field, one button. Type or paste a link from Instagram, TikTok, or
/// YouTube Shorts; Analyze is enabled whenever the field has text and validates
/// the link before submitting (inline error if it isn't a supported link).
///
/// UX invariants:
/// - Nothing overlays or wraps the TextField, so focus is instant and the
///   system long-press Paste menu works.
/// - Tapping anywhere in the empty background dismisses the keyboard.
struct AddReelScreen: View {
    @Environment(\.modelContext) private var context
    @FocusState private var focused: Bool
    @State private var text = ""
    @State private var fieldError: String?
    @State private var phase: Phase = .idle

    enum Phase: Equatable {
        case idle, working(String), done(Int), failed(String)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                // Keyboard dismissal lives ONLY on this background layer —
                // taps on the field or buttons never touch it.
                Color(.systemBackground)
                    .ignoresSafeArea()
                    .onTapGesture { focused = false }

                VStack(spacing: 20) {
                    hero
                    inputSection
                    analyzeButton
                    statusView
                    Spacer(minLength: 0)
                }
                .padding(20)
            }
            .navigationTitle("Add a place")
        }
    }

    // MARK: Pieces

    private var hero: some View {
        VStack(spacing: 10) {
            Image(systemName: "mappin.and.ellipse")
                .font(.system(size: 40, weight: .semibold))
                .foregroundStyle(.tint)
            Text("Paste a link, get a pin").font(.title2.bold())
            Text("From Instagram, TikTok, or YouTube Shorts — we pull out every place and drop it on your map.")
                .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(.top, 8)
    }

    private var inputSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                TextField("Type or paste a link", text: $text)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .submitLabel(.done)
                    .focused($focused)
                    .onSubmit { focused = false }
                    .onChange(of: text) { fieldError = nil }

                if trimmed.isEmpty {
                    // Instagram's "Copy link" often lands on the pasteboard as a
                    // URL payload, not a string — readers that only check
                    // `.string` (or a String-typed PasteButton) silently no-op.
                    // This reads both, so it always works.
                    Button("Paste") {
                        let pb = UIPasteboard.general
                        if let value = pb.url?.absoluteString ?? pb.string {
                            text = value.trimmingCharacters(in: .whitespacesAndNewlines)
                        }
                        focused = false
                    }
                    .font(.subheadline.weight(.semibold))
                    .buttonStyle(.bordered)
                    .buttonBorderShape(.capsule)
                } else {
                    Button {
                        text = ""
                        fieldError = nil
                    } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Clear")
                }
            }
            .padding(.vertical, 12).padding(.horizontal, 16)
            .background(.regularMaterial,
                        in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(fieldError == nil ? Color.primary.opacity(0.06) : .red,
                                  lineWidth: fieldError == nil ? 1 : 1.5))

            if let fieldError {
                Label(fieldError, systemImage: "exclamationmark.circle.fill")
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.15), value: fieldError)
    }

    private var analyzeButton: some View {
        Button {
            focused = false
            analyzeTapped()
        } label: {
            HStack {
                if isWorking { ProgressView().tint(.white); Spacer().frame(width: 8) }
                Text("Analyze").font(.headline)
            }
            .frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .buttonStyle(.borderedProminent)
        .disabled(trimmed.isEmpty || isWorking)
    }

    @ViewBuilder private var statusView: some View {
        switch phase {
        case .idle:
            EmptyView()
        case .working(let msg):
            statusCard(msg, icon: "hourglass", tint: .secondary)
        case .done(let n):
            statusCard("\(n) place\(n == 1 ? "" : "s") saved. Check the Map & Lists tabs.",
                       icon: "checkmark.circle.fill", tint: .green)
        case .failed(let msg):
            statusCard(msg, icon: "exclamationmark.triangle.fill", tint: .orange)
        }
    }

    private func statusCard(_ text: String, icon: String, tint: Color) -> some View {
        Label(text, systemImage: icon)
            .foregroundStyle(tint)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .card(16)
    }

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var isWorking: Bool { if case .working = phase { return true } else { return false } }

    // MARK: Flow

    private func analyzeTapped() {
        // Share sheets sometimes wrap the URL in a sentence — pull the link out.
        guard let link = LinkValidator.firstSupportedLink(in: trimmed) else {
            fieldError = "That doesn't look like an Instagram, TikTok, or YouTube link."
            phase = .idle
            return
        }
        fieldError = nil
        Task { await submit(link) }
    }

    private func submit(_ link: String) async {
        phase = .working("Submitting…")
        do {
            let submitted = try await APIClient.shared.submitReel(url: link)
            phase = .working("Analyzing… (~15–60s)")
            try await poll(submitted.reelID)
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    private func poll(_ reelID: String) async throws {
        for _ in 0..<40 {
            try await Task.sleep(for: .seconds(2))
            let s = try await APIClient.shared.reelStatus(reelID)
            switch s.status {
            case "done":
                phase = .done(s.placeCount)
                text = ""
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                await Syncer.refresh(context, force: true)
                return
            case "failed":
                phase = .failed("Couldn't analyze that link. Try another.")
                return
            default:
                phase = .working("Analyzing… (\(s.status))")
            }
        }
        phase = .working("Still working — check the Map shortly.")
    }
}
