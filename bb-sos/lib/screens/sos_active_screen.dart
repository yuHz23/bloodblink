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
import '../services/sos_inbox_service.dart';

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
  String? _rewardRole;
  String? _rewardStatus;
  int? _rewardAmountVnd;

  SosInboxItem get call => widget.call;

  @override
  void initState() {
    super.initState();
    _rewardRole = call.rewardRole;
    _rewardStatus = call.rewardStatus;
    _rewardAmountVnd = call.rewardAmountVnd;
  }

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
      case 'emergency': return 'Cấp cứu — cần trong 2 giờ';
      case 'urgent': return 'Cấp bách — cần trong 6 giờ';
      default: return 'Luân chuyển';
    }
  }

  Color get _urgencyColor {
    switch (call.urgency) {
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
                    'Cần ${call.bloodType ?? 'nhóm phù hợp'}',
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

          if (_rewardRole != null) ...[
            const SizedBox(height: 14),
            Card(
              color: context.bb.info.withValues(alpha: 0.08),
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(call.title, style: const TextStyle(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 6),
                    Text(_rewardMessage(), style: TextStyle(fontSize: 13, color: context.bb.body)),
                    if (_rewardRole == 'backup' && _rewardStatus == 'awaiting_choice') ...[
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: FilledButton(
                              onPressed: _sending ? null : () => _chooseBackup('continue'),
                              child: const Text('Tiếp tục dự bị'),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: OutlinedButton(
                              onPressed: _sending ? null : () => _chooseBackup('decline'),
                              child: const Text('Xin dừng'),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ],
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
          if (_rewardRole == null) Row(
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
                      'Vị trí của bạn chỉ được gửi dưới dạng ô lưới H3 (~1,2 km) có TTL 4 giờ. '
                      'Cơ sở y tế chỉ thấy mã người hiến, không thấy họ tên hay số điện thoại '
                      'cho tới khi bạn nhận lời.',
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

  Future<void> _respond(String outcome) async {
    Map<String, String>? contact;
    if (outcome == 'accepted') {
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
      );
      SosInboxService.instance.markAnswered(call.notificationId);

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

  String _rewardMessage() {
    if (_rewardStatus == 'awaiting_choice') return call.body;
    if (_rewardStatus == 'awaiting_donation') {
      final amount = _rewardRole == 'primary' ? '100.000đ' : '80.000đ';
      return 'Đã ghi nhận bạn trong danh sách ${_rewardRole == 'primary' ? 'người chính' : 'dự bị'}. '
          'Cơ sở y tế sẽ đánh giá điều kiện hiến và xác nhận kết quả. Phương án quà $amount chỉ là mô phỏng.';
    }
    if (_rewardStatus == 'compensation_proposed') {
      return 'Cảm ơn bạn đã phản hồi. Phương án bù phiền 30.000đ đã được ghi nhận ở chế độ mô phỏng; chưa phát quà thật.';
    }
    if (_rewardStatus == 'mock_ready') {
      return 'Cơ sở đã xác nhận kết quả hiến. Phương án quà ${_rewardAmountVnd ?? 0}đ đã ghi nhận ở chế độ mô phỏng; chưa phát voucher.';
    }
    if (_rewardStatus == 'not_completed') {
      return 'Cơ sở chưa ghi nhận hoàn tất hiến trong đợt SOS này.';
    }
    return call.body;
  }

  Future<void> _chooseBackup(String choice) async {
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
      final result = await _api.chooseSosBackup(
        eventId: call.eventId,
        donorId: donorId,
        choice: choice,
      );
      if (!mounted) return;
      setState(() {
        _rewardStatus = result['status'] as String?;
        _rewardAmountVnd = result['proposed_amount_vnd'] as int?;
        _sending = false;
      });
      SosInboxService.instance.markAnswered(call.notificationId);
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
