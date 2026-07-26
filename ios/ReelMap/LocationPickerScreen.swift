import CoreLocation
import MapKit
import SharedKit
import SwiftData
import SwiftUI

/// Drop a pin by hand for a place the geocoder couldn't resolve.
///
/// Geocoding deliberately returns nothing rather than risk a wrong pin (see
/// `place_min_score` in the backend), which leaves the place listed but off the
/// map. This is the escape hatch: search for the venue, or drag the map until
/// the crosshair is over it.
struct LocationPickerScreen: View {
    let place: CachedPlace
    var userLocation: CLLocation? = nil

    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var context

    @State private var camera: MapCameraPosition = .automatic
    @State private var center: CLLocationCoordinate2D?
    @State private var query = ""
    @State private var results: [MKMapItem] = []
    @State private var pickedAddress: String?
    @State private var searching = false
    @State private var saving = false
    @State private var errorText: String?
    @FocusState private var searchFocused: Bool

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                map
                VStack(spacing: 0) {
                    searchField
                    if !results.isEmpty { resultsList }
                }
                .padding(.horizontal, 16).padding(.top, 8)
            }
            .safeAreaInset(edge: .bottom) { saveBar }
            .navigationTitle("Set location")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task { await seedFromPlaceName() }
            .alert("Couldn't save", isPresented: .init(get: { errorText != nil },
                                                      set: { if !$0 { errorText = nil } })) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(errorText ?? "")
            }
        }
    }

    // MARK: Map + crosshair

    private var map: some View {
        Map(position: $camera)
            .mapStyle(.standard)
            .onMapCameraChange(frequency: .continuous) { ctx in center = ctx.region.center }
            // A fixed crosshair over a movable map beats a draggable annotation:
            // no gesture conflicts, and the target is always dead centre.
            .overlay(alignment: .center) { crosshair }
            .ignoresSafeArea(edges: .bottom)
    }

    private var crosshair: some View {
        VStack(spacing: 0) {
            Image(systemName: "mappin")
                .font(.system(size: 30, weight: .bold))
                .foregroundStyle(place.pinColor)
                .shadow(color: .black.opacity(0.35), radius: 4, y: 2)
            Circle().fill(.black.opacity(0.25)).frame(width: 8, height: 4).blur(radius: 1)
        }
        .offset(y: -15)  // sit the point, not the centre of the glyph, on the target
        .allowsHitTesting(false)
    }

    // MARK: Search

    private var searchField: some View {
        HStack(spacing: 9) {
            Image(systemName: "magnifyingglass").font(.system(size: 14, weight: .semibold))
                .foregroundStyle(.inkMuted)
            TextField("", text: $query,
                      prompt: Text("Search for \(place.name)").foregroundColor(.inkMuted))
                .font(.system(size: 15)).foregroundStyle(.ink)
                .autocorrectionDisabled().submitLabel(.search)
                .focused($searchFocused)
                .onSubmit { Task { await search(query) } }
            if searching { ProgressView().controlSize(.small) }
            else if !query.isEmpty {
                Button { query = ""; results = [] } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.inkMuted)
                }.buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.cardStroke))
        .shadow(color: .black.opacity(0.12), radius: 10, y: 4)
    }

    private var resultsList: some View {
        VStack(spacing: 0) {
            ForEach(Array(results.prefix(5).enumerated()), id: \.offset) { i, item in
                Button {
                    Haptics.tap()
                    select(item)
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "mappin.circle.fill").font(.system(size: 18))
                            .foregroundStyle(.appAccent)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(item.name ?? "Unnamed").font(.system(size: 14, weight: .semibold))
                                .foregroundStyle(.ink).lineLimit(1)
                            if let sub = Self.addressLine(item) {
                                Text(sub).font(.system(size: 12)).foregroundStyle(.inkSecondary).lineLimit(1)
                            }
                        }
                        Spacer()
                    }
                    .padding(.horizontal, 14).padding(.vertical, 11)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Color.hairline).frame(height: 1) } }
            }
        }
        .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.cardStroke))
        .shadow(color: .black.opacity(0.12), radius: 10, y: 4)
        .padding(.top, 8)
    }

    // MARK: Save

    private var saveBar: some View {
        VStack(spacing: 8) {
            if let pickedAddress {
                Text(pickedAddress).font(.system(size: 13)).foregroundStyle(.inkSecondary)
                    .lineLimit(2).multilineTextAlignment(.center)
            } else {
                Text("Drag the map to put the pin on \(place.name)")
                    .font(.system(size: 13)).foregroundStyle(.inkSecondary)
            }
            Button { Task { await save() } } label: {
                HStack(spacing: 8) {
                    if saving { ProgressView().tint(.white) }
                    else { Image(systemName: "mappin.and.ellipse").font(.system(size: 15, weight: .semibold)) }
                    Text(saving ? "Saving…" : "Use this location")
                        .font(.system(size: 15, weight: .semibold))
                }
                .foregroundStyle(.white).frame(maxWidth: .infinity).padding(.vertical, 15)
                .background(Color.appAccent, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(saving || center == nil)
            .opacity(center == nil ? 0.5 : 1)
        }
        .padding(.horizontal, 20).padding(.top, 12).padding(.bottom, 8)
        .background(.regularMaterial)
    }

    private func save() async {
        guard let center else { return }
        saving = true
        defer { saving = false }
        // Fill in an address if the user dragged rather than picking a result —
        // it's what the list rows and the Address row display.
        let address = pickedAddress ?? (await Self.reverseGeocode(center))
        do {
            let updated = try await APIClient.shared.setPlaceLocation(
                id: place.id, lat: center.latitude, lng: center.longitude, address: address)
            apply(updated)
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            dismiss()
        } catch {
            errorText = error.localizedDescription
        }
    }

    /// Patch the cached row directly rather than round-tripping a full refresh
    /// just to pick up the one field we already have back from the server.
    private func apply(_ updated: SavedPlace) {
        place.lat = updated.place.lat
        place.lng = updated.place.lng
        place.address = updated.place.address
        place.region = updated.place.region
        place.locationSource = updated.place.locationSource
        try? context.save()
    }

    // MARK: Lookup

    /// Best-effort first guess: search the venue by name in its city so the
    /// common case is "open, glance, tap Use this location".
    private func seedFromPlaceName() async {
        if let user = userLocation {
            camera = .region(MKCoordinateRegion(center: user.coordinate,
                                                latitudinalMeters: 8000, longitudinalMeters: 8000))
        }
        var terms = [place.name]
        if let city = place.cityLabel { terms.append(city) }
        await search(terms.joined(separator: ", "))
        // Land on the best guess; `select` clears the dropdown so the user sees
        // a positioned map rather than a list to work through.
        if let first = results.first { select(first) }
    }

    private func search(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        searching = true
        defer { searching = false }

        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = trimmed
        if let user = userLocation {
            request.region = MKCoordinateRegion(center: user.coordinate,
                                                latitudinalMeters: 50_000, longitudinalMeters: 50_000)
        }
        results = (try? await MKLocalSearch(request: request).start())?.mapItems ?? []
    }

    private func select(_ item: MKMapItem) {
        let coordinate = item.placemark.coordinate
        searchFocused = false
        results = []
        query = item.name ?? query
        pickedAddress = Self.addressLine(item)
        center = coordinate
        withAnimation(.easeInOut) {
            camera = .region(MKCoordinateRegion(center: coordinate,
                                                latitudinalMeters: 400, longitudinalMeters: 400))
        }
    }

    private static func addressLine(_ item: MKMapItem) -> String? {
        let p = item.placemark
        let parts = [
            [p.subThoroughfare, p.thoroughfare].compactMap { $0 }.joined(separator: " "),
            p.locality, p.administrativeArea, p.postalCode, p.country,
        ]
        let line = parts.compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
        return line.isEmpty ? nil : line
    }

    private static func reverseGeocode(_ c: CLLocationCoordinate2D) async -> String? {
        let location = CLLocation(latitude: c.latitude, longitude: c.longitude)
        guard let mark = try? await CLGeocoder().reverseGeocodeLocation(location).first else { return nil }
        return addressLine(MKMapItem(placemark: MKPlacemark(placemark: mark)))
    }
}
