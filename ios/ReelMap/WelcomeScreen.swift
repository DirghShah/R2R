import SharedKit
import SwiftData
import SwiftUI

/// The first thirty seconds.
///
/// Two first-time testers opened this app, found an empty map, and had no idea
/// what to do next — and one of them doesn't use social media at all, so every
/// path in was closed to him. This exists so nobody lands on nothing.
///
/// One screen, not a carousel, and every option ends with something actually on
/// the map. Trying the example is first because it is the only one that
/// requires nothing from the person and shows them the real output in about a
/// second: the reel is already analysed, so the backend copies its places
/// across without fetching, extracting or geocoding anything.
struct WelcomeScreen: View {
    @EnvironmentObject private var maps: MapStore
    @Environment(\.modelContext) private var context
    @Environment(\.colorScheme) private var scheme

    /// What the person chose, so the caller can open the right thing after.
    enum Next { case example, pasteLink, search, skip }
    var onFinish: (Next) -> Void

    @State private var running = false
    @State private var exampleFailed = false

    private var ground: Color { scheme == .dark ? .black : .white }
    private var ink: Color { scheme == .dark ? .white : .black }

    var body: some View {
        ZStack {
            ground.ignoresSafeArea()
            VStack(spacing: 0) {
                Spacer(minLength: 20)
                header
                VStack(spacing: 12) {
                    exampleCard
                    card(icon: "link", title: "Paste a reel link",
                         detail: "Got one already? Drop it in and watch it work.") {
                        onFinish(.pasteLink)
                    }
                    card(icon: "magnifyingglass", title: "Search for a place",
                         detail: "Add somewhere you've already been. No reel needed.") {
                        onFinish(.search)
                    }
                }
                .padding(.top, 32)
                Spacer()
                footer
            }
            .padding(.horizontal, 26)
            .padding(.bottom, 26)
        }
        .interactiveDismissDisabled(running)
    }

    private var header: some View {
        VStack(spacing: 14) {
            Image("Wordmark")
                .renderingMode(.template).resizable().scaledToFit()
                .frame(height: 38).foregroundStyle(ink)
                .accessibilityLabel("Nosh")
            Text("Nosh turns food reels into map pins.\nStart however you like.")
                .font(.system(size: 16))
                .foregroundStyle(ink.opacity(0.55))
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// Deliberately explicit that this adds real, deletable places. An example
    /// that quietly puts things on your map is a trick, not a demo.
    private var exampleCard: some View {
        Button { Task { await runExample() } } label: {
            HStack(spacing: 13) {
                ZStack {
                    Circle().fill(Color.appAccent.opacity(0.14)).frame(width: 40, height: 40)
                    if running {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "sparkles")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(.appAccent)
                    }
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(running ? "Adding them now…" : "Try it with an example")
                        .font(.system(size: 16, weight: .semibold)).foregroundStyle(ink)
                    Text(exampleFailed
                         ? "Couldn't load that just now — try one of the others."
                         : "Puts a few real places on your map. Delete them any time.")
                        .font(.system(size: 13))
                        .foregroundStyle(exampleFailed ? Color.closedRed : ink.opacity(0.5))
                        .fixedSize(horizontal: false, vertical: true)
                        .multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
            }
            .padding(15)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.appAccent.opacity(0.09),
                        in: RoundedRectangle(cornerRadius: 17, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 17, style: .continuous)
                .strokeBorder(Color.appAccent.opacity(0.28)))
        }
        .buttonStyle(.plain)
        .disabled(running)
    }

    private func card(icon: String, title: String, detail: String,
                      action: @escaping () -> Void) -> some View {
        Button { Haptics.tap(); action() } label: {
            HStack(spacing: 13) {
                ZStack {
                    Circle().fill(ink.opacity(0.07)).frame(width: 40, height: 40)
                    Image(systemName: icon)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(ink.opacity(0.7))
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.system(size: 16, weight: .semibold)).foregroundStyle(ink)
                    Text(detail).font(.system(size: 13)).foregroundStyle(ink.opacity(0.5))
                        .fixedSize(horizontal: false, vertical: true)
                        .multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
            }
            .padding(15)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(RoundedRectangle(cornerRadius: 17, style: .continuous)
                .strokeBorder(ink.opacity(0.12)))
        }
        .buttonStyle(.plain)
        .disabled(running)
    }

    private var footer: some View {
        VStack(spacing: 10) {
            Text("All of this lives in the Add tab afterwards.")
                .font(.system(size: 12)).foregroundStyle(ink.opacity(0.4))
            Button("Skip for now") { onFinish(.skip) }
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(ink.opacity(0.6))
                .disabled(running)
        }
    }

    private func runExample() async {
        running = true
        exampleFailed = false
        defer { running = false }
        do {
            _ = try await APIClient.shared.submitExampleReel()
            await Syncer.refresh(context, force: true)
            await maps.refresh(force: true)
            Haptics.success()
            onFinish(.example)
        } catch {
            // No example configured, or the backend is unreachable. Say so and
            // leave the other two routes open rather than dead-ending.
            exampleFailed = true
        }
    }
}
