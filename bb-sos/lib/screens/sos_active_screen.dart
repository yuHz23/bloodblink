/// BB-SOS — Màn hình lời kêu gọi hiến máu.
///
/// P2: trước đây đây là UI chết — không màn nào điều hướng tới, và nút trả lời
/// chỉ hiện một dòng snackbar. Nay nó nhận lời kêu gọi thật từ hộp thư và gửi
/// phản hồi lên máy chủ.

import 'package:flutter/material.dart';

import '../theme/bb_colors.dart';
import 'nearby_facilities_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/donor_profile.dart';
import '../services/api_service.dart';
import '../services/location_service.dart';
import '../services/sos_inbox_service.dart';
import '../widgets/bb_gold_dragon_backdrop.dart';

class SosActiveScreen extends StatefulWidget {
  final SosInboxItem call;

  const SosActiveScreen({super.key, required this.call});

  @override
  State<SosActiveScreen> createState() => _SosActiveScreenState();
}

class _SosActiveScreenState extends State<SosActiveScreen> {
  final _api = ApiService();
  bool _sending = false;
  String? _error;

  SosInboxItem get call => widget.call;

  String get _componentLabel {
    switch (call.componentCode) {
      case 'RBC': return 'Khối hồng cầu (RBC)';
      case 'PLT': return 'Khối tiểu cầu (PLT)';
      case 'FFP': return 'Huyết tương (FFP)';
      case 'CRYO': return 'Kết tủa lạnh (CRYO)';
      default: return 'Máu toàn phần (WB)';
    }
  }

  String get _urgencyLabel {
    switch (call.urgency) {
      case 'mock_test': return 'KIỂM THỬ — không phải ca cấp cứu';
      case 'emergency': return 'Cấp cứu — cần trong 2 giờ';
      case 'urgent': return 'Cấp bách — cần trong 6 giờ';
      default: return 'Luân chuyển';
    }
  }

