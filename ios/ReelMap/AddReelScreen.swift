import SharedKit
import SwiftData
import SwiftUI

/// Fine-dining intake screen: a calm, tasteful, wordless composition. Paste a
/// reel link, tap to analyze. Same backend pipeline as everywhere else.
struct AddReelScreen: View {
    @Environment(\.modelContext) private var context
    @FocusState private var focused: Bool
    @State private var url = ""
    @State private var phase: Phase = .idle

    enum Phase: Equatable { case idle, working, done(Int), failed }

    // Palette — deep charcoal-green plate with champagne gold.
    private static let plate = Color(red: 0.07, green: 0.09, blue: 0.08)
    private static let plateDeep = Color(red: 0.10, green: 0.15, blue: 0.13)
    private static let gold = Color(red: 0.83, green: 0.69, blue: 0.42)
    private static let cream = Color(red: 0.93, green: 0.91, blue: 0.86)

    var body: some View {
        ZStack {
            background
            VStack(spacing: 34) {
                Spacer()
                emblem
                field
                analyzeButton
                status
                Spacer()
                Spacer()
            }
            .padding(.horizontal, 36)
        }
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button { focused = false } label: { Image(systemName: "checkmark") }
                    .tint(Self.gold)
            }
        }
    }

    // MARK: Background

    private var background: some View {
        ZStack {
            LinearGradient(colors: [Self.plate, Self.plateDeep],
                           startPoint: .top, endPoint: .bottom)
            RadialGradient(colors: [Self.gold.opacity(0.10), .clear],
                           center: .top, startRadius: 0, endRadius: 360)
        }
        .ignoresSafeArea()
        .contentShape(Rectangle())
        .onTapGesture { focused = false }
    }

    // MARK: Emblem (culinary, replaces the reel icon)

    private var emblem: some View {
        ZStack {
            Circle().stroke(Self.gold.opacity(0.35), lineWidth: 1).frame(width: 116, height: 116)
            Circle().stroke(Self.gold.opacity(0.7), lineWidth: 1.5).frame(width: 92, height: 92)
            Image(systemName: "fork.knife")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(Self.gold)
        }
    }

    // MARK: Input

    private var field: some View {
        HStack(spacing: 12) {
            Image(systemName: "link").font(.callout).foregroundStyle(Self.cream.opacity(0.45))
            TextField("", text: $url, prompt:
                        Text(verbatim: "instagram.com/reel/…")
                            .foregroundColor(Self.cream.opacity(0.35)))
                .foregroundStyle(Self.cream)
                .tint(Self.gold)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .submitLabel(.go)
                .focused($focused)
                .onSubmit { focused = false; Task { await submit() } }
            Button {
                if let s = UIPasteboard.general.string { url = s }
                focused = false
            } label: {
                Image(systemName: "doc.on.clipboard").font(.callout).foregroundStyle(Self.gold)
            }
        }
        .padding(.vertical, 16).padding(.horizontal, 20)
        .background(Color.white.opacity(0.04), in: Capsule())
        .overlay(Capsule().strokeBorder(Self.gold.opacity(0.30), lineWidth: 1))
    }

    // MARK: Action (icon-only)

    private var analyzeButton: some View {
        Button { focused = false; Task { await submit() } } label: {
            ZStack {
                Circle()
                    .fill(LinearGradient(colors: [Self.gold, Color(red: 0.72, green: 0.57, blue: 0.30)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 66, height: 66)
                    .shadow(color: Self.gold.opacity(0.35), radius: 12, y: 4)
                if phase == .working {
                    ProgressView().tint(Self.plate)
                } else {
                    Image(systemName: "arrow.right")
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(Self.plate)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(url.isEmpty || phase == .working)
        .opacity(url.isEmpty ? 0.45 : 1)
        .animation(.easeInOut, value: url.isEmpty)
    }

    // MARK: Status (wordless)

    @ViewBuilder private var status: some View {
        switch phase {
        case .idle, .working:
            Color.clear.frame(height: 28)
        case .done(let n):
            HStack(spacing: 8) {
                Image(systemName: "checkmark.seal.fill").foregroundStyle(Self.gold)
                Image(systemName: "mappin.and.ellipse").foregroundStyle(Self.cream.opacity(0.8))
                Text("\(n)").font(.headline.monospacedDigit()).foregroundStyle(Self.cream)
            }
            .frame(height: 28)
            .transition(.opacity)
        case .failed:
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(Color(red: 0.85, green: 0.55, blue: 0.30))
                .frame(height: 28)
                .transition(.opacity)
        }
    }

    // MARK: Flow

    private func submit() async {
        let link = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !link.isEmpty else { return }
        withAnimation { phase = .working }
        do {
            let submitted = try await APIClient.shared.submitReel(url: link)
            try await poll(submitted.reelID)
        } catch {
            withAnimation { phase = .failed }
        }
    }

    private func poll(_ reelID: String) async throws {
        for _ in 0..<40 {
            try await Task.sleep(for: .seconds(2))
            let s = try await APIClient.shared.reelStatus(reelID)
            if s.status == "done" {
                url = ""
                await Syncer.refresh(context)
                withAnimation { phase = .done(s.placeCount) }
                return
            } else if s.status == "failed" {
                withAnimation { phase = .failed }
                return
            }
        }
        withAnimation { phase = .done(0) }
    }
}
