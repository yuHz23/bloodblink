/// BB-SOS — Settings Screen
///
/// App settings: API URL, notification preferences, privacy controls,
/// H3 geocell management, offline queue status.

import 'package:flutter/material.dart';

import '../theme/bb_colors.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:hive/hive.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../models/donor_profile.dart';
import '../services/api_service.dart';
import 'login_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _api = ApiService();

  String _apiUrl = kDefaultApiUrl;
  String? _connectionStatus;

  /// Phiên bản đọc từ chính bản cài, không cắm cứng trong mã.
  String _appVersion = '';
  bool _checking = false;
  bool _pushNotifications = true;
  bool _sosAlerts = true;
  bool _locationSharing = false;
  int _h3Resolution = 7;
  int _offlineQueueSize = 0;

  @override
  void initState() {
    super.initState();
    _loadSettings();
    _loadVersion();
  }

  /// Lấy phiên bản THẬT của bản đang cài.
  ///
  /// Trước đây chỗ này là chuỗi cắm cứng `'BLOODBLINK SOS v0.8.0'`, và nó đứng
  /// yên suốt trong khi app đi tới v1.4 — máy đang chạy bản nào thì màn Cài đặt
  /// vẫn khai v0.8.0. Đọc từ `PackageInfo` thì không có gì để trôi nữa.
  Future<void> _loadVersion() async {
    try {
      final info = await PackageInfo.fromPlatform();
      if (mounted) {
        setState(() => _appVersion = 'v${info.version} (build ${info.buildNumber})');
      }
    } catch (_) {
      // Không đọc được thì để trống còn hơn hiện một con số sai.
    }
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    final box = await Hive.openBox('pending_responses');
    setState(() {
      _apiUrl = prefs.getString('api_url') ?? kDefaultApiUrl;
      _pushNotifications = prefs.getBool('push_notifications') ?? true;
      _sosAlerts = prefs.getBool('sos_alerts') ?? true;
      _locationSharing = prefs.getBool('location_sharing') ?? false;
      _h3Resolution = prefs.getInt('h3_resolution') ?? 7;
      _offlineQueueSize = box.length;
    });
  }

  /// Gọi /api/health và đẩy nốt hàng đợi ngoại tuyến nếu máy chủ trả lời.
  Future<void> _checkConnection() async {
    setState(() {
      _checking = true;
      _connectionStatus = null;
    });

    final ok = await _api.healthCheck();
    int sent = 0;
    if (ok) sent = await _api.processOfflineQueue();
    final pending = await _api.pendingCount();

    if (!mounted) return;
    setState(() {
      _checking = false;
      _offlineQueueSize = pending;
      _connectionStatus = ok
          ? 'Kết nối được máy chủ ✓${sent > 0 ? ' — đã gửi $sent yêu cầu chờ' : ''}'
          : 'Không gọi được $_apiUrl';
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Cài đặt')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Connection
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.cloud_outlined, size: 20),
                      SizedBox(width: 8),
                      Text('Kết nối', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                    ],
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    initialValue: _apiUrl,
                    decoration: InputDecoration(
                      labelText: 'API URL',
                      hintText: kDefaultApiUrl,
                      prefixIcon: const Icon(Icons.link),
                      helperText: 'Mặc định: laptop chạy bb-core qua Tailscale. '
                          'Máy ảo Android: http://10.0.2.2:8000/api',
                      helperMaxLines: 2,
                    ),
                    // Áp dụng ngay vào ApiService — trước đây giá trị này chỉ
                    // được ghi vào SharedPreferences và không ai đọc tới.
                    onChanged: (v) async {
                      await _api.setBaseUrl(v);
                      setState(() {
                        _apiUrl = v;
                        _connectionStatus = null;
                      });
                    },
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      OutlinedButton.icon(
                        onPressed: _checking ? null : _checkConnection,
                        icon: _checking
                            ? const SizedBox(
                                width: 14, height: 14,
                                child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.network_check, size: 18),
                        label: const Text('Kiểm tra kết nối'),
                      ),
                      const SizedBox(width: 12),
                      if (_connectionStatus != null)
                        Expanded(
                          child: Text(
                            _connectionStatus!,
                            style: TextStyle(
                              fontSize: 12,
                              color: _connectionStatus!.startsWith('Kết nối được')
                                  ? context.bb.successDeep
                                  : context.bb.danger,
                            ),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Icon(Icons.schedule_outlined, size: 16, color: Colors.grey[600]),
                      const SizedBox(width: 4),
                      Text(
                        'Hàng đợi offline: $_offlineQueueSize yêu cầu',
                        style: TextStyle(fontSize: 12, color: Colors.grey[600]),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 16),

          // Notifications
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.notifications_outlined, size: 20),
                      SizedBox(width: 8),
                      Text('Thông báo', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                    ],
                  ),
                  const SizedBox(height: 12),
                  SwitchListTile(
                    value: _pushNotifications,
                    onChanged: (v) async {
                      final prefs = await SharedPreferences.getInstance();
                      await prefs.setBool('push_notifications', v);
                      setState(() => _pushNotifications = v);
                    },
                    title: const Text('Thông báo đẩy (FCM)'),
                    subtitle: const Text('Nhận SOS khi có nhu cầu máu khẩn cấp'),
                  ),
                  SwitchListTile(
                    value: _sosAlerts,
                    onChanged: _pushNotifications ? (v) async {
                      final prefs = await SharedPreferences.getInstance();
                      await prefs.setBool('sos_alerts', v);
                      setState(() => _sosAlerts = v);
                    } : null,
                    title: const Text('SOS cấp cứu'),
                    subtitle: const Text('Leo thang 4 vòng: T+0/10/25/45 phút'),
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 16),

          // Privacy
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.shield_outlined, size: 20, color: context.bb.info),
                      SizedBox(width: 8),
                      Text('Quyền riêng tư', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                    ],
                  ),
                  const SizedBox(height: 12),
                  SwitchListTile(
                    value: _locationSharing,
                    onChanged: (v) async {
                      final prefs = await SharedPreferences.getInstance();
                      await prefs.setBool('location_sharing', v);
                      setState(() => _locationSharing = v);
                    },
                    title: const Text('Chia sẻ vị trí (ô lưới H3)'),
                    subtitle: const Text(
                      'Ô lưới H3 (~1 km) với TTL 4 giờ\nKhông lưu tọa độ GPS thô',
                      style: TextStyle(fontSize: 12),
                    ),
                    secondary: Icon(
                      _locationSharing ? Icons.location_on : Icons.location_off,
                      color: _locationSharing ? context.bb.info : context.bb.faint,
                    ),
                  ),
                  const Divider(),
                  ListTile(
                    leading: const Icon(Icons.grid_on, size: 20),
                    title: const Text('Độ phân giải H3'),
                    subtitle: Text(
                      'Resolution $_h3Resolution = ~${H3Config.resolution == 7 ? '1.2' : '2.0'} km/cell',
                      style: const TextStyle(fontSize: 12),
                    ),
                    trailing: const Text('7', style: TextStyle(fontWeight: FontWeight.w700)),
                  ),
                  const SizedBox(height: 4),
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: context.bb.dangerSoft,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Row(
                      children: [
                        Icon(Icons.warning_amber, size: 16, color: context.bb.danger),
                        SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'O⁻ chiếm ~0.1% dân số VN — hệ thống phạt nặng việc dùng O- cho người không thuộc nhóm này.',
                            style: TextStyle(fontSize: 11, color: context.bb.danger),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 16),

          // Donation interval rules
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.timer_outlined, size: 20),
                      SizedBox(width: 8),
                      Text('Khoảng cách hiến (Điều 6)', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                    ],
                  ),
                  const SizedBox(height: 12),
                  _intervalRow('Máu toàn phần / Hồng cầu', '12 tuần', false),
                  _intervalRow('Tiểu cầu / Huyết tương', '2 tuần', true),
                  _intervalRow('Bạch cầu hạt trung tính', '≤3 lần / 7 ngày', false),
                  const SizedBox(height: 8),
                  Text(
                    '⚠️ Phải lọc theo loại hiến gần nhất — không dùng một ngưỡng 12 tuần duy nhất.',
                    style: TextStyle(fontSize: 11, color: context.bb.danger),
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 16),

          // App info
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.info_outline, size: 20),
                      SizedBox(width: 8),
                      Text('Thông tin ứng dụng', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text('BLOODBLINK SOS $_appVersion'.trimRight(),
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(
                    'Điều phối máu liên viện — HCMC\n'
                    'H3 geocell · FEFO · 4-ring SOS\n'
                    'Tuân thủ TT 26/2013/TT-BYT',
                    style: TextStyle(fontSize: 12, color: context.bb.muted),
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: () async {
                        final box = await Hive.openBox('settings');
                        await box.put('is_logged_in', false);
                        if (context.mounted) {
                          Navigator.pushAndRemoveUntil(
                            context,
                            MaterialPageRoute(builder: (context) => const LoginScreen()),
                            (Route<dynamic> route) => false,
                          );
                        }
                      },
                      icon: Icon(Icons.logout, color: context.bb.danger),
                      label: Text('Đăng xuất', style: TextStyle(color: context.bb.danger)),
                      style: OutlinedButton.styleFrom(
                        side: BorderSide(color: context.bb.danger),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _intervalRow(String type, String interval, bool isWarning) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(child: Text(type, style: const TextStyle(fontSize: 13))),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(
              color: isWarning ? context.bb.dangerSoft : context.bb.successSoft,
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              interval,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: isWarning ? context.bb.danger : context.bb.success,
              ),
            ),
          ),
        ],
      ),
    );
  }
}