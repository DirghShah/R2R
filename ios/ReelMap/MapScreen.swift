import MapKit
import SwiftData
import SwiftUI

struct MapScreen: View {
    @Environment(\.modelContext) private var context
    @Query(sort: \CachedPlace.savedAt, order: .reverse) private var allPlaces: [CachedPlace]

    @State private var selected: CachedPlace?
    @State private var filter: MapFilter = .all
    @State private var detail: CachedPlace?
    // .automatic frames the visible pins; the user regains control by panning.
    @State private var camera: MapCameraPosition = .automatic

    private var pins: [CachedPlace] {
        allPlaces.filter { $0.coordinate != nil && filter.matches($0.categoryEnum) }
    }

    var body: some View {
        Map(position: $camera) {
            ForEach(pins) { place in
                if let coord = place.coordinate {
                    Annotation(place.name, coordinate: coord) {
                        PinView(place: place, selected: selected?.id == place.id) {
                            withAnimation(.spring(duration: 0.3)) { selected = place }
                        }
                    }
                }
            }
        }
        .mapStyle(.standard(pointsOfInterest: .excludingAll))
        .ignoresSafeArea(edges: .top)
        .safeAreaInset(edge: .top) { filterBar }
        .overlay(alignment: .bottom) { bottomLayer }
        .task { await Syncer.refresh(context) }
        .refreshable { await Syncer.refresh(context, force: true) }
        .sheet(item: $detail) { PlaceDetailScreen(place: $0) }
    }

    private var filterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(MapFilter.allCases) { f in
                    let on = filter == f
                    Button {
                        withAnimation(.snappy) {
                            filter = f
                            selected = nil
                            camera = .automatic   // re-frame to the filtered pins
                        }
                    } label: {
                        Label(f.label, systemImage: f.icon)
                            .font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 14).padding(.vertical, 9)
                            .foregroundStyle(on ? Color.white : .primary)
                            .background {
                                if on { Capsule().fill(Color.appAccent) }
                                else { Capsule().fill(.regularMaterial) }
                            }
                            .overlay(Capsule().strokeBorder(Color.primary.opacity(on ? 0 : 0.06)))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 4)
        }
    }

    @ViewBuilder private var bottomLayer: some View {
        if let selected {
            PreviewCard(place: selected) { detail = selected }
                .padding(.horizontal, 16).padding(.bottom, 8)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        } else if allPlaces.isEmpty {
            EmptyHint().padding(.horizontal, 24).padding(.bottom, 16)
        }
    }
}

private struct PinView: View {
    let place: CachedPlace
    let selected: Bool
    let tap: () -> Void

    var body: some View {
        Button(action: tap) {
            VStack(spacing: 0) {
                Image(systemName: place.categoryEnum.symbol)
                    .font(.system(size: selected ? 18 : 14, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: selected ? 44 : 36, height: selected ? 44 : 36)
                    .background(place.categoryEnum.tint, in: .circle)
                    .overlay(Circle().strokeBorder(.white, lineWidth: 2))
                    .shadow(color: .black.opacity(0.25), radius: 4, y: 2)
                Image(systemName: "arrowtriangle.down.fill")
                    .font(.system(size: 9))
                    .foregroundStyle(place.categoryEnum.tint)
                    .offset(y: -2)
            }
        }
        .buttonStyle(.plain)
    }
}

private struct PreviewCard: View {
    let place: CachedPlace
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            HStack(spacing: 14) {
                Image(systemName: place.categoryEnum.symbol)
                    .font(.title3.weight(.semibold)).foregroundStyle(.white)
                    .frame(width: 46, height: 46)
                    .background(place.categoryEnum.tint, in: .circle)
                VStack(alignment: .leading, spacing: 3) {
                    Text(place.name).font(.headline).lineLimit(1)
                    Text(place.categoryEnum.displayName + (place.address.map { " · \($0)" } ?? ""))
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(.secondary)
            }
            .padding(14)
            .card(22)
        }
        .buttonStyle(.plain)
    }
}

private struct EmptyHint: View {
    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: "sparkles").font(.title2)
            Text("Your map is empty").font(.headline)
            Text("Open the Add tab and paste an Instagram reel to drop your first pins.")
                .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(20)
        .card(24)
    }
}
