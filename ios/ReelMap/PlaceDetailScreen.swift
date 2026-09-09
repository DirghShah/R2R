import CoreLocation
import MapKit
import SharedKit
import SwiftData
import SwiftUI

struct PlaceDetailScreen: View {
    let place: CachedPlace
    var userLocation: CLLocation? = nil
    var detents: Set<PresentationDetent> = [.large]
    /// Only true in shared maps — in a personal map there's one contributor, so
    /// naming them on every card is noise.
    var showsAttribution: Bool = false

    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var context
    @State private var showMapsDialog = false
    @State private var mark: PlaceMark?
    @State private var visited = false
    @State private var note = ""
    @State private var confirmDelete = false
    // Guideline 1.2. A place in a shared map was put there by another person,
    // which makes it reportable content.
    @State private var reporting: ReportSubject?
    @State private var deleting = false
    @State private var deleteError: String?
    @State private var showLocationPicker = false
    @FocusState private var isNotesFocused: Bool

    private var cat: PlaceCategory { place.categoryEnum }
    private var tint: Color { place.pinColor }
    private var hasCoords: Bool { place.coordinate != nil }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                hero
                VStack(alignment: .leading, spacing: 14) {
                    badgeRow
                    if let s = place.summary, !s.isEmpty {
                        Text(s).font(.system(size: 15)).foregroundStyle(.ink).lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if place.isUnmapped { unmappedCard }
                    if !place.tips.isEmpty { tipsCard }
                    if !place.whatToOrder.isEmpty { orderCard }
                    infoCard
                    if showsAttribution, let name = place.addedByName { addedByCard(name) }
                    visitedCard
                    sourcedFrom
                    actions
                    removeButton
            reportButton
                }
                .padding(.horizontal, 20).padding(.top, 16).padding(.bottom, 34)
            }
            // Tap anywhere that isn't a control to dismiss the notes keyboard —
            // buttons and the field itself still win, since child gestures take
            // precedence over a container's tap.
            .contentShape(Rectangle())
            .onTapGesture { isNotesFocused = false }
        }
        .scrollIndicators(.hidden)
        .scrollDismissesKeyboard(.interactively)
        .background(Color.canvas)
        .presentationDetents(detents)
        .presentationDragIndicator(.visible)
        .onAppear(perform: loadMark)
        .onDisappear(perform: persistMark)
        .confirmationDialog("Open in Maps", isPresented: $showMapsDialog, titleVisibility: .visible) {
            Button("Apple Maps") { openAppleMaps() }
            Button("Google Maps") { openGoogleMaps() }
        }
        .sheet(item: $reporting) {
            ReportSheet(target: $0.target, targetID: $0.id, subject: $0.name)
        }
        .confirmationDialog("Remove \(place.name)?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Remove pin", role: .destructive) { Task { await deletePlace() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("It disappears from your map and lists. Sharing the reel again brings it back.")
        }
        .alert("Couldn't remove", isPresented: .init(get: { deleteError != nil },
                                                    set: { if !$0 { deleteError = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(deleteError ?? "")
        }
        .sheet(isPresented: $showLocationPicker) {
            LocationPickerScreen(place: place, userLocation: userLocation)
        }
    }

    // MARK: Hero

    private var hero: some View {
        ZStack(alignment: .bottomLeading) {
            heroBackground
            HStack {
                ShareLink(item: shareText) { heroButton("square.and.arrow.up") }
                Spacer()
                Button { dismiss() } label: { heroButton("xmark") }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            // Extra top inset: the sheet's drag indicator sits in this strip.
            .padding(.horizontal, 16).padding(.top, 26).padding(.bottom, 16)

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: cat.symbol).font(.system(size: 10, weight: .bold))
                    Text(place.filterLabel.uppercased())
                        .font(.system(size: 11, weight: .bold)).tracking(0.5)
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(.white.opacity(0.22), in: RoundedRectangle(cornerRadius: 8))
                Text(place.name).font(.display(28, .bold)).foregroundStyle(.white)
                    .shadow(color: .black.opacity(0.3), radius: 12, y: 2)
            }
            .padding(20)
        }
        .frame(height: 210)
        .clipped()
    }

    private var gradient: some View {
        LinearGradient(colors: [tint, tint.opacity(0.73), Color.deepGreen],
                       startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    /// Real venue photo (Google) with a legibility scrim, or the gradient.
    ///
    /// The image sits in an *overlay* on a zero-size Color rather than being a
    /// ZStack child directly: `scaledToFill` reports the scaled-up size, which
    /// grew the ZStack and pushed the close/share buttons and the name outside
    /// the 210pt window, so they rendered cut off.
    @ViewBuilder private var heroBackground: some View {
        if let url = place.firstPhotoURL {
            Color.deepGreen
                .overlay {
                    AsyncImage(url: url) { img in
                        img.resizable().scaledToFill()
                    } placeholder: {
                        gradient.overlay(ProgressView().tint(.white))
                    }
                }
                .clipped()
                .overlay(LinearGradient(colors: [.black.opacity(0.35), .clear,
                                                 .black.opacity(0.55)],
                                        startPoint: .top, endPoint: .bottom))
        } else {
            gradient
        }
    }

    private func heroButton(_ system: String) -> some View {
        Image(systemName: system).font(.system(size: 15, weight: .bold)).foregroundStyle(.white)
            .frame(width: 32, height: 32).background(Color(hex: 0x101A14).opacity(0.35), in: Circle())
    }

    private var shareText: String {
        var parts = [place.name]
        if let a = place.address ?? place.cityLabel { parts.append(a) }
        if let g = place.googleMapsURL { parts.append(g) }
        else if let r = place.reelURL { parts.append(r) }
        return parts.joined(separator: "\n")
    }

    // MARK: Rows

    private var badgeRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                if let r = place.rating {
                    HStack(spacing: 6) {
                        Image(systemName: "star.fill").font(.system(size: 14)).foregroundStyle(.starGold)
                        Text(String(format: "%.1f", r)).font(.display(16, .bold)).foregroundStyle(.ink)
                        if let n = place.reviewCount, n > 0 {
                            Text("(\(n.formatted()))").font(.system(size: 12)).foregroundStyle(.inkSecondary)
                        }
                    }
                    .padding(.horizontal, 13).padding(.vertical, 9).card(14)
                }
                if let price = place.priceString {
                    Text(price).font(.system(size: 15, weight: .semibold)).foregroundStyle(.ink)
                        .padding(.horizontal, 13).padding(.vertical, 9).card(14)
                }
                if let d = place.distanceMeters(from: userLocation) {
                    Label(DistanceFormat.short(d), systemImage: "location.fill")
                        .font(.system(size: 13, weight: .semibold)).foregroundStyle(.inkSecondary)
                        .padding(.horizontal, 13).padding(.vertical, 9).card(14)
                }
                openChip
            }
            .padding(.vertical, 2)
        }
        .scrollClipDisabled()
    }

    @ViewBuilder private var openChip: some View {
        if place.isPermanentlyClosed {
            statusChip("Permanently closed", color: .closedRed)
        } else if let st = place.openStatus {
            statusChip(st.label, color: st.open ? .appAccent : .closedRed)
        } else if let h = place.hoursHint {
            statusChip(h, color: .appAccent)
        }
    }

    private func statusChip(_ text: String, color: Color) -> some View {
        Text(text).font(.system(size: 13, weight: .semibold)).foregroundStyle(color).lineLimit(1)
            .padding(.horizontal, 13).padding(.vertical, 9)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var tipsCard: some View {
        card(header: "Tips from the reel", icon: "lightbulb.fill") {
            ForEach(Array(place.tips.enumerated()), id: \.offset) { i, tip in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "checkmark").font(.system(size: 13, weight: .heavy)).foregroundStyle(.appAccent)
                        .padding(.top, 2)
                    Text(tip).font(.system(size: 14)).foregroundStyle(.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 7)
                .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Color.hairline).frame(height: 1) } }
            }
        }
    }

    private var orderCard: some View {
        card(header: "What to order", icon: "fork.knife") {
            ForEach(Array(place.whatToOrder.enumerated()), id: \.offset) { i, item in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "circle.fill").font(.system(size: 5)).foregroundStyle(.appAccent).padding(.top, 7)
                    Text(item).font(.system(size: 14)).foregroundStyle(.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 6)
            }
        }
    }

    @ViewBuilder private var infoCard: some View {
        let rows = infoRows
        if !rows.isEmpty {
            VStack(spacing: 0) {
                ForEach(Array(rows.enumerated()), id: \.offset) { i, row in
                    infoRowView(row)
                        .padding(.vertical, 13)
                        .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Color.hairline).frame(height: 1) } }
                }
            }
            .padding(.horizontal, 16).card(20)
        }
    }

    /// Rows carrying a destination open it on tap; the rest are plain text.
    @ViewBuilder private func infoRowView(_ row: InfoRow) -> some View {
        if let destination = row.destination {
            Button {
                Haptics.tap()
                open(destination)
            } label: {
                infoRowBody(row)
            }
            .buttonStyle(.plain)
        } else {
            infoRowBody(row)
        }
    }

    private func infoRowBody(_ row: InfoRow) -> some View {
        HStack(spacing: 12) {
            Image(systemName: row.icon).font(.system(size: 17))
                .foregroundStyle(row.destination == nil ? Color.inkMuted : .linkBlue).frame(width: 20)
            VStack(alignment: .leading, spacing: 1) {
                Text(row.label).font(.system(size: 13)).foregroundStyle(.secondary)
                Text(row.value).font(.system(size: 14, weight: .medium))
                    .foregroundStyle(row.destination == nil ? Color.primary : .linkBlue).lineLimit(1)
            }
            Spacer()
            if row.destination != nil {
                Image(systemName: "arrow.up.right").font(.system(size: 12, weight: .bold)).foregroundStyle(.inkMuted)
            }
        }
        .contentShape(Rectangle())
    }

    private var sourcedFrom: some View {
        HStack(spacing: 11) {
            ZStack {
                LinearGradient(colors: [tint, Color.deepGreen], startPoint: .topLeading, endPoint: .bottomTrailing)
                Image(systemName: "play.fill").font(.system(size: 15)).foregroundStyle(.white)
            }
            .frame(width: 44, height: 44).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 1) {
                Text("Sourced from").font(.system(size: 13)).foregroundStyle(.inkMuted)
                Text(sourceLabel).font(.system(size: 14, weight: .semibold)).foregroundStyle(.ink).lineLimit(1)
            }
            Spacer()
        }
        .padding(.horizontal, 15).padding(.vertical, 13).card(20)
    }

    private var actions: some View {
        HStack(spacing: 11) {
            if let reel = place.reelURL, let url = URL(string: reel) {
                Button { openReel(url) } label: {
                    Label("Open reel", systemImage: "play.fill")
                        .font(.system(size: 15, weight: .semibold)).foregroundStyle(.white)
                        .frame(maxWidth: .infinity).padding(15)
                        .background(Color.linkBlue, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }.buttonStyle(.plain)
            }
            if hasCoords {
                Button { showMapsDialog = true } label: {
                    Label("Maps", systemImage: "mappin.and.ellipse")
                        .font(.system(size: 15, weight: .semibold)).foregroundStyle(.appAccent)
                        .frame(maxWidth: .infinity).padding(15)
                        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.appAccent, lineWidth: 1.6))
                }.buttonStyle(.plain)
            }
        }
    }

    private func addedByCard(_ name: String) -> some View {
        HStack(spacing: 11) {
            InitialAvatar(name: name, colorHex: place.addedByColor, size: 34)
            VStack(alignment: .leading, spacing: 1) {
                Text("Added by").font(.system(size: 13)).foregroundStyle(.inkMuted)
                Text(place.addedBySomeoneElse ? name : "You")
                    .font(.system(size: 14, weight: .semibold)).foregroundStyle(.ink)
            }
            Spacer()
        }
        .padding(.horizontal, 15).padding(.vertical, 12).card(20)
    }

    // MARK: No map location

    /// Shown instead of a silent absence: geocoding declined to guess, so the
    /// place is saved and listed but has no pin until someone sets one.
    private var unmappedCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "mappin.slash").font(.system(size: 15)).foregroundStyle(.orange)
                Text("No map location").font(.display(15, .semibold)).foregroundStyle(.ink)
            }
            Text("We couldn't work out exactly where this is, so it's saved to your lists but isn't on the map yet.")
                .font(.system(size: 14)).foregroundStyle(.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Button { Haptics.tap(); showLocationPicker = true } label: {
                Label("Set location", systemImage: "mappin.and.ellipse")
                    .font(.system(size: 15, weight: .semibold)).foregroundStyle(.white)
                    .frame(maxWidth: .infinity).padding(.vertical, 13)
                    .background(Color.appAccent, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            .buttonStyle(.plain)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous)
            .strokeBorder(Color.orange.opacity(0.35)))
    }

    // MARK: Remove

    private var removeButton: some View {
        Button { Haptics.tap(); confirmDelete = true } label: {
            HStack(spacing: 8) {
                if deleting { ProgressView().tint(.closedRed) }
                else { Image(systemName: "trash").font(.system(size: 14, weight: .semibold)) }
                Text(deleting ? "Removing…" : "Remove this pin").font(.system(size: 15, weight: .semibold))
            }
            .foregroundStyle(.closedRed)
            .frame(maxWidth: .infinity).padding(14)
            .background(Color.closedRed.opacity(0.10), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(deleting)
    }

    /// Removing a pin only affects your map; reporting escalates it to us.
    /// Both are needed: one is tidying, the other is moderation.
    private var reportButton: some View {
        Button {
            Haptics.tap()
            reporting = ReportSubject(target: .place, id: place.id, name: place.name)
        } label: {
            Label("Report this place", systemImage: "flag")
                .font(.system(size: 13)).foregroundStyle(.inkMuted)
                .frame(maxWidth: .infinity).padding(.vertical, 10)
        }
        .buttonStyle(.plain)
    }

    private func deletePlace() async {
        deleting = true
        defer { deleting = false }
        let id = place.id
        do {
            try await APIClient.shared.deletePlace(id: id)
        } catch {
            deleteError = error.localizedDescription
            return
        }
        Haptics.success()
        dismiss()
        // Let the sheet finish tearing down before the model goes away — this
        // view still holds `place`, and reading a deleted SwiftData object mid
        // dismissal is a crash.
        try? await Task.sleep(nanoseconds: 450_000_000)
        Syncer.purge(placeID: id, context)
    }

    // MARK: Visited + notes (local, survives sync)

    private var visitedCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Toggle(isOn: $visited) {
                Label("I've been here", systemImage: visited ? "checkmark.seal.fill" : "checkmark.seal")
                    .font(.system(size: 15, weight: .semibold)).foregroundStyle(.ink)
            }
            .tint(.appAccent)
            .onChange(of: visited) { _, _ in Haptics.select(); persistMark() }

            Rectangle().fill(Color.hairline).frame(height: 1)

            VStack(alignment: .leading, spacing: 6) {
                Text("YOUR NOTES").font(.system(size: 11, weight: .semibold)).tracking(0.4).foregroundStyle(.secondary)
                TextField("Add a private note…", text: $note, axis: .vertical)
                    .font(.system(size: 14)).foregroundStyle(.ink).lineLimit(1...4)
                    .focused($isNotesFocused)
                    .onChange(of: isNotesFocused) { _, focused in if !focused { persistMark() } }
                    // A multiline field has no return key to dismiss with, so
                    // give the keyboard an explicit way out too.
                    .toolbar {
                        ToolbarItemGroup(placement: .keyboard) {
                            Spacer()
                            Button("Done") { isNotesFocused = false; persistMark() }
                                .font(.system(size: 15, weight: .semibold))
                        }
                    }
            }
        }
        .padding(16).card(20)
    }

    private func loadMark() {
        let id = place.id
        let descriptor = FetchDescriptor<PlaceMark>(predicate: #Predicate { $0.placeID == id })
        if let m = try? context.fetch(descriptor).first {
            mark = m; visited = m.visited; note = m.note
        }
    }

    private func persistMark() {
        if let m = mark {
            m.visited = visited; m.note = note; m.updatedAt = .now
        } else if visited || !note.isEmpty {
            let m = PlaceMark(placeID: place.id, visited: visited, note: note)
            context.insert(m); mark = m
        }
        try? context.save()
    }

    // MARK: Helpers

    private func card<Content: View>(header: String, icon: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.system(size: 15)).foregroundStyle(.appAccent)
                Text(header).font(.display(15, .semibold)).foregroundStyle(.ink)
            }
            .padding(.bottom, 4)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16).card(20)
    }

    /// `destination` is the app URL to open on tap (with `web` as the fallback
    /// when the native app isn't installed); nil makes the row plain text.
    private struct InfoRow {
        let icon: String
        let label: String
        let value: String
        var destination: Destination? = nil
    }

    private struct Destination { let primary: URL; var fallback: URL? = nil }

    private var infoRows: [InfoRow] {
        var rows: [InfoRow] = []
        if let h = place.hoursHint { rows.append(.init(icon: "clock", label: "Hours", value: h)) }
        if let a = place.address ?? place.cityLabel { rows.append(.init(icon: "mappin.and.ellipse", label: "Address", value: a)) }
        if let phone = place.phone {
            let digits = phone.filter { $0.isNumber || $0 == "+" }
            rows.append(.init(icon: "phone", label: "Phone", value: phone,
                              destination: URL(string: "tel://\(digits)").map { Destination(primary: $0) }))
        }
        if let handle = place.instagramHandle {
            let clean = handle.trimmingCharacters(in: CharacterSet(charactersIn: "@ "))
            rows.append(.init(icon: "camera", label: "Instagram", value: "@\(clean)",
                              destination: instagramDestination(clean)))
        }
        if let site = place.website {
            let clean = site.replacingOccurrences(of: "https://", with: "").replacingOccurrences(of: "http://", with: "")
            rows.append(.init(icon: "globe", label: "Website", value: clean,
                              destination: websiteURL(site).map { Destination(primary: $0) }))
        }
        return rows
    }

    /// Deep-link into the Instagram app when it's installed, else the profile page.
    private func instagramDestination(_ handle: String) -> Destination? {
        guard !handle.isEmpty,
              let web = URL(string: "https://www.instagram.com/\(handle)/")
        else { return nil }
        guard let app = URL(string: "instagram://user?username=\(handle)") else {
            return Destination(primary: web)
        }
        return Destination(primary: app, fallback: web)
    }

    /// The AI sometimes returns a bare host ("saaqinyc.com") — add the scheme so
    /// it opens instead of being treated as a relative path.
    private func websiteURL(_ raw: String) -> URL? {
        let trimmed = raw.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return nil }
        if trimmed.lowercased().hasPrefix("http://") || trimmed.lowercased().hasPrefix("https://") {
            return URL(string: trimmed)
        }
        return URL(string: "https://\(trimmed)")
    }

    private func open(_ destination: Destination) {
        if UIApplication.shared.canOpenURL(destination.primary) {
            UIApplication.shared.open(destination.primary)
        } else if let fallback = destination.fallback {
            UIApplication.shared.open(fallback)
        }
    }

    private var sourceLabel: String {
        let platform = platformName
        if let h = place.instagramHandle { return "@\(h) · \(platform)" }
        return platform
    }

    private var platformName: String {
        let u = (place.reelURL ?? "").lowercased()
        if u.contains("tiktok") { return "TikTok" }
        if u.contains("youtu") { return "YouTube" }
        return "Instagram"
    }

    // MARK: Deep links

    /// Open the reel itself, not just the app it lives in.
    ///
    /// This used to rewrite the https link into the instagram:// scheme by
    /// swapping the host, which turned
    /// `https://www.instagram.com/reel/ABC/` into `instagram:///reel/ABC/` —
    /// an empty host and a path the scheme defines no route for. Instagram
    /// accepted it, ignored it, and opened the feed, so "Open reel" always
    /// landed on whatever Instagram felt like showing.
    ///
    /// The https link needs no rewriting at all: Instagram, TikTok and YouTube
    /// all claim their own links, so iOS hands this to the app when it is
    /// installed and to Safari when it isn't. One line covers all three.
    private func openReel(_ url: URL) {
        UIApplication.shared.open(url)
    }

    private func openAppleMaps() {
        guard let lat = place.lat, let lng = place.lng else { return }
        let item = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lng)))
        item.name = place.name
        item.openInMaps()
    }

    private func openGoogleMaps() {
        // Prefer the exact place URL Google gave us — it opens the resolved
        // listing (reviews, hours, photos) rather than a name search.
        if let s = place.googleMapsURL, let url = URL(string: s) {
            UIApplication.shared.open(url)
            return
        }
        guard let lat = place.lat, let lng = place.lng else { return }
        let q = place.name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        let app = URL(string: "comgooglemaps://?q=\(q)&center=\(lat),\(lng)")!
        let web = URL(string: "https://www.google.com/maps/search/?api=1&query=\(lat),\(lng)")!
        UIApplication.shared.open(UIApplication.shared.canOpenURL(app) ? app : web)
    }
}
