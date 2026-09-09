/// BB-SOS — Donor Profile Model
///
/// Privacy architecture:
///   - H3 geocell (~1 km) with TTL instead of raw GPS coordinates
///   - NO patient medical data stored
///   - Donation interval filtering per Article 6 TT 26/2013/TT-BYT:
///     WB/RBC = 12 weeks, PLT/plasma = 2 weeks
///
/// The donor profile is stored LOCALLY on the device (Hive),
/// never sent to the server in full — only the H3 geocell
/// is transmitted with a TTL for the SOS search radius.

import 'package:hive/hive.dart';

/// Donation types for interval filtering (Article 6)
enum DonationType {
  wholeBlood('WB', 'Máu toàn phần', 12),    // 12 weeks
  redBloodCell('RBC', 'Khối hồng cầu', 12),  // 12 weeks
  platelet('PLT', 'Tiểu cầu', 2),             // 2 weeks
  plasma('FFP', 'Huyết tương', 2),            // 2 weeks
  granulocyte('GRAN', 'Bạch cầu hạt', 1);     // ≤3 times/7 days → 1 week safety

  const DonationType(this.code, this.label, this.minWeeks);

  final String code;
  final String label;
  final int minWeeks;  // Minimum interval in weeks

  /// Check if donor can donate again based on last donation type
  bool canDonateAfter(DateTime lastDonationDate) {
    final minInterval = Duration(days: minWeeks * 7);
    return DateTime.now().difference(lastDonationDate) >= minInterval;
  }
}

@HiveType(typeId: 0)
class DonorProfile extends HiveObject {
  @HiveField(0)
  String id;  // UUID, generated locally

  @HiveField(1)
  String name;  // Display name (optional, for UI only)

  @HiveField(2)
  String abo;  // O, A, B, AB

  @HiveField(3)
  String rh;   // + or -

  @HiveField(4)
  int birthYear;  // Only year stored for age calculation

  @HiveField(5)
  String? sex;  // 'M' or 'F' — needed for RhD constraint check

  @HiveField(6)
  double? weightKg;  // Optional, per Article 4 requirements

  @HiveField(7)
  String? h3Cell;  // H3 geocell (~1 km resolution), NOT raw coordinates

  @HiveField(8)
  DateTime? h3CellTtl;  // When this geocell expires (privacy)

  @HiveField(9)
  String? facilityId;  // Preferred facility

  @HiveField(10)
  bool isRegistered;  // Has completed full registration

  @HiveField(11)
  DateTime createdAt;

  DonorProfile({
    required this.id,
    required this.name,
    required this.abo,
    required this.rh,
    required this.birthYear,
    this.sex,
    this.weightKg,
    this.h3Cell,
    this.h3CellTtl,
    this.facilityId,
    this.isRegistered = false,
    DateTime? createdAt,
  }) : createdAt = createdAt ?? DateTime.now();

  /// Check if the H3 geocell is still valid (not expired)
  bool get isGeocellValid {
    if (h3CellTtl == null) return false;
    return DateTime.now().isBefore(h3CellTtl!);
  }

  /// Calculate age from birth year
  int get age => DateTime.now().year - birthYear;

  /// Check if woman of childbearing age (18-45) — for RhD constraint
  bool get isWomanOfChildbearingAge => sex == 'F' && age >= 18 && age <= 45;

  /// Full blood type string
  String get bloodType => '$abo$rh';

  /// Can donate based on most recent donation?
  bool canDonate(List<DonationRecord> history) {
    if (history.isEmpty) return true;
    final lastDonation = history.reduce((a, b) =>
      a.donatedAt.isAfter(b.donatedAt) ? a : b);
    return lastDonation.type.canDonateAfter(lastDonation.donatedAt);
  }

  /// Minimum weeks until next donation
  int? weeksUntilNextDonation(List<DonationRecord> history) {
    if (history.isEmpty) return 0;
    final lastDonation = history.reduce((a, b) =>
      a.donatedAt.isAfter(b.donatedAt) ? a : b);
    final elapsed = DateTime.now().difference(lastDonation.donatedAt);
    final required = Duration(days: lastDonation.type.minWeeks * 7);
    if (elapsed >= required) return 0;
    return ((required - elapsed).inDays / 7).ceil();
  }
}

@HiveType(typeId: 1)
class DonationRecord extends HiveObject {
  @HiveField(0)
  String id;

  @HiveField(1)
  DonationType type;

  @HiveField(2)
  DateTime donatedAt;

  @HiveField(3)
  String? facilityId;

  @HiveField(4)
  String? notes;

  DonationRecord({
    required this.id,
    required this.type,
    required this.donatedAt,
    this.facilityId,
    this.notes,
  });
}

/// H3 geocell configuration
class H3Config {
  /// H3 resolution: 7 = ~1.2 km edge length (urban-appropriate)
  /// Resolution 7 gives cells of approximately 1.22 km edge length
  /// This is the privacy sweet spot — accurate enough for SOS radius,
  /// coarse enough to prevent precise location tracking
  static const int resolution = 7;

  /// TTL for H3 geocell: 4 hours
  /// After this, the cell is considered stale and must be refreshed
  static const Duration cellTtl = Duration(hours: 4);

  /// SOS ring radii in H3 cell counts (approximate)
  /// Ring 0: same cell (~1 km) — same blood type
  /// Ring 1: 1 cell away (~3 km) — compatible types
  /// Ring 2: 2 cells away (~5 km) — all compatible + registered
  /// Ring 3: city-wide — hospital alert
  static const List<int> sosRingCells = [0, 1, 2, -1];  // -1 = all cells

  /// Ring timing (minutes from SOS event start)
  static const List<int> sosRingMinutes = [0, 10, 25, 45];

  /// Check if a geocell is expired
  static bool isGeocellExpired(DateTime? ttl) {
    if (ttl == null) return true;
    return DateTime.now().isAfter(ttl);
  }

  /// Generate a new TTL for a geocell
  static DateTime newGeocellTtl() {
    return DateTime.now().add(cellTtl);
  }
}

/// SOS Ring definitions
class SosRing {
  final int ring;
  final String label;
  final String description;
  final String radius;
  final int triggerMinutes;
  final String color;

  const SosRing({
    required this.ring,
    required this.label,
    required this.description,
    required this.radius,
    required this.triggerMinutes,
    required this.color,
  });

  static const List<SosRing> rings = [
    SosRing(
      ring: 0,
      label: 'Vòng 0 — Cùng nhóm máu',
      description: 'Thông báo đẩy FCM đến người hiến cùng nhóm máu trong phạm vi ~1 km',
      radius: '~1 km',
      triggerMinutes: 0,
      color: '#3B82F6',  // blue
    ),
    SosRing(
      ring: 1,
      label: 'Vòng 1 — Tương hợp',
      description: 'Mở rộng tìm kiếm đến nhóm máu tương hợp, bán kính ~3 km',
      radius: '~3 km',
      triggerMinutes: 10,
      color: '#F59E0B',  // amber
    ),
    SosRing(
      ring: 2,
      label: 'Vòng 2 — Mở rộng',
      description: 'Mở rộng đến tất cả nhóm tương hợp + người đã đăng ký, bán kính ~5 km',
      radius: '~5 km',
      triggerMinutes: 25,
      color: '#EF4444',  // red
    ),
    SosRing(
      ring: 3,
      label: 'Vòng 3 — Toàn viện',
      description: 'Cảnh báo toàn khoa, kích hoạt giao thức cấp cứu',
      radius: 'Toàn TP.HCM',
      triggerMinutes: 45,
      color: '#7C3AED',  // purple
    ),
  ];
}