  Color get _urgencyColor {
    switch (call.urgency) {
      case 'mock_test': return context.bb.info;
      case 'emergency': return context.bb.danger;
      case 'urgent': return context.bb.warning;
      default: return context.bb.info;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('SOS — Yêu cầu máu'),
        flexibleSpace: const BBGoldDragonBackdrop(),
        backgroundColor: _urgencyColor,
        foregroundColor: Colors.white,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Tóm tắt lời kêu gọi
          Card(
            color: _urgencyColor.withValues(alpha: 0.08),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.warning_amber_rounded, color: _urgencyColor),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _urgencyLabel,
                          style: TextStyle(
                            fontWeight: FontWeight.w700,
                            color: _urgencyColor,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Text(
                    call.urgency == 'mock_test'
                        ? 'Kiểm tra thông báo'
                        : 'Cần ${call.bloodType ?? 'nhóm phù hợp'}',
                    style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 4),
                  Text(_componentLabel,
                      style: TextStyle(fontSize: 14, color: context.bb.body)),
                  if (call.facilityName != null) ...[
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Icon(Icons.local_hospital_outlined,
                            size: 16, color: context.bb.muted),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(call.facilityName!,
                              style: TextStyle(fontSize: 13, color: context.bb.body)),
                        ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 10),
                  Text(
                    'Đã có ${call.acceptCount}/${call.targetCount} người nhận lời · '
                    'Bạn được gọi ở ${SosRing.rings[call.ring.clamp(0, 3)].label.toLowerCase()}',
                    style: TextStyle(fontSize: 12, color: context.bb.muted),
                  ),
                ],
              ),
            ),
          ),

          if (call.urgency == 'mock_test') ...[
            const SizedBox(height: 12),
            Card(
              color: context.bb.infoSoft,
              child: const ListTile(
                leading: Icon(Icons.info_outline),
                title: Text('Mô phỏng riêng cho thiết bị này'),
                subtitle: Text(
                  'Không phải ca hiến máu thật. Không gửi phản hồi hay điều hướng tới bệnh viện.',
                ),
              ),
            ),
          ],

          const SizedBox(height: 16),

          if (_error != null)
            Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: context.bb.dangerSoft,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(_error!,
                  style: TextStyle(fontSize: 13, color: context.bb.danger)),
            ),

          if (call.urgency != 'mock_test') ...[
            // Chỉ đường tới nơi đang cần — câu hỏi đầu tiên sau khi đọc lời kêu
            // gọi luôn là "chỗ đó ở đâu, mình đi bao lâu".
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => NearbyFacilitiesScreen(
                    highlightFacilityId: call.facilityId,
                  ),
                )),
                icon: const Icon(Icons.directions_outlined, size: 18),
                label: const Text('Xem đường tới bệnh viện'),
              ),
            ),
            const SizedBox(height: 12),

            // Nút trả lời
            Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: _sending ? null : () => _respond('accepted'),
                  icon: const Icon(Icons.check_circle_outline),
                  label: Text(_sending ? 'Đang gửi…' : 'Tôi có thể hiến'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: context.bb.successDeep,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _sending ? null : () => _respond('declined'),
                  icon: const Icon(Icons.cancel_outlined),
                  label: const Text('Không thể'),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                ),
              ),
            ],
            ),
          ],

          const SizedBox(height: 20),

          // Các vòng leo thang
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Tiến trình huy động',
                      style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
                  const SizedBox(height: 10),
                  ...SosRing.rings.map((r) => _buildRingStep(r, r.ring <= call.ring)),
                ],
              ),
            ),
          ),

          const SizedBox(height: 16),

          Card(
            child: Padding(
              padding: EdgeInsets.all(12),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.shield_outlined, size: 16, color: context.bb.info),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Mặc định app chỉ gửi ô lưới H3 (~1,2 km). Tọa độ chính xác chỉ được '
                      'gửi cho cơ sở phát SOS nếu bạn đồng ý chia sẻ trong lời kêu gọi này; '
                      'bạn vẫn có thể nhận lời mà không chia sẻ vị trí.',
                      style: TextStyle(fontSize: 12, color: context.bb.body),
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

  Widget _buildRingStep(SosRing ring, bool reached) {
    final color = reached ? _hexToColor(ring.color) : context.bb.border;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.15),
              shape: BoxShape.circle,
              border: Border.all(color: color, width: 2),
            ),
            child: Center(
              child: Text(
                '${ring.ring}',
                style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 14),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(ring.label,
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                      color: reached ? context.bb.strong : context.bb.faint,
                    )),
                Text(
                  'T+${ring.triggerMinutes} phút · Bán kính ${ring.radius}',
                  style: TextStyle(fontSize: 11, color: context.bb.muted),
                ),
              ],
            ),
          ),
          if (reached)
            Icon(Icons.check_circle, size: 18, color: context.bb.successDeep),
        ],
      ),
    );
  }

  /// Hỏi cách liên hệ TRƯỚC KHI gửi lời nhận.
  ///
  /// Máy chủ không có sẵn số điện thoại của ai — đây là lần duy nhất trong cả
  /// hệ thống người hiến tự quyết định có lộ danh tính hay không, và chỉ lộ cho
  /// đúng cơ sở đang cần máu.
  Future<Map<String, String>?> _askContact() async {
    final phone = TextEditingController();
    final note = TextEditingController();

    final shared = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cơ sở y tế liên hệ bạn thế nào?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: phone,
              keyboardType: TextInputType.phone,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Số điện thoại (tuỳ chọn)',
                hintText: '09xx xxx xxx',
                prefixIcon: Icon(Icons.phone_outlined),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: note,
              decoration: const InputDecoration(
                labelText: 'Ghi chú (tuỳ chọn)',
                hintText: 'Có mặt sau 30 phút',
                prefixIcon: Icon(Icons.notes_outlined),
              ),
            ),
            const SizedBox(height: 14),
            Text(
              'Chỉ cơ sở phát lời kêu gọi này đọc được, và chỉ sau khi bạn nhận lời. '
              'Bỏ trống vẫn nhận lời được — cơ sở sẽ liên hệ qua ứng dụng.',
              style: TextStyle(fontSize: 12, color: context.bb.muted),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Huỷ'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Nhận lời'),
          ),
        ],
      ),
    );

    if (shared != true) return null;
    return {'phone': phone.text, 'note': note.text};
  }

  Future<bool?> _askLocationSharing() {
    return showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Chia sẻ vị trí với bệnh viện?'),
        content: const Text(
          'Nếu đồng ý, vị trí hiện tại sẽ được gửi riêng cho cơ sở phát lời kêu gọi '
          'để họ điều phối. Bạn vẫn có thể nhận lời hiến máu mà không chia sẻ vị trí.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Huỷ'),
          ),
          OutlinedButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Nhận lời, không chia sẻ'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(ctx, true),
            icon: const Icon(Icons.location_on_outlined),
            label: const Text('Chia sẻ vị trí'),
          ),
        ],
      ),
    );
  }

  Future<void> _respond(String outcome) async {
    Map<String, String>? contact;
    bool? shareLocation;
    double? latitude;
    double? longitude;
    if (outcome == 'accepted') {
      shareLocation = await _askLocationSharing();
      if (shareLocation == null) return;

      if (shareLocation) {
        try {
          final position = await LocationService.instance.currentPosition();
          latitude = position.latitude;
          longitude = position.longitude;
        } on LocationException catch (e) {
          if (!mounted) return;
          setState(() => _error = '${e.message}. Bạn có thể thử lại hoặc nhận lời mà không chia sẻ vị trí.');
          return;
        } on Exception {
          if (!mounted) return;
          setState(() => _error = 'Không lấy được vị trí. Bạn có thể thử lại hoặc nhận lời mà không chia sẻ vị trí.');
          return;
        }
      }

      contact = await _askContact();
      if (contact == null) return;          // người dùng bấm Huỷ
    }

    if (!mounted) return;
    final prefs = await SharedPreferences.getInstance();
    final donorId = prefs.getString('donor_id');
    if (donorId == null) {
      setState(() => _error = 'Chưa có hồ sơ người hiến trên máy này');
      return;
    }

    setState(() {
      _sending = true;
      _error = null;
    });

    try {
      await _api.respondToSos(
        eventId: call.eventId,
        donorId: donorId,
        response: outcome,
        contactPhone: contact?['phone'],
        contactNote: contact?['note'],
        shareLocation: shareLocation,
        latitude: latitude,
        longitude: longitude,
      );
      await SosInboxService.instance.markAnswered(call.notificationId);

      if (!mounted) return;
      Navigator.pop(context);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(outcome == 'accepted'
              ? 'Đã ghi nhận sẵn sàng hiến máu. Cơ sở y tế sẽ liên hệ.'
              : 'Đã ghi nhận không thể hiến lúc này.'),
        ),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _sending = false;
        _error = e.message;
      });
    }
  }

  Color _hexToColor(String hex) {
    return Color(int.parse(hex.replaceFirst('#', 'FF'), radix: 16));
  }
}
