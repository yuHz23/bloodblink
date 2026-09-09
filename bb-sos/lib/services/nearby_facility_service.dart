/// BB-SOS — Tìm bệnh viện gần.
///
/// Toàn bộ phép tính khoảng cách chạy TRÊN MÁY. App tải danh sách cơ sở y tế
/// (toạ độ bệnh viện là dữ liệu công khai) rồi so với vị trí hiện tại của thiết
/// bị. Máy chủ không hề biết người hiến đang đứng ở đâu — giữ đúng ràng buộc
/// "không lưu toạ độ GPS thô" của cả hệ thống, và cũng là câu trả lời sẵn khi
/// hội đồng hỏi "tính năng này có làm lộ vị trí không".
///
/// Danh sách cơ sở được nhớ tạm trong phiên: nó gần như không đổi, tải lại mỗi
/// lần mở màn hình chỉ tốn mạng.

library;

import 'dart:math' as math;

import 'package:geolocator/geolocator.dart';

import 'api_service.dart';
import 'location_service.dart';

/// Một cơ sở y tế kèm khoảng cách tới người dùng.
class NearbyFacility {
  final Facility facility;

  /// Khoảng cách đường chim bay, mét. Null khi chưa biết vị trí người dùng.
  final double? distanceMeters;

  const NearbyFacility({required this.facility, this.distanceMeters});

  /// "1,2 km" / "850 m" — dạng người Việt đọc quen.
  String get distanceLabel {
    final d = distanceMeters;
    if (d == null) return '—';
    if (d < 1000) return '${d.round()} m';
    final km = d / 1000;
    return '${km.toStringAsFixed(km < 10 ? 1 : 0).replaceAll('.', ',')} km';
  }

  /// Ước lượng thời gian đi xe máy, chỉ để người dùng hình dung.
  ///
  /// Dùng ĐÚNG tốc độ mà `StraightLineRouting` bên máy chủ dùng cho xe máy
  /// (30 km/h) để hai bên không nói hai con số khác nhau về cùng quãng đường.
  String get rideTimeLabel {
    final d = distanceMeters;
    if (d == null) return '—';
    final minutes = (d / 1000 / 30 * 60).round();
    return minutes < 1 ? 'dưới 1 phút' : '~$minutes phút';
  }
}

class NearbyFacilityService {
  NearbyFacilityService._();
  static final NearbyFacilityService instance = NearbyFacilityService._();

  final ApiService _api = ApiService();

  List<Facility>? _cache;

  /// Bán kính Trái Đất trung bình (mét).
  static const double _earthRadius = 6371000;

  /// Khoảng cách đường chim bay giữa hai điểm (haversine).
  ///
  /// Đây là khoảng cách THẲNG, không phải quãng đường thật — màn hình phải nói
  /// rõ điều đó, đường bộ ở TP.HCM thường dài hơn.
  static double haversineMeters(
      double lat1, double lon1, double lat2, double lon2) {
    double rad(double deg) => deg * math.pi / 180;
    final dLat = rad(lat2 - lat1);
    final dLon = rad(lon2 - lon1);
    final a = math.pow(math.sin(dLat / 2), 2) +
        math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.pow(math.sin(dLon / 2), 2);
    return _earthRadius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a));
  }

  /// Sắp xếp danh sách cơ sở theo khoảng cách tới một điểm cho trước.
  ///
  /// Tách riêng khỏi phần lấy GPS để test được mà không cần thiết bị thật.
  static List<NearbyFacility> rank(
    List<Facility> facilities,
    double? lat,
    double? lon,
  ) {
    final rows = facilities
        .map((f) => NearbyFacility(
              facility: f,
              distanceMeters:
                  (lat == null || lon == null) ? null : haversineMeters(lat, lon, f.lat, f.lon),
            ))
        .toList();

    // Chưa biết vị trí thì xếp theo tên, để danh sách không nhảy lung tung.
    if (lat == null || lon == null) {
      rows.sort((a, b) => a.facility.name.compareTo(b.facility.name));
    } else {
      rows.sort((a, b) => a.distanceMeters!.compareTo(b.distanceMeters!));
    }
    return rows;
  }

  /// Tải (hoặc dùng lại) danh sách cơ sở y tế.
  Future<List<Facility>> facilities({bool refresh = false}) async {
    if (!refresh && _cache != null) return _cache!;
    final list = await _api.listFacilities();
    _cache = list;
    return list;
  }

  /// Danh sách cơ sở đã xếp theo khoảng cách tới vị trí hiện tại.
  ///
  /// Nếu người dùng không cho quyền vị trí thì VẪN trả về danh sách — chỉ là
  /// không có khoảng cách. Người hiến vẫn cần biết bệnh viện nào có trong mạng
  /// lưới, không nên chặn cả màn hình chỉ vì thiếu GPS.
  Future<List<NearbyFacility>> nearest({bool refresh = false}) async {
    final list = await facilities(refresh: refresh);

    double? lat, lon;
    try {
      await LocationService.instance.ensurePermission();
      final pos = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.low,
        timeLimit: const Duration(seconds: 20),
      );
      lat = pos.latitude;
      lon = pos.longitude;
    } on LocationException {
      // Không có quyền — vẫn hiện danh sách, chỉ thiếu khoảng cách.
    } catch (_) {
      // GPS quá hạn hoặc lỗi khác — xử lý y hệt.
    }

    return rank(list, lat, lon);
  }
}
