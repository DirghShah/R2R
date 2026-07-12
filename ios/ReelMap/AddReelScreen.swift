import SharedKit
import SwiftData
import SwiftUI

/// Paste a link from Instagram, TikTok, or YouTube Shorts and analyze it.
/// Tap anywhere outside the field to dismiss the keyboard, then Analyze.
struct AddReelScreen: View {
    @Environment(\.modelContext) private var context
    @FocusState private var focused: Bool
    @State private var url = ""
    @State private var phase: Phase = .idle

    enum Phase: Equatable {
        case idle, working(String), done(Int), failed(String)
    }

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                // Dismiss the keyboard on a tap in the empty area. The gesture
                // lives ONLY on this background layer, so it never competes with
                // the text field (that competition caused the input lag + broke
                // paste). Empty space in the VStack falls through to here.
                Color(.systemBackground)
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture { focused = false }

                VStack(spacing: 22) {
                    hero
                    inputField
                    analyzeButton
                    statusView
                    Spacer(minLength: 0)
                }
                .padding(20)
            }
            .navigationTitle("Add a place")
        }
    }

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

    private var inputField: some View {
        HStack(spacing: 10) {
            TextField("Paste a reel or video link", text: $url)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .submitLabel(.go)
                .focused($focused)
                .onSubmit { focused = false; Task { await submit() } }

            if url.isEmpty {
                // Native paste control: reads the clipboard only on tap (no
                // privacy banner, no long-press edit menu needed). Makes repeat
                // testing of pasted links reliable.
                PasteButton(payloadType: String.self) { strings in
                    if let s = strings.first(where: { !$0.isEmpty }) {
                        url = s.trimmingCharacters(in: .whitespacesAndNewlines)
                        focused = false
                    }
                }
                .labelStyle(.iconOnly)
                .buttonBorderShape(.capsule)
                .tint(.accentColor)
            } else {
                Button {
                    url = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear")
            }
        }
        .padding(16)
        .card(20)
    }

    private var analyzeButton: some View {
        Button { focused = false; Task { await submit() } } label: {
            HStack {
                if isWorking { ProgressView().tint(.white); Spacer().frame(width: 8) }
                Text("Analyze").font(.headline)
            }
            .frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .buttonStyle(.borderedProminent)
        .disabled(url.isEmpty || isWorking)
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

    private var isWorking: Bool { if case .working = phase { return true } else { return false } }

    // MARK: Flow

    private func submit() async {
        let link = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !link.isEmpty else { return }
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
                phase = .done(s.placeCount); url = ""
                await Syncer.refresh(context, force: true)
                return
            case "failed":
                phase = .failed("Couldn't analyze that link. Try another."); return
            default:
                phase = .working("Analyzing… (\(s.status))")
            }
        }
        phase = .working("Still working — check the Map shortly.")
    }
}
