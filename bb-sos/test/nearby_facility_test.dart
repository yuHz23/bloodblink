/// Kiểm phần tính khoảng cách của tính năng "Bệnh viện gần bạn".
///
/// Chỉ kiểm hàm thuần — phần lấy GPS tách riêng nên test chạy được không cần
/// thiết bị thật.

library;

import 'package:flutter_test/flutter_test.dart';
import 'package:bb_sos/services/api_service.dart';
import 'package:bb_sos/services/nearby_facility_service.dart';

Facility fac(String id, String name, double lat, double lon) =>
    Facility(id: id, name: name, tier: 'trung ương', lat: lat, lon: lon);

// Toạ độ thật của ba cơ sở trong dữ liệu dự án.
final choRay = fac('fac-bv-cho-ray', 'BV Chợ Rẫy', 10.7546, 106.6633);
final tmhh = fac('fac-bv-tmhh', 'BV Truyền máu Huyết học', 10.7625, 106.6602);
final nhiDong = fac('fac-bv-nhi-dong', 'BV Nhi Đồng 1', 10.7686, 106.6710);

void main() {
  group('haversine', () {
    test('cùng một điểm thì khoảng cách bằng 0', () {
      expect(
        NearbyFacilityService.haversineMeters(10.7546, 106.6633, 10.7546, 106.6633),
        closeTo(0, 0.001),
      );
    });

    test('Chợ Rẫy → Truyền máu Huyết học khoảng 0,9 km', () {
      final d = NearbyFacilityService.haversineMeters(
          choRay.lat, choRay.lon, tmhh.lat, tmhh.lon);
      expect(d, greaterThan(700));
      expect(d, lessThan(1200));
    });

    test('đối xứng — đo chiều nào cũng như nhau', () {
      final a = NearbyFacilityService.haversineMeters(
          choRay.lat, choRay.lon, nhiDong.lat, nhiDong.lon);
      final b = NearbyFacilityService.haversineMeters(
          nhiDong.lat, nhiDong.lon, choRay.lat, choRay.lon);
      expect(a, closeTo(b, 0.001));
    });
  });

  group('xếp hạng', () {
    test('xếp theo khoảng cách tăng dần từ vị trí người dùng', () {
      // Đứng ngay tại Chợ Rẫy.
      final rows = NearbyFacilityService.rank(
          [nhiDong, tmhh, choRay], choRay.lat, choRay.lon);

      expect(rows.first.facility.id, 'fac-bv-cho-ray');
      expect(rows.first.distanceMeters, closeTo(0, 1));
      // Danh sách phải tăng dần, không được nhảy cóc.
      for (var i = 1; i < rows.length; i++) {
        expect(rows[i].distanceMeters!,
            greaterThanOrEqualTo(rows[i - 1].distanceMeters!));
      }
    });

    test('chưa có vị trí thì vẫn trả đủ danh sách, xếp theo tên', () {
      // Không có GPS KHÔNG được làm rỗng màn hình — người hiến vẫn cần biết
      // bệnh viện nào có trong mạng lưới.
      final rows = NearbyFacilityService.rank([nhiDong, tmhh, choRay], null, null);

      expect(rows.length, 3);
      expect(rows.every((r) => r.distanceMeters == null), isTrue);
      expect(rows.map((r) => r.facility.name).toList(),
          ['BV Chợ Rẫy', 'BV Nhi Đồng 1', 'BV Truyền máu Huyết học']);
    });
  });

  group('nhãn hiển thị', () {
    NearbyFacility row(double? m) =>
        NearbyFacility(facility: choRay, distanceMeters: m);

    test('dưới 1 km hiện theo mét', () {
      expect(row(850).distanceLabel, '850 m');
    });

    test('từ 1 km trở lên hiện theo km, dùng dấu phẩy kiểu Việt', () {
      expect(row(4300).distanceLabel, '4,3 km');
    });

    test('chưa biết khoảng cách thì hiện gạch ngang, không hiện 0', () {
      expect(row(null).distanceLabel, '—');
      expect(row(null).rideTimeLabel, '—');
    });

    test('thời gian xe máy dùng đúng tốc độ 30 km/h như máy chủ', () {
      // 15 km ở 30 km/h = 30 phút. Lệch tốc độ với máy chủ là hai bên nói hai
      // con số khác nhau về cùng quãng đường.
      expect(row(15000).rideTimeLabel, '~30 phút');
    });
  });
}
