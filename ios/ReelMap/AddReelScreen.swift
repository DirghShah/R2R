import SharedKit
import SwiftData
import SwiftUI

/// Paste a link from Instagram, TikTok, or YouTube Shorts and analyze it — the
/// same backend pipeline as the native share sheet. Consistent material theme.
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
            ScrollView {
                VStack(spacing: 22) {
                    hero
                    inputCard
                    analyzeButton
                    statusView
                }
                .padding(20)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
                .onTapGesture { focused = false }
            }
            .scrollDismissesKeyboard(.immediately)
            .navigationTitle("Add a place")
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { focused = false }
                }
            }
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
            platformRow
        }
        .padding(.top, 8)
    }

    private var platformRow: some View {
        HStack(spacing: 18) {
            Label("Instagram", systemImage: "camera.fill")
            Label("TikTok", systemImage: "music.note")
            Label("Shorts", systemImage: "play.rectangle.fill")
        }
        .labelStyle(.iconOnly)
        .font(.title3)
        .foregroundStyle(.secondary)
        .padding(.top, 2)
    }

    private var inputCard: some View {
        VStack(spacing: 12) {
            TextField("Paste a reel or video link", text: $url)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .submitLabel(.go)
                .focused($focused)
                .onSubmit { focused = false; Task { await submit() } }
            Divider()
            Button {
                if let s = UIPasteboard.general.string { url = s }
                focused = false
            } label: {
                Label("Paste from clipboard", systemImage: "doc.on.clipboard")
                    .font(.subheadline.weight(.medium))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
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
                await Syncer.refresh(context)
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
