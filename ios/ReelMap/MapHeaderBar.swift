import SharedKit
import SwiftUI

/// The current-map control that sits at the top of Map and Lists.
///
/// Tapping the name opens the switcher. In a shared map it also stacks the
/// members' avatars — the cheapest possible signal that you're not alone in
/// here, which is the whole point of the feature.
struct MapHeaderBar: View {
    @EnvironmentObject private var store: MapStore
    @State private var showSwitcher = false

    var body: some View {
        Button { Haptics.tap(); showSwitcher = true } label: {
            HStack(spacing: 8) {
                Text(store.current?.emoji ?? "📍").font(.system(size: 15))
                Text(store.current?.name ?? "My Map")
                    .font(.display(16, .semibold)).foregroundStyle(.ink)
                    .lineLimit(1)
                Image(systemName: "chevron.down")
                    .font(.system(size: 11, weight: .bold)).foregroundStyle(.inkMuted)
                if let map = store.current, map.isShared {
                    Text("\(map.memberCount)")
                        .font(.system(size: 11, weight: .bold)).foregroundStyle(.appAccent)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color.appAccent.opacity(0.14), in: Capsule())
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 9)
            .background(Capsule().fill(Color.cardFill))
            .overlay(Capsule().strokeBorder(Color.cardStroke))
            .shadow(color: Color(hex: 0x1E2822).opacity(0.10), radius: 6, y: 2)
        }
        .buttonStyle(.plain)
        .sheet(isPresented: $showSwitcher) { MapSwitcherSheet() }
    }
}

/// Small "who added this" chip, shown only where it carries information — a
/// personal map has exactly one contributor, so it would be noise there.
struct AddedByChip: View {
    let name: String?
    let colorHex: String?

    var body: some View {
        HStack(spacing: 5) {
            InitialAvatar(name: name, colorHex: colorHex, size: 16)
            Text(name ?? "Someone")
                .font(.system(size: 11.5, weight: .medium)).foregroundStyle(.inkSecondary)
                .lineLimit(1)
        }
    }
}
