import SharedKit
import SwiftData
import SwiftUI

/// Paste an Instagram reel link (Instagram → Share → Copy link) and analyze it.
/// Same backend pipeline as the native share sheet — works on a free account.
struct AddReelScreen: View {
    @Environment(\.modelContext) private var context
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
            }
            .navigationTitle("Add a place")
        }
    }

    private var hero: some View {
        VStack(spacing: 8) {
            Image(systemName: "sparkles.rectangle.stack.fill")
                .font(.system(size: 40)).foregroundStyle(.tint)
            Text("Paste a reel, get a pin").font(.title2.bold())
            Text("In Instagram tap Share → Copy link, then paste it here. We pull out every place and drop it on your map.")
                .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(.top, 8)
    }

    private var inputCard: some View {
        VStack(spacing: 12) {
            TextField("https://www.instagram.com/reel/…", text: $url, axis: .vertical)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .lineLimit(1...3)
            Divider()
            Button {
                if let s = UIPasteboard.general.string { url = s }
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
        Button { Task { await submit() } } label: {
            HStack {
                if isWorking { ProgressView().tint(.white); Spacer().frame(width: 8) }
                Text("Analyze reel").font(.headline)
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
        phase = .working("Submitting…")
        do {
            let submitted = try await APIClient.shared.submitReel(url: url)
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
                await Syncer.refresh(context)   // pull the new pins into the cache
                return
            case "failed":
                phase = .failed("Couldn't analyze that reel. Try another."); return
            default:
                phase = .working("Analyzing… (\(s.status))")
            }
        }
        phase = .working("Still working — check the Map shortly.")
    }
}
