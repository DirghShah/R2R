import MapKit
import SwiftData
import SwiftUI

struct MapScreen: View {
    @Environment(\.modelContext) private var context
    @EnvironmentObject private var activity: ActivityStore
    @Query(sort: \CachedPlace.savedAt, order: .reverse) private var allPlaces: [CachedPlace]

    @State private var selected: CachedPlace?
    @State private var filter: MapFilter = .all
    @State private var detail: CachedPlace?
    @State private var showActivity = false
    @State private var camera: MapCameraPosition = .automatic

    private var pins: [CachedPlace] {
        allPlaces.filter { $0.coordinate != nil && filter.matches($0.categoryEnum) }
    }

    var body: some View {
        Map(position: $camera) {
            ForEach(pins) { place in
                if let coord = place.coordinate {
                    Annotation(place.name, coordinate: coord) {
                        TeardropPin(place: place, selected: selected?.id == place.id) {
                            withAnimation(.spring(duration: 0.3)) { selected = place }
                        }
                    }
                }
            }
        }
        .mapStyle(.standard(pointsOfInterest: .excludingAll))
        .ignoresSafeArea(edges: .top)
        .safeAreaInset(edge: .top) {
            VStack(spacing: 8) {
                filterBar
                if let toast = activity.toast { ToastView(toast: toast).transition(.move(edge: .top).combined(with: .opacity)) }
            }
            .animation(.snappy, value: activity.toast)
        }
        .overlay(alignment: .bottomTrailing) { fabColumn }
        .overlay(alignment: .bottom) { bottomLayer }
        .task { await Syncer.refresh(context) }
        .refreshable { await Syncer.refresh(context, force: true) }
        .sheet(item: $detail) { PlaceDetailScreen(place: $0) }
        .sheet(isPresented: $showActivity) { ActivityView() }
    }

    // MARK: Filter chips

    private var filterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 9) {
                ForEach(MapFilter.allCases) { f in
                    let on = filter == f
                    Button {
                        withAnimation(.snappy) { filter = f; selected = nil; camera = .automatic }
                    } label: {
                        HStack(spacing: 7) {
                            Circle().fill(on ? Color.white : f.dotColor).frame(width: 8, height: 8)
                            Text(f.label).font(.system(size: 13, weight: .semibold))
                        }
                        .foregroundStyle(on ? Color.white : .ink)
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .background(Capsule().fill(on ? f.dotColor : Color.white))
                        .overlay(Capsule().strokeBorder(on ? .clear : Color(hex: 0xE6E6DF)))
                        .shadow(color: Color(hex: 0x1E2822).opacity(0.12), radius: 6, y: 2)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 18).padding(.vertical, 6)
        }
    }

    // MARK: FABs (activity + locate)

    private var fabColumn: some View {
        VStack(spacing: 12) {
            fab(system: "square.stack.3d.up", badge: activity.activeCount) { showActivity = true }
            fab(system: "location.fill", badge: 0) { withAnimation { camera = .automatic } }
        }
        .padding(.trailing, 18)
        .padding(.bottom, selected == nil ? 24 : 130)
        .animation(.snappy, value: selected != nil)
    }

    private func fab(system: String, badge: Int, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            ZStack(alignment: .topTrailing) {
                Image(systemName: system)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.appAccent)
                    .frame(width: 46, height: 46)
                    .background(Color.white, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
                    .shadow(color: Color(hex: 0x1E2822).opacity(0.28), radius: 12, y: 6)
                if badge > 0 {
                    Text("\(badge)").font(.system(size: 11, weight: .bold)).foregroundStyle(.white)
                        .padding(5).background(Circle().fill(Color.appAccent)).offset(x: 5, y: -5)
                }
            }
        }
        .buttonStyle(.plain)
    }

    // MARK: Bottom preview / empty

    @ViewBuilder private var bottomLayer: some View {
        if let selected {
            MiniPreview(place: selected, open: { detail = selected }, close: { withAnimation { self.selected = nil } })
                .padding(.horizontal, 14).padding(.bottom, 12)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        } else if allPlaces.isEmpty {
            EmptyHint().padding(.horizontal, 24).padding(.bottom, 16)
        }
    }
}

// MARK: - Teardrop pin

