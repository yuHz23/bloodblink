/// BB-SOS — Donation interval tests
///
/// Verify Article 6 TT 26/2013/TT-BYT compliance:
///   WB/RBC = 12 weeks, PLT/plasma = 2 weeks
///   Must filter by LAST DONATION TYPE, not a single 12-week threshold

import 'package:flutter_test/flutter_test.dart';
import 'package:bb_sos/models/donor_profile.dart';

void main() {
  group('DonationType intervals', () {
    test('WB interval is 12 weeks', () {
      expect(DonationType.wholeBlood.minWeeks, 12);
    });

    test('RBC interval is 12 weeks', () {
      expect(DonationType.redBloodCell.minWeeks, 12);
    });

    test('PLT interval is 2 weeks', () {
      expect(DonationType.platelet.minWeeks, 2);
    });

    test('FFP interval is 2 weeks', () {
      expect(DonationType.plasma.minWeeks, 2);
    });

    test('GRAN interval is 1 week', () {
      expect(DonationType.granulocyte.minWeeks, 1);
    });

    test('WB can donate after 12 weeks', () {
      final lastDonation = DateTime.now().subtract(const Duration(days: 84)); // 12 weeks
      expect(DonationType.wholeBlood.canDonateAfter(lastDonation), true);
    });

    test('WB cannot donate before 12 weeks', () {
      final lastDonation = DateTime.now().subtract(const Duration(days: 83)); // just under 12 weeks
      expect(DonationType.wholeBlood.canDonateAfter(lastDonation), false);
    });

    test('PLT can donate after 2 weeks', () {
      final lastDonation = DateTime.now().subtract(const Duration(days: 14));
      expect(DonationType.platelet.canDonateAfter(lastDonation), true);
    });

    test('PLT cannot donate before 2 weeks', () {
      final lastDonation = DateTime.now().subtract(const Duration(days: 13));
      expect(DonationType.platelet.canDonateAfter(lastDonation), false);
    });

    test('Mixed donations — last type determines interval', () {
      // If last donation was PLT (2 weeks ago), donor CAN donate PLT again
      final lastPLT = DateTime.now().subtract(const Duration(days: 14));
      expect(DonationType.platelet.canDonateAfter(lastPLT), true);

      // But if last donation was WB (2 weeks ago), donor CANNOT donate WB
      final lastWB = DateTime.now().subtract(const Duration(days: 14));
      expect(DonationType.wholeBlood.canDonateAfter(lastWB), false);
    });
  });

  group('DonorProfile', () {
    test('age calculation from birth year', () {
      final profile = DonorProfile(
        id: 'test-1',
        name: 'Nguyễn Văn A',
        abo: 'O',
        rh: '+',
        birthYear: DateTime.now().year - 25,
      );
      expect(profile.age, 25);
    });

    test('woman of childbearing age check', () {
      final woman18to45 = DonorProfile(
        id: 'test-2',
        name: 'Trần Thị B',
        abo: 'A',
        rh: '-',
        birthYear: DateTime.now().year - 30,
        sex: 'F',
      );
      expect(woman18to45.isWomanOfChildbearingAge, true);

      final womanOver45 = DonorProfile(
        id: 'test-3',
        name: 'Lê Thị C',
        abo: 'O',
        rh: '-',
        birthYear: DateTime.now().year - 50,
        sex: 'F',
      );
      expect(womanOver45.isWomanOfChildbearingAge, false);

      final man = DonorProfile(
        id: 'test-4',
        name: 'Phạm Văn D',
        abo: 'B',
        rh: '+',
        birthYear: DateTime.now().year - 30,
        sex: 'M',
      );
      expect(man.isWomanOfChildbearingAge, false);
    });

    test('blood type string', () {
      final profile = DonorProfile(
        id: 'test-5',
        name: 'Test',
        abo: 'O',
        rh: '-',
        birthYear: 1990,
      );
      expect(profile.bloodType, 'O-');
    });

    test('geocell TTL validation', () {
      // Expired TTL
      expect(H3Config.isGeocellExpired(DateTime.now().subtract(const Duration(hours: 1))), true);
      // Valid TTL
      expect(H3Config.isGeocellExpired(DateTime.now().add(const Duration(hours: 3))), false);
      // Null TTL (never set)
      expect(H3Config.isGeocellExpired(null), true);
    });

    test('new geocell TTL is 4 hours from now', () {
      final ttl = H3Config.newGeocellTtl();
      final expected = DateTime.now().add(H3Config.cellTtl);
      // Should be within 1 second of expected
      expect(ttl.difference(expected).inSeconds.abs(), lessThan(2));
    });
  });

  group('H3Config', () {
    test('resolution is 7 (~1.2 km)', () {
      expect(H3Config.resolution, 7);
    });

    test('cell TTL is 4 hours', () {
      expect(H3Config.cellTtl, const Duration(hours: 4));
    });

    test('SOS rings have 4 levels', () {
      expect(SosRing.rings.length, 4);
    });

    test('SOS ring timing matches spec', () {
      expect(SosRing.rings[0].triggerMinutes, 0);
      expect(SosRing.rings[1].triggerMinutes, 10);
      expect(SosRing.rings[2].triggerMinutes, 25);
      expect(SosRing.rings[3].triggerMinutes, 45);
    });
  });
}