/// BB-SOS — Bệnh viện gần bạn.
///
/// Người hiến nhận lời rồi thì câu hỏi kế tiếp luôn là "đi đâu, xa không". Màn
/// này trả lời điều đó: danh sách cơ sở trong mạng lưới, xếp theo khoảng cách,
/// kèm nút mở chỉ đường bằng ứng dụng bản đồ có sẵn trên máy.
///
/// Ràng buộc giữ nguyên: khoảng cách tính TRÊN MÁY từ toạ độ bệnh viện tải về —
/// vị trí thô của người hiến không gửi đi đâu cả.

library;

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/nearby_facility_service.dart';
import '../theme/bb_colors.dart';

class NearbyFacilitiesScreen extends StatefulWidget {
  /// Khi mở từ một lời kêu gọi, truyền mã cơ sở phát để làm nổi nó lên.
  final String? highlightFacilityId;

  const NearbyFacilitiesScreen({super.key, this.highlightFacilityId});

  @override
  State<NearbyFacilitiesScreen> createState() => _NearbyFacilitiesScreenState();
}

class _NearbyFacilitiesScreenState extends State<NearbyFacilitiesScreen> {
  List<NearbyFacility>? _rows;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool refresh = false}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final rows = await NearbyFacilityService.instance.nearest(refresh: refresh);
      if (mounted) setState(() { _rows = rows; _loading = false; });
    } catch (e) {
      if (mounted) setState(() { _error = e.toString(); _loading = false; });
    }
  }

  /// Mở ứng dụng bản đồ có sẵn để chỉ đường.
  ///
  /// Dùng lược đồ `geo:` trước — Android tự hỏi người dùng chọn app nào, không
  /// ép phải cài Google Maps. Máy nào không xử lý được `geo:` thì rơi về liên
  /// kết web.
  Future<void> _openDirections(NearbyFacility row) async {
    final f = row.facility;
    final label = Uri.encodeComponent(f.name);
    final geo = Uri.parse('geo:${f.lat},${f.lon}?q=${f.lat},${f.lon}($label)');
    final web = Uri.parse(
        'https://www.google.com/maps/dir/?api=1&destination=${f.lat},${f.lon}');

    if (await canLaunchUrl(geo)) {
      await launchUrl(geo, mode: LaunchMode.externalApplication);
      return;
    }
    if (await canLaunchUrl(web)) {
      await launchUrl(web, mode: LaunchMode.externalApplication);
      return;
    }
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Không mở được ứng dụng bản đồ trên máy này')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final bb = context.bb;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Bệnh viện gần bạn'),
        actions: [
          IconButton(
            tooltip: 'Tải lại',
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : () => _load(refresh: true),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _load(refresh: true),
        child: _buildBody(bb),
      ),
    );
  }

  Widget _buildBody(BBColors bb) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const SizedBox(height: 60),
          Icon(Icons.cloud_off, size: 48, color: bb.faint),
          const SizedBox(height: 12),
          Text('Không tải được danh sách cơ sở',
              textAlign: TextAlign.center,
              style: TextStyle(fontWeight: FontWeight.w600, color: bb.strong)),
          const SizedBox(height: 6),
          Text(_error!, textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: bb.muted)),
          const SizedBox(height: 18),
          Center(
            child: FilledButton.icon(
              onPressed: () => _load(refresh: true),
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('Thử lại'),
            ),
          ),
        ],
      );
    }

    final rows = _rows ?? const <NearbyFacility>[];
    final hasDistance = rows.any((r) => r.distanceMeters != null);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
      children: [
        // Nói thẳng nguồn của con số, đừng để người xem đoán.
        Container(
          padding: const EdgeInsets.all(13),
          decoration: BoxDecoration(
            color: bb.infoSoft,
            borderRadius: BorderRadius.circular(11),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.shield_outlined, size: 19, color: bb.info),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  hasDistance
                      ? 'Khoảng cách tính ngay trên máy bạn từ toạ độ bệnh viện — '
                        'vị trí của bạn KHÔNG được gửi lên máy chủ. Đây là đường '
                        'chim bay, đường đi thật sẽ dài hơn.'
                      : 'Chưa có quyền vị trí nên chưa tính được khoảng cách. '
                        'Danh sách vẫn đầy đủ; bật chia sẻ vị trí ở màn Hồ sơ để '
                        'thấy bệnh viện gần nhất.',
                  style: TextStyle(fontSize: 12.5, height: 1.45, color: bb.body),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),

        if (rows.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 40),
            child: Center(
              child: Text('Chưa có cơ sở y tế nào trong mạng lưới',
                  style: TextStyle(color: bb.muted)),
            ),
          ),

        for (final row in rows) _facilityCard(row, bb),
      ],
    );
  }

  Widget _facilityCard(NearbyFacility row, BBColors bb) {
    final f = row.facility;
    final highlighted = f.id == widget.highlightFacilityId;

    return Card(
      margin: const EdgeInsets.only(bottom: 11),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: highlighted
            ? BorderSide(color: bb.danger, width: 1.6)
            : BorderSide(color: bb.border),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (highlighted)
              Padding(
                padding: const EdgeInsets.only(bottom: 7),
                child: Row(children: [
                  Icon(Icons.campaign, size: 15, color: bb.danger),
                  const SizedBox(width: 5),
                  Text('Nơi đang cần bạn',
                      style: TextStyle(
                          fontSize: 12, fontWeight: FontWeight.w700, color: bb.danger)),
                ]),
              ),

            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(f.name,
                          style: TextStyle(
                              fontSize: 15.5,
                              fontWeight: FontWeight.w600,
                              color: bb.strong)),
                      const SizedBox(height: 3),
                      Text('Tuyến ${f.tier}',
                          style: TextStyle(fontSize: 12.5, color: bb.muted)),
                    ],
                  ),
                ),
                if (row.distanceMeters != null)
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(row.distanceLabel,
                          style: TextStyle(
                              fontSize: 17,
                              fontWeight: FontWeight.w700,
                              color: bb.info)),
                      Text('xe máy ${row.rideTimeLabel}',
                          style: TextStyle(fontSize: 11.5, color: bb.faint)),
                    ],
                  ),
              ],
            ),

            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () => _openDirections(row),
                icon: const Icon(Icons.directions_outlined, size: 18),
                label: const Text('Chỉ đường'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