private struct TeardropPin: View {
    let place: CachedPlace
    let selected: Bool
    let tap: () -> Void

    var body: some View {
        Button(action: tap) {
            ZStack {
                RoundedRectangle(cornerRadius: 13, style: .continuous)
                    .fill(place.categoryEnum.tint)
                    .frame(width: 26, height: 26)
                    .rotationEffect(.degrees(45))
                    .overlay(
                        RoundedRectangle(cornerRadius: 13, style: .continuous)
                            .strokeBorder(.white, lineWidth: 3)
                            .frame(width: 26, height: 26)
                            .rotationEffect(.degrees(45)))
                    .shadow(color: Color(hex: 0x1E2822).opacity(0.5), radius: 5, y: 3)
                Image(systemName: place.categoryEnum.symbol)
                    .font(.system(size: 11, weight: .bold)).foregroundStyle(.white)
            }
            .scaleEffect(selected ? 1.25 : 1)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Mini preview card

private struct MiniPreview: View {
    let place: CachedPlace
    let open: () -> Void
    let close: () -> Void
    private var cat: PlaceCategory { place.categoryEnum }

    var body: some View {
        HStack(spacing: 13) {
            InitialThumb(text: place.initialLetter, color: cat.tint, size: 56, radius: 16)
            Button(action: open) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(cat.displayName.uppercased())
                        .font(.system(size: 11, weight: .bold)).tracking(0.4)
                        .foregroundStyle(cat.tint)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(cat.tint.opacity(0.12), in: Capsule())
                    Text(place.name).font(.display(18, .semibold)).foregroundStyle(.ink).lineLimit(1)
                    if let rating = place.rating {
                        HStack(spacing: 5) {
                            Image(systemName: "star.fill").font(.system(size: 11)).foregroundStyle(.starGold)
                            Text(String(format: "%.1f", rating)).font(.system(size: 13, weight: .bold)).foregroundStyle(.ink)
                            if let a = place.address ?? place.city { Text("· \(a)").font(.system(size: 13)).foregroundStyle(.inkSecondary).lineLimit(1) }
                        }
                    } else if let a = place.address ?? place.city {
                        Text(a).font(.system(size: 13)).foregroundStyle(.inkSecondary).lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            Button(action: close) {
                Image(systemName: "xmark").font(.system(size: 12, weight: .bold)).foregroundStyle(.inkSecondary)
                    .frame(width: 26, height: 26).background(Color(hex: 0xF1F1EC), in: Circle())
            }
            .buttonStyle(.plain)
            .frame(maxHeight: .infinity, alignment: .top)
        }
        .padding(14)
        .background(Color.white, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .shadow(color: Color(hex: 0x1E2822).opacity(0.35), radius: 24, y: 14)
    }
}

// MARK: - Shared bits

struct InitialThumb: View {
    let text: String
    let color: Color
    var size: CGFloat = 52
    var radius: CGFloat = 15
    var body: some View {
        Text(text)
            .font(.display(size * 0.4, .bold)).foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(
                LinearGradient(colors: [color, color.opacity(0.8)],
                               startPoint: .topLeading, endPoint: .bottomTrailing),
                in: RoundedRectangle(cornerRadius: radius, style: .continuous))
    }
}

struct ToastView: View {
    let toast: ActivityStore.Toast
    var body: some View {
        HStack(spacing: 10) {
            switch toast {
            case .added(let n):
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.appAccent)
                Text("\(n) place\(n == 1 ? "" : "s") added to your map").font(.system(size: 14, weight: .medium))
            case .failed:
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.closedRed)
                Text("Couldn't analyze a reel").font(.system(size: 14, weight: .medium))
            }
        }
        .foregroundStyle(.ink)
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(Color.white, in: Capsule())
        .shadow(color: Color(hex: 0x1E2822).opacity(0.15), radius: 10, y: 4)
    }
}

private struct EmptyHint: View {
    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: "sparkles").font(.title2).foregroundStyle(.appAccent)
            Text("Your map is empty").font(.display(18, .semibold)).foregroundStyle(.ink)
            Text("Open Analyze and paste a reel to drop your first pins.")
                .font(.callout).foregroundStyle(.inkSecondary).multilineTextAlignment(.center)
        }
        .padding(20)
        .card(24)
    }
}
