/// BB-SOS — API Service (offline-first with queue)
///
/// Architecture:
///   - All API calls go through this service
///   - When offline, requests are queued in Hive and sent when connectivity returns
///   - H3 geocell is sent instead of raw coordinates
///   - NO patient medical data transmitted
///
/// P0: địa chỉ máy chủ đọc LÚC CHẠY từ SharedPreferences (ô "API URL" trong
/// màn Cài đặt). Trước đây nó là hằng số `String.fromEnvironment` cố định lúc
/// build, nên ô cài đặt đó không có tác dụng gì.

import 'package:flutter/foundation.dart' show kDebugMode, visibleForTesting;
import 'package:dio/dio.dart';
import 'package:hive/hive.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Backend local hiện chạy trên laptop, truy cập qua Tailscale.
///
/// Ghi đè lúc build bằng: flutter build apk --dart-define=API_URL=...
const String kDefaultApiUrl = String.fromEnvironment(
  'API_URL',
  defaultValue: 'http://laptop-rrqk96mj.tail85e1ba.ts.net:8000/api',
);

/// Dự phòng khi điện thoại không phân giải được MagicDNS.
const String kFallbackApiUrl = 'http://100.101.73.36:8000/api';

const _retiredApiUrls = <String>{
  'http://desktop-kijp57s.tail85e1ba.ts.net:8000/api',
  'http://100.106.118.107:8000/api',
};
final _trailingSlashes = RegExp(r'/+$');

class ApiException implements Exception {
  final String message;
  final int? statusCode;
  ApiException(this.message, [this.statusCode]);

  @override
  String toString() => 'ApiException: $message (${statusCode ?? 'N/A'})';
}

class ApiService {
  /// Một thực thể duy nhất — đổi URL ở màn Cài đặt là mọi màn hình dùng ngay.
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;

  late final Dio _dio;
  final Connectivity _connectivity = Connectivity();

  /// Token của chính người hiến, do `/donors/register` cấp.
  /// Người hiến không có tài khoản mật khẩu — đăng ký lại là cách lấy token mới.
  String? _token;

  /// Bí mật thiết bị, máy chủ cấp MỘT lần ở lần đăng ký đầu.
  ///
  /// Đây là thứ chứng minh "tôi là thiết bị đã đăng ký hồ sơ này" khi token đã
  /// hết hạn. Không có nó thì máy chủ từ chối đăng ký lại (nếu không thì ai đoán
  /// được mã người hiến cũng chiếm được hồ sơ).
  String? _deviceSecret;

