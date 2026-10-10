/// BB-SOS — Settings Screen
///
/// App settings: API URL, notification preferences, location sharing,
/// offline queue status.

import 'package:flutter/material.dart';

import '../theme/bb_colors.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:hive/hive.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../services/api_service.dart';
import '../services/sos_inbox_service.dart';
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
  bool _systemNotificationsEnabled = true;
  bool _testingNotification = false;
  bool _locationSharing = false;
  int _offlineQueueSize = 0;

  @override
  void initState() {
    super.initState();
    _loadSettings();
    _loadVersion();
    _loadNotificationPermission();
  }

  Future<void> _loadNotificationPermission() async {
    final enabled = await SosInboxService.instance.notificationsEnabled();
    if (mounted) setState(() => _systemNotificationsEnabled = enabled);
  }

  Future<void> _sendTestNotification() async {
    setState(() => _testingNotification = true);
    final enabled = await SosInboxService.instance.showTestNotification();
    await _loadNotificationPermission();
    if (!mounted) return;
    setState(() => _testingNotification = false);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(enabled
            ? 'Đã gửi thông báo thử. Kiểm tra thanh thông báo của điện thoại.'
            : 'Android chưa cấp quyền thông báo cho BLOODBLINK SOS.'),
      ),
    );
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
                      if (v) await SosInboxService.instance.refresh();
                    },
                    title: const Text('Thông báo SOS'),
                    subtitle: const Text('Cho phép ứng dụng báo lời kêu gọi hiến máu'),
                  ),
                  SwitchListTile(
                    value: _sosAlerts,
                    onChanged: _pushNotifications ? (v) async {
                      final prefs = await SharedPreferences.getInstance();
                      await prefs.setBool('sos_alerts', v);
                      setState(() => _sosAlerts = v);
                      if (v) await SosInboxService.instance.refresh();
                    } : null,
                    title: const Text('SOS cấp cứu'),
                    subtitle: const Text('Leo thang 4 vòng: T+0/10/25/45 phút'),
                  ),
                  ListTile(
                    leading: Icon(
                      _systemNotificationsEnabled
                          ? Icons.notifications_active_outlined
                          : Icons.notifications_off_outlined,
                      color: _systemNotificationsEnabled
                          ? context.bb.success
                          : context.bb.danger,
                    ),
                    title: const Text('Quyền thông báo Android'),
                    subtitle: Text(_systemNotificationsEnabled
                        ? 'Đang bật trên thiết bị'
                        : 'Đang tắt — Android sẽ không hiển thị SOS'),
                    trailing: _systemNotificationsEnabled
                        ? const Icon(Icons.check_circle_outline)
                        : TextButton(
                            onPressed: _loadNotificationPermission,
                            child: const Text('Kiểm tra'),
                          ),
                  ),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: _testingNotification ? null : _sendTestNotification,
                      icon: _testingNotification
                          ? const SizedBox.square(
                              dimension: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.notifications_active_outlined),
                      label: const Text('Gửi thông báo thử'),
                    ),
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
}
