import MapKit
import SwiftData
import SwiftUI

struct MapScreen: View {
    @Environment(\.modelContext) private var context
    @EnvironmentObject private var activity: ActivityStore
    @Query(sort: \CachedPlace.savedAt, order: .reverse) private var allPlaces: [CachedPlace]

    @StateObject private var location = LocationManager()
    @State private var filter: String = allFilter
    @State private var detail: CachedPlace?
    @State private var showActivity = false
    @State private var camera: MapCameraPosition = .automatic
    @State private var didCenterOnUser = false

    private static let allFilter = "All"

    /// "All" + the distinct cuisine/venue labels currently on the map, in order of
    /// how many places carry them (most common first) — so the chips reflect the
    /// user's actual saved reels, not a fixed list.
    private var filterOptions: [String] {
        var counts: [String: Int] = [:]
        for p in allPlaces where p.coordinate != nil {
            counts[p.filterLabel, default: 0] += 1
        }
        let labels = counts.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }
                           .map(\.key)
        return [Self.allFilter] + labels
    }

    private var pins: [CachedPlace] {
        allPlaces.filter {
            $0.coordinate != nil && (filter == Self.allFilter || $0.filterLabel == filter)
        }
    }

    var body: some View {
        Map(position: $camera) {
            UserAnnotation()
            ForEach(pins) { place in
                if let coord = place.coordinate {
                    Annotation(place.name, coordinate: coord) {
                        SimplePin(color: place.pinColor) { detail = place }
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
        .task {
            location.request()
            await Syncer.refresh(context)
        }
        .onChange(of: location.authorized) { _, ok in
            // Center on the user as soon as we're granted access (first launch flow).
            if ok { centerOnUser() }
        }
        .onAppear {
            // Returning to the tab when already authorized: snap to the user once.
            if location.authorized && !didCenterOnUser { centerOnUser() }
        }
        .refreshable { await Syncer.refresh(context, force: true) }
        .sheet(item: $detail) { PlaceDetailScreen(place: $0) }
        .sheet(isPresented: $showActivity) { ActivityView() }
    }

    private func centerOnUser() {
        didCenterOnUser = true
        withAnimation(.easeInOut) {
            camera = .userLocation(fallback: .automatic)
        }
    }

    // MARK: Filter chips

    private var filterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 9) {
                ForEach(filterOptions, id: \.self) { label in
                    let on = filter == label
                    let dot = dotColor(for: label)
                    Button {
                        withAnimation(.snappy) { filter = label }
                    } label: {
                        HStack(spacing: 7) {
                            Circle().fill(on ? Color.white : dot).frame(width: 8, height: 8)
                            Text(label).font(.system(size: 13, weight: .semibold))
                        }
                        .foregroundStyle(on ? Color.white : .ink)
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .background(Capsule().fill(on ? dot : Color.white))
                        .overlay(Capsule().strokeBorder(on ? .clear : Color(hex: 0xE6E6DF)))
                        .shadow(color: Color(hex: 0x1E2822).opacity(0.12), radius: 6, y: 2)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 18).padding(.vertical, 6)
        }
    }

    private func dotColor(for label: String) -> Color {
        if label == Self.allFilter { return .appAccent }
        return CuisineStyle.color(label)
            ?? allPlaces.first { $0.filterLabel == label }?.categoryEnum.tint
            ?? .appAccent
    }

    // MARK: FABs (activity + locate)

    private var fabColumn: some View {
        VStack(spacing: 12) {
            fab(system: "square.stack.3d.up", badge: activity.activeCount) { showActivity = true }
            fab(system: "location.fill", badge: 0) {
                if location.authorized { centerOnUser() }
                else { location.request() }
            }
        }
        .padding(.trailing, 18)
        .padding(.bottom, 24)
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
        if allPlaces.isEmpty {
            EmptyHint().padding(.horizontal, 24).padding(.bottom, 16)
        }
    }
}

// MARK: - Simple color-coded pin

/// A plain dot whose color encodes the cuisine/category (no icon). Tapping it
/// opens the full place detail sheet.
private struct SimplePin: View {
    let color: Color
    let tap: () -> Void

    var body: some View {
        Button(action: tap) {
            Circle()
                .fill(color)
                .frame(width: 20, height: 20)
                .overlay(Circle().strokeBorder(.white, lineWidth: 3))
                .shadow(color: Color(hex: 0x1E2822).opacity(0.45), radius: 4, y: 2)
        }
        .buttonStyle(.plain)
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
