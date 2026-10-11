/// BB-SOS — Location Service
///
/// Mặc định biến GPS thành ô lưới H3 (res 7 ≈ 1.22 km) trên máy và chỉ gửi ô
/// đó lên máy chủ. Toạ độ chính xác chỉ được dùng khi người hiến đồng ý chia sẻ
/// cho một ca SOS cụ thể.
///
/// Trước P0 app khai báo `geolocator` + `h3_flutter` trong pubspec nhưng không
/// dùng tới, nên `DonorProfile.h3Cell` luôn null và không ai tìm thấy người hiến.

import 'package:geolocator/geolocator.dart';
import 'package:h3_flutter/h3_flutter.dart';

import '../models/donor_profile.dart';

/// Kết quả định vị: ô lưới + thời hạn sống.
class Geocell {
  final String h3Cell;
  final DateTime ttl;

  const Geocell({required this.h3Cell, required this.ttl});

  bool get isValid => DateTime.now().isBefore(ttl);
}

class LocationException implements Exception {
  final String message;
  LocationException(this.message);
  @override
  String toString() => message;
}

class LocationService {
  LocationService._();
  static final LocationService instance = LocationService._();

  H3? _h3;
  H3 get _h3lib => _h3 ??= const H3Factory().load();

  /// Xin quyền vị trí. Ném [LocationException] kèm thông điệp tiếng Việt để
  /// màn hình hồ sơ hiển thị thẳng cho người dùng.
  Future<void> ensurePermission() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw LocationException('Dịch vụ vị trí đang tắt — hãy bật GPS rồi thử lại');
    }

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied) {
      throw LocationException('Bạn đã từ chối quyền vị trí');
    }
    if (permission == LocationPermission.deniedForever) {
      throw LocationException(
        'Quyền vị trí bị chặn vĩnh viễn — hãy mở Cài đặt hệ thống để cấp lại',
      );
    }
  }

  /// Lấy ô lưới H3 hiện tại. Trả về null nếu người dùng chưa đồng ý chia sẻ.
  Future<Geocell> currentGeocell({
    int resolution = H3Config.resolution,
    Duration ttl = H3Config.cellTtl,
  }) async {
    // Độ chính xác thấp là đủ: ô lưới rộng hơn 1 km, lấy GPS chính xác cao chỉ
    // tốn pin và thu thập nhiều hơn mức cần thiết.
    final position = await currentPosition(
      accuracy: LocationAccuracy.low,
    );

    return cellFor(position.latitude, position.longitude,
        resolution: resolution, ttl: ttl);
  }

  /// Lấy vị trí GPS sau khi màn hình đã xin đồng ý chia sẻ cho ca SOS cụ thể.
  Future<Position> currentPosition({
    LocationAccuracy accuracy = LocationAccuracy.high,
  }) async {
    await ensurePermission();
    return Geolocator.getCurrentPosition(
      desiredAccuracy: accuracy,
      timeLimit: const Duration(seconds: 20),
    );
  }

  /// Chuyển một cặp toạ độ thành ô lưới — tách riêng để test được không cần GPS.
  Geocell cellFor(
    double lat,
    double lon, {
    int resolution = H3Config.resolution,
    Duration ttl = H3Config.cellTtl,
  }) {
    final index = _h3lib.geoToCell(GeoCoord(lat: lat, lon: lon), resolution);
    return Geocell(
      // Chuỗi hex chữ thường — đúng dạng thư viện h3 bên Python sinh ra,
      // nếu khác dạng thì so ô lưới ở server sẽ không bao giờ khớp.
      h3Cell: index.toRadixString(16),
      ttl: DateTime.now().add(ttl),
    );
  }
}
