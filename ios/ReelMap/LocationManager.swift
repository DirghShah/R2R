import CoreLocation
import SwiftUI

/// Thin wrapper over CoreLocation so the Map can behave like any map app:
/// ask for "while using" permission on first appear, then center on the user.
/// We only need authorization state here — MapKit's `UserAnnotation` and
/// `MapCameraPosition.userLocation` read the device location directly.
@MainActor
final class LocationManager: NSObject, ObservableObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    @Published var authorized = false

    override init() {
        super.init()
        manager.delegate = self
        authorized = Self.isAuthorized(manager.authorizationStatus)
    }

    /// Prompt once. No-op (aside from a possible Settings deep-link elsewhere)
    /// if the user already answered.
    func request() {
        if manager.authorizationStatus == .notDetermined {
            manager.requestWhenInUseAuthorization()
        }
    }

    private static func isAuthorized(_ status: CLAuthorizationStatus) -> Bool {
        status == .authorizedWhenInUse || status == .authorizedAlways
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in self.authorized = Self.isAuthorized(status) }
    }
}