  ApiService._internal() {
    _dio = Dio(BaseOptions(
      baseUrl: kDefaultApiUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 15),
      headers: {'Content-Type': 'application/json'},
    ));

    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) {
        if (_token != null) {
          options.headers['Authorization'] = 'Bearer $_token';
        }
        handler.next(options);
      },
      onError: (e, handler) {
        // Máy chủ nói token không dùng được nữa → bỏ token ngay tại đây, một
        // chỗ duy nhất cho mọi lời gọi. Không có bước này thì app cứ giữ mãi một
        // token đã chết và im lặng không nhận được lời kêu gọi nào.
        if (e.response?.statusCode == 401) {
          _onTokenRejected();
        }
        handler.next(e);
      },
    ));

    // CHỈ bật khi chạy bản gỡ lỗi.
    //
    // LogInterceptor mặc định in cả header, tức là in luôn
    // `Authorization: Bearer <token của người hiến>`; `responseBody: true` thì in
    // cả token vừa cấp lẫn toàn bộ hộp thư SOS. Bật trong bản phát hành nghĩa là
    // mọi app có quyền đọc log (hoặc `adb logcat`) đọc được hết.
    if (kDebugMode) {
      _dio.interceptors.add(LogInterceptor(
        requestBody: true,
        responseBody: true,
        error: true,
      ));
    }
  }

  String get baseUrl => _dio.options.baseUrl;
  bool get hasToken => _token != null;
  String? get deviceSecret => _deviceSecret;

  /// Máy chủ vừa từ chối token của mình (401) chưa?
  ///
  /// `SosInboxService` xem cờ này để biết phải lấy token mới, thay vì cứ 45 giây
  /// lại hỏi hộp thư bằng một token đã chết và im lặng không nhận được gì.
  bool _tokenRejected = false;
  bool get tokenRejected => _tokenRejected;

  /// Chuyển URL máy chủ cũ sang laptop hiện tại, giữ nguyên URL tuỳ chỉnh.
  @visibleForTesting
  static String resolveSavedBaseUrl(String? savedUrl) {
    final candidate = savedUrl?.trim();
    if (candidate == null || candidate.isEmpty) return kDefaultApiUrl;

    final normalized = candidate.replaceFirst(_trailingSlashes, '');
    return _retiredApiUrls.contains(normalized) ? kDefaultApiUrl : candidate;
  }

  /// Nạp URL và token đã lưu. Gọi một lần trong `main()` trước `runApp`.
  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString('api_url');
    if (saved != null && saved.trim().isNotEmpty) {
      final resolved = resolveSavedBaseUrl(saved);
      _dio.options.baseUrl = resolved;
      if (resolved != saved.trim()) {
        await prefs.setString('api_url', resolved);
      }
    }
    _token = prefs.getString('donor_token');
    _deviceSecret = prefs.getString('donor_device_secret');
  }

  Future<void> _saveDeviceSecret(String secret) async {
    _deviceSecret = secret;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('donor_device_secret', secret);
  }

  /// Đánh dấu token đã bị máy chủ từ chối và xoá nó đi.
  ///
  /// Trước đây không chỗ nào làm việc này: `hasToken` chỉ kiểm `_token != null`
  /// nên sau 12 giờ token hết hạn, app vẫn nghĩ mình còn phiên, mọi lời gọi trả
  /// 401 và người hiến ngừng nhận được lời kêu gọi mà KHÔNG có dấu hiệu gì.
  Future<void> _onTokenRejected() async {
    _tokenRejected = true;
    await clearToken();
  }

  Future<void> _saveToken(String token) async {
    _token = token;
    _tokenRejected = false;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('donor_token', token);
  }

  /// Xoá token cục bộ (đăng xuất). Giữ lại bí mật thiết bị để còn đăng ký lại được.
  Future<void> clearToken() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('donor_token');
  }

  /// Đổi máy chủ và ghi nhớ lựa chọn.
  Future<void> setBaseUrl(String url) async {
    final trimmed = url.trim();
    if (trimmed.isEmpty) return;
    _dio.options.baseUrl = trimmed;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('api_url', trimmed);
  }

  // ── Donor Endpoints ────────────────────────────────────────────

  /// Đăng ký / cập nhật hồ sơ người hiến trên máy chủ (upsert theo id).
  ///
  /// Chỉ gửi thông tin cần cho việc ghép: nhóm máu, năm sinh, giới tính,
  /// cân nặng, ô lưới H3. KHÔNG gửi họ tên.
  Future<DonorSyncResult> registerDonor({
    required String donorId,
    required String abo,
    required String rh,
    int? birthYear,
    String? sex,
    double? weightKg,
    String? h3Cell,
    DateTime? lastDonationAt,
    int geocellTtlHours = 4,
  }) async {
    final payload = <String, dynamic>{
      'id': donorId,
      'abo': abo,
      'rh': rh,
      // Bằng chứng "hồ sơ này là của thiết bị này". Lần đăng ký đầu chưa có nên
      // bỏ trống; những lần sau thiếu nó (và token đã hết hạn) là máy chủ trả 403.
      if (_deviceSecret != null) 'device_secret': _deviceSecret,
      if (birthYear != null) 'birth_year': birthYear,
      if (sex != null) 'sex': sex,
      if (weightKg != null) 'weight_kg': weightKg.round(),
      if (h3Cell != null) 'h3_cell': h3Cell,
      if (lastDonationAt != null) 'last_donation_at': lastDonationAt.toUtc().toIso8601String(),
      'geocell_ttl_hours': geocellTtlHours,
    };

    try {
      final response = await _dio.post('/donors/register', data: payload);
      final result = DonorSyncResult.fromJson(response.data);
      if (result.accessToken != null) {
        await _saveToken(result.accessToken!);
      }
      // Máy chủ chỉ giữ bản băm nên bí mật này KHÔNG cấp lại được. Mất là phải
      // đăng ký hồ sơ mới, nên lưu ngay khi nhận.
      if (result.deviceSecret != null) {
        await _saveDeviceSecret(result.deviceSecret!);
      }
      return result;
    } on DioException catch (e) {
      if (_isOffline(e)) {
        await _queueOfflineRequest('/donors/register', payload);
        throw ApiException('Không có mạng — hồ sơ đã xếp hàng, sẽ gửi khi có kết nối');
      }
      throw ApiException(_describe(e, 'Lỗi đăng ký hồ sơ'), e.response?.statusCode);
    }
  }

  /// Danh sách cơ sở y tế kèm toạ độ.
  ///
  /// Toạ độ bệnh viện là dữ liệu CÔNG KHAI nên tải hết về máy được. Nhờ vậy
  /// việc tính "bệnh viện nào gần tôi" làm NGAY TRÊN MÁY — vị trí thô của người
  /// hiến không phải rời khỏi thiết bị, đúng ràng buộc của cả hệ thống.
  Future<List<Facility>> listFacilities() async {
    try {
      final response = await _dio.get('/facilities');
      return (response.data as List)
          .map((e) => Facility.fromJson(e as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw ApiException(_describe(e, 'Lỗi tải danh sách cơ sở y tế'),
          e.response?.statusCode);
    }
  }

  /// Làm mới ô lưới H3 + TTL (người dùng còn bật chia sẻ vị trí).
  Future<DonorSyncResult> updateGeocell({
    required String donorId,
    required String h3Cell,
    int ttlHours = 4,
  }) async {
    final payload = {'h3_cell': h3Cell, 'ttl_hours': ttlHours};
    try {
      final response = await _dio.patch('/donors/$donorId/geocell', data: payload);
      return DonorSyncResult.fromJson(response.data);
    } on DioException catch (e) {
      throw ApiException(_describe(e, 'Lỗi cập nhật ô lưới'), e.response?.statusCode);
    }
  }

  /// Rút lại đồng ý chia sẻ vị trí — xoá ô lưới trên máy chủ ngay.
  Future<void> revokeGeocell(String donorId) async {
    try {
      await _dio.delete('/donors/$donorId/geocell');
    } on DioException catch (e) {
      throw ApiException(_describe(e, 'Lỗi thu hồi vị trí'), e.response?.statusCode);
    }
  }

  /// Đọc lại hồ sơ trên máy chủ (trạng thái xác minh, điều kiện hiến).
  Future<DonorSyncResult> getDonor(String donorId, {String? componentCode}) async {
    try {
      final response = await _dio.get('/donors/$donorId', queryParameters: {
        if (componentCode != null) 'component_code': componentCode,
      });
      return DonorSyncResult.fromJson(response.data);
    } on DioException catch (e) {
      throw ApiException(_describe(e, 'Lỗi đọc hồ sơ'), e.response?.statusCode);
    }
  }

  /// Ghi nhận một lần hiến — mốc tính khoảng cách theo Điều 6.
  Future<DonorSyncResult> recordDonation({
    required String donorId,
    required String componentCode,
    DateTime? donatedAt,
    String? facilityId,
  }) async {
    final payload = {
      'component_code': componentCode,
      if (donatedAt != null) 'donated_at': donatedAt.toUtc().toIso8601String(),
      if (facilityId != null) 'facility_id': facilityId,
    };
    try {
      final response = await _dio.post('/donors/$donorId/donation', data: payload);
      return DonorSyncResult.fromJson(response.data);
    } on DioException catch (e) {
      if (_isOffline(e)) {
        await _queueOfflineRequest('/donors/$donorId/donation', payload);
        throw ApiException('Không có mạng — lần hiến đã xếp hàng');
      }
      throw ApiException(_describe(e, 'Lỗi ghi nhận lần hiến'), e.response?.statusCode);
    }
  }

  /// Đăng ký địa chỉ nhận thông báo đẩy của thiết bị.
  ///
  /// Dự án chưa có Firebase nên hiện chưa gọi tới; giữ sẵn để khi có
  /// google-services.json thì chỉ việc truyền token FCM vào đây.
  Future<void> setPushToken({
    required String donorId,
    String? token,
    String platform = 'android',
  }) async {
    try {
      await _dio.put('/donors/$donorId/push-token', data: {
        'push_token': token,
        'platform': platform,
      });
    } on DioException catch (e) {
      throw ApiException(_describe(e, 'Lỗi đăng ký thiết bị'), e.response?.statusCode);
    }
  }

  /// Hộp thư lời kêu gọi đang chờ người hiến này trả lời.
  ///
  /// Đây là kênh giao hàng khi chưa có Firebase: app hỏi rồi tự dựng thông báo
  /// trên máy. Máy chủ chỉ trả về sự kiện CÒN MỞ và chưa được trả lời.
  Future<List<SosInboxItem>> fetchSosInbox(String donorId,
      {bool includeRead = false}) async {
    try {
      final response = await _dio.get('/donors/$donorId/sos-inbox',
          queryParameters: {'include_read': includeRead});
      return (response.data as List)
          .map((e) => SosInboxItem.fromJson(e as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw ApiException(_describe(e, 'Lỗi đọc hộp thư SOS'), e.response?.statusCode);
    }
  }

  // ── SOS Endpoints ──────────────────────────────────────────────

  /// Create SOS event — the primary use case
  Future<SosEventResult> createSosEvent({
    required String facilityId,
    required String componentCode,
    required String abo,
    required String rh,
    required String urgency,
    int qty = 1,
    int ring = 0,
    String? h3Cell,
  }) async {
    final payload = {
      'facility_id': facilityId,
      'component_code': componentCode,
      'abo': abo,
      'rh': rh,
      'urgency': urgency,
      'qty': qty,
      'ring': ring,
      if (h3Cell != null) 'h3_cell': h3Cell,
    };

    try {
      final response = await _dio.post('/sos/event', data: payload);
      return SosEventResult.fromJson(response.data);
    } on DioException catch (e) {
      if (_isOffline(e)) {
        await _queueOfflineRequest('/sos/event', payload);
        return SosEventResult(
          id: 'offline-${DateTime.now().millisecondsSinceEpoch}',
          status: 'queued',
          message: 'Không có mạng — yêu cầu đã được xếp hàng và sẽ gửi khi có kết nối',
        );
      }
      throw ApiException(_describe(e, 'Lỗi mở lời kêu gọi'), e.response?.statusCode);
    }
  }

  /// Find nearby donors using H3 geocell search
  Future<NearbyDonorsResult> findNearbyDonors({
    required String h3Cell,
    String? abo,
    String? rh,
    String componentCode = 'WB',
    int ring = 0,
    bool eligibleOnly = false,
  }) async {
    try {
      final params = <String, dynamic>{
        'h3_cell': h3Cell,
        'component_code': componentCode,
        'ring': ring,
        'eligible_only': eligibleOnly,
      };
      if (abo != null) params['abo'] = abo;
      if (rh != null) params['rh'] = rh;

      final response = await _dio.get('/sos/donors/nearby', queryParameters: params);
      return NearbyDonorsResult.fromJson(response.data);
    } on DioException catch (e) {
      throw ApiException(_describe(e, 'Lỗi tìm người hiến'), e.response?.statusCode);
    }
  }

  /// Respond to SOS event
  Future<void> respondToSos({
    required String eventId,
    required String donorId,
    required String response,
    String? contactPhone,
    String? contactNote,
    bool? shareLocation,
    double? latitude,
    double? longitude,
  }) async {
    final payload = {
      'donor_id': donorId,
      'response': response,
      // Máy chủ bỏ qua hai trường này nếu từ chối — không giữ số của người
      // đã nói "không thể".
      if (contactPhone != null && contactPhone.trim().isNotEmpty)
        'contact_phone': contactPhone.trim(),
      if (contactNote != null && contactNote.trim().isNotEmpty)
        'contact_note': contactNote.trim(),
      if (shareLocation != null) 'share_location': shareLocation,
      if (shareLocation == true && latitude != null) 'latitude': latitude,
      if (shareLocation == true && longitude != null) 'longitude': longitude,
    };
    try {
      await _dio.post('/sos/event/$eventId/respond', data: payload);
    } on DioException catch (e) {
      if (_isOffline(e)) {
        await _queueOfflineRequest('/sos/event/$eventId/respond', payload);
        return;
      }
      throw ApiException(_describe(e, 'Lỗi phản hồi'), e.response?.statusCode);
    }
  }

  // ── Routing Endpoints ──────────────────────────────────────────

  /// Get ETA between two coordinates
  Future<EtaResult> getEta({
    required double fromLat,
    required double fromLon,
    required double toLat,
    required double toLon,
    String mode = 'car',
  }) async {
    try {
      final response = await _dio.get('/routing/eta', queryParameters: {
        'from_lat': fromLat,
        'from_lon': fromLon,
        'to_lat': toLat,
        'to_lon': toLon,
        'mode': mode,
      });
      return EtaResult.fromJson(response.data);
    } on DioException catch (e) {
      throw ApiException(_describe(e, 'Lỗi tính ETA'), e.response?.statusCode);
    }
  }

  // ── Offline Queue ──────────────────────────────────────────────

  bool _isOffline(DioException e) =>
      e.type == DioExceptionType.connectionError ||
      e.type == DioExceptionType.connectionTimeout;

  /// Lấy thông điệp lỗi máy chủ trả về thay vì chỉ "Http status error [422]".
  String _describe(DioException e, String fallback) {
    final code = e.response?.statusCode;
    if (code == 401) {
      return 'Phiên đã hết hạn — bấm Lưu hồ sơ để đăng ký lại và lấy phiên mới';
    }
    if (code == 403) {
      return 'Không đủ quyền cho thao tác này';
    }
    final data = e.response?.data;
    if (data is Map && data['detail'] != null) return data['detail'].toString();
    return e.message ?? fallback;
  }

  /// Queue a request for later when offline
  Future<void> _queueOfflineRequest(String path, Map<String, dynamic> data) async {
    final box = await Hive.openBox('pending_responses');
    await box.add({
      'path': path,
      'data': data,
      'queued_at': DateTime.now().toIso8601String(),
    });
  }

  /// Process queued requests when connectivity returns
  Future<int> processOfflineQueue() async {
    final box = await Hive.openBox('pending_responses');
    if (box.isEmpty) return 0;

    int processed = 0;
    final keysToDelete = <dynamic>[];

    for (final key in box.keys) {
      final item = box.get(key) as Map;
      try {
        final path = item['path'] as String;
        final data = Map<String, dynamic>.from(item['data'] as Map);
        // Ô lưới dùng phương thức PATCH, phần còn lại là POST.
        if (path.endsWith('/geocell')) {
          await _dio.patch(path, data: data);
        } else {
          await _dio.post(path, data: data);
        }
        keysToDelete.add(key);
        processed++;
      } on DioException catch (e) {
        if (_isOffline(e)) break;      // vẫn mất mạng — để nguyên hàng đợi

        // 401/403/429 là hỏng TẠM THỜI: token hết hạn trong lúc nằm chờ, hoặc
        // máy chủ đang chặn nhịp. Vứt ở đây nghĩa là người hiến đã bấm "Nhận lời"
        // mà bệnh viện không bao giờ biết — giữ lại để gửi sau khi lấy token mới.
        final code = e.response?.statusCode ?? 0;
        if (code == 401 || code == 403 || code == 429) {
          if (code == 401) await _onTokenRejected();
          break;
        }
        keysToDelete.add(key);          // 4xx khác: gửi lại cũng hỏng, bỏ khỏi hàng đợi
      }
    }

    for (final key in keysToDelete) {
      await box.delete(key);
    }

    return processed;
  }

  /// Số yêu cầu đang chờ gửi.
  Future<int> pendingCount() async {
    final box = await Hive.openBox('pending_responses');
    return box.length;
  }

  /// Check if device is online
  Future<bool> isOnline() async {
    final result = await _connectivity.checkConnectivity();
    return !result.contains(ConnectivityResult.none);
  }

  // ── Health Check ──────────────────────────────────────────────

  Future<bool> healthCheck() async {
    try {
      final response = await _dio.get('/health');
      return response.data['status'] == 'ok';
    } catch (_) {
      return false;
    }
  }
}

// ── Result models ─────────────────────────────────────────────────

/// Hồ sơ người hiến do máy chủ trả về sau khi đăng ký / cập nhật.
/// Một cơ sở y tế, kèm toạ độ để app tự tính khoảng cách.
class Facility {
  final String id;
  final String name;
  final String tier;      // trung ương | tỉnh | quận-huyện …
  final double lat;
  final double lon;
  final bool optIn;

  const Facility({
    required this.id,
    required this.name,
    required this.tier,
    required this.lat,
    required this.lon,
    this.optIn = true,
  });

  factory Facility.fromJson(Map<String, dynamic> json) => Facility(
        id: json['id'] ?? '',
        name: json['name'] ?? '',
        tier: json['tier'] ?? '',
        lat: (json['lat'] as num?)?.toDouble() ?? 0,
        lon: (json['lon'] as num?)?.toDouble() ?? 0,
        optIn: json['opt_in'] ?? true,
      );
}

class DonorSyncResult {
  final String id;
  final String bloodType;
  final bool verified;
  final String? geocellH3;
  final DateTime? geocellTtl;
  final bool geocellValid;
  final bool eligible;
  final int? daysSinceDonation;
  final String? ineligibleReason;

  /// Chỉ có trong đáp của `/donors/register`.
  final String? accessToken;

  /// Chỉ có ở LẦN ĐẦU đăng ký (hoặc lần đầu hồ sơ cũ được cấp bí mật).
  final String? deviceSecret;

  DonorSyncResult({
    required this.id,
    required this.bloodType,
    required this.verified,
    this.geocellH3,
    this.geocellTtl,
    this.geocellValid = false,
    this.eligible = true,
    this.daysSinceDonation,
    this.ineligibleReason,
    this.accessToken,
    this.deviceSecret,
  });

  factory DonorSyncResult.fromJson(Map<String, dynamic> json) {
    return DonorSyncResult(
      id: json['id'] ?? '',
      bloodType: json['blood_type'] ?? '${json['abo'] ?? ''}${json['rh'] ?? ''}',
      verified: json['verified'] ?? false,
      geocellH3: json['geocell_h3'],
      geocellTtl: json['geocell_ttl'] != null ? DateTime.tryParse(json['geocell_ttl']) : null,
      geocellValid: json['geocell_valid'] ?? false,
      eligible: json['eligible'] ?? true,
      daysSinceDonation: json['days_since_donation'],
      ineligibleReason: json['ineligible_reason'],
      accessToken: json['access_token'],
      deviceSecret: json['device_secret'],
    );
  }
}

/// Một lời kêu gọi đang chờ trong hộp thư của người hiến.
class SosInboxItem {
  final String notificationId;
  final String eventId;
  final int ring;
  final DateTime notifiedAt;
  final String status;

  final String? abo;
  final String? rh;
  final String? bloodType;
  final String? componentCode;
  final String? urgency;
  final int targetCount;
  final int acceptCount;
  final String eventStatus;
  final String? facilityId;
  final String? facilityName;

  final String title;
  final String body;

  SosInboxItem({
    required this.notificationId,
    required this.eventId,
    required this.ring,
    required this.notifiedAt,
    required this.status,
    this.abo,
    this.rh,
    this.bloodType,
    this.componentCode,
    this.urgency,
    this.targetCount = 1,
    this.acceptCount = 0,
    this.eventStatus = 'open',
    this.facilityId,
    this.facilityName,
    this.title = '',
    this.body = '',
  });

  factory SosInboxItem.fromJson(Map<String, dynamic> json) {
    return SosInboxItem(
      notificationId: json['notification_id'] ?? '',
      eventId: json['event_id'] ?? '',
      ring: json['ring'] ?? 0,
      notifiedAt: DateTime.tryParse(json['notified_at'] ?? '') ?? DateTime.now(),
      status: json['status'] ?? 'pending',
      abo: json['abo'],
      rh: json['rh'],
      bloodType: json['blood_type'],
      componentCode: json['component_code'],
      urgency: json['urgency'],
      targetCount: json['target_count'] ?? 1,
      acceptCount: json['accept_count'] ?? 0,
      eventStatus: json['event_status'] ?? 'open',
      facilityId: json['facility_id'],
      facilityName: json['facility_name'],
      title: json['title'] ?? '',
      body: json['body'] ?? '',
    );
  }
}

class SosEventResult {
  final String id;
  final String status;
  final String message;
  final int donorsNotified;

  SosEventResult({
    required this.id,
    required this.status,
    required this.message,
    this.donorsNotified = 0,
  });

  factory SosEventResult.fromJson(Map<String, dynamic> json) {
    return SosEventResult(
      id: json['id'] ?? '',
      status: json['status'] ?? 'unknown',
      message: json['message'] ?? '',
      donorsNotified: json['donors_notified'] ?? 0,
    );
  }
}

class NearbyDonorsResult {
  final int totalDonors;
  final List<NearbyDonor> donors;

  NearbyDonorsResult({required this.totalDonors, required this.donors});

  factory NearbyDonorsResult.fromJson(Map<String, dynamic> json) {
    return NearbyDonorsResult(
      totalDonors: json['total_donors'] ?? json['donors_found'] ?? 0,
      donors: (json['donors'] as List? ?? [])
          .map((d) => NearbyDonor.fromJson(d))
          .toList(),
    );
  }
}

class NearbyDonor {
  final String donorId;
  final String abo;
  final String rh;
  final String? h3Cell;
  final bool eligible;
  final String? ineligibleReason;

  NearbyDonor({
    required this.donorId,
    required this.abo,
    required this.rh,
    this.h3Cell,
    required this.eligible,
    this.ineligibleReason,
  });

  factory NearbyDonor.fromJson(Map<String, dynamic> json) {
    return NearbyDonor(
      donorId: json['donor_id'] ?? '',
      abo: json['abo'] ?? '',
      rh: json['rh'] ?? '',
      h3Cell: json['h3_cell'],
      eligible: json['eligible'] ?? false,
      ineligibleReason: json['ineligible_reason'],
    );
  }
}

class EtaResult {
  final double distanceM;
  final double durationS;
  final double durationMin;
  final String provider;
  final String mode;

  EtaResult({
    required this.distanceM,
    required this.durationS,
    required this.durationMin,
    required this.provider,
    required this.mode,
  });

  factory EtaResult.fromJson(Map<String, dynamic> json) {
    return EtaResult(
      distanceM: (json['distance_m'] ?? 0).toDouble(),
      durationS: (json['duration_s'] ?? 0).toDouble(),
      durationMin: (json['duration_min'] ?? 0).toDouble(),
      provider: json['provider'] ?? 'unknown',
      mode: json['routing_mode'] ?? 'unknown',
    );
  }
}
