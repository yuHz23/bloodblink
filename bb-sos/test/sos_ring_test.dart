import 'package:flutter_test/flutter_test.dart';
import 'package:bb_sos/models/donor_profile.dart';

void main() {
  group('SOS Ring Escalation Logic', () {
    test('Ring 0 should trigger immediately (0 min)', () {
      final ring = SosRing.rings[0];
      expect(ring.ring, 0);
      expect(ring.triggerMinutes, 0);
    });

    test('Ring 1 should trigger at 10 min', () {
      final ring = SosRing.rings[1];
      expect(ring.ring, 1);
      expect(ring.triggerMinutes, 10);
    });

    test('Ring 2 should trigger at 25 min', () {
      final ring = SosRing.rings[2];
      expect(ring.ring, 2);
      expect(ring.triggerMinutes, 25);
    });

    test('Ring 3 should trigger at 45 min', () {
      final ring = SosRing.rings[3];
      expect(ring.ring, 3);
      expect(ring.triggerMinutes, 45);
    });

    test('H3 Config defines correct TTL', () {
      expect(H3Config.cellTtl, const Duration(hours: 4));
    });
    
    test('H3 Geocell expiration logic works', () {
      final pastTtl = DateTime.now().subtract(const Duration(minutes: 5));
      final futureTtl = DateTime.now().add(const Duration(minutes: 5));
      
      expect(H3Config.isGeocellExpired(null), true);
      expect(H3Config.isGeocellExpired(pastTtl), true);
      expect(H3Config.isGeocellExpired(futureTtl), false);
    });
    
    test('New Geocell TTL is 4 hours from now', () {
      final ttl = H3Config.newGeocellTtl();
      final difference = ttl.difference(DateTime.now());
      // Due to execution time, it might be slightly less than 4 hours, but > 3h 59m
      expect(difference.inMinutes >= 239, true);
      expect(difference.inMinutes <= 240, true);
    });
  });
}
