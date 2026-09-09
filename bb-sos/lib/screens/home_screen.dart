/// BB-SOS — Home Screen with SOS escalation visualization
///
/// The main screen shows:
///   - Donor profile status (blood type, eligibility)
///   - Active SOS events (if any)
///   - 4-ring escalation timeline
///   - Privacy architecture notes

import 'package:flutter/material.dart';

import '../theme/bb_colors.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:hive/hive.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../models/donor_profile.dart';
import '../services/api_service.dart';
import '../services/sos_inbox_service.dart';
import '../widgets/components.dart';
import 'donor_profile_screen.dart';
import 'nearby_facilities_screen.dart';
import 'sos_active_screen.dart';

final apiProvider = Provider<ApiService>((ref) => ApiService());

// Providers
final donorProfileProvider = FutureProvider<DonorProfile?>((ref) async {
  final box = await Hive.openBox<DonorProfile>('donor_profile');
  return box.isNotEmpty ? box.getAt(0) : null;
});

final isOnlineProvider = StreamProvider<bool>((ref) async* {
  final api = ref.watch(apiProvider);
  yield await api.isOnline();
  yield* Stream.periodic(const Duration(seconds: 30), (_) async {
    return await api.isOnline();
  }).asyncMap((event) => event);
});

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profileAsync = ref.watch(donorProfileProvider);
    final onlineAsync = ref.watch(isOnlineProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('BLOODBLINK SOS'),
        actions: [
          // Online/offline indicator
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Icon(
              onlineAsync.valueOrNull == true
                ? Icons.cloud_done_outlined
                : Icons.cloud_off_outlined,
              color: onlineAsync.valueOrNull == true
                ? context.bb.success
                : context.bb.faint,
              size: 20,
            ),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(donorProfileProvider);
          ref.invalidate(isOnlineProvider);
        },
        child: profileAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text('Lỗi: $e')),
          data: (profile) {
            if (profile == null) {
              return _buildNoProfile(context);
            }
            return _buildProfileHome(context, ref, profile);
          },
        ),
      ),
    );
  }

  /// Danh sách lời kêu gọi chưa trả lời, lấy từ hộp thư trên máy chủ.
  Widget _buildPendingCalls(BuildContext context) {
    return ValueListenableBuilder<List<SosInboxItem>>(
      valueListenable: SosInboxService.instance.pending,
      builder: (context, calls, _) {
        if (calls.isEmpty) return const SizedBox.shrink();

        return Column(
          children: calls.map((call) {
            final emergency = call.urgency == 'emergency';
            final color = emergency ? context.bb.danger : context.bb.warning;

            return Card(
              margin: const EdgeInsets.only(bottom: 12),
              color: color.withValues(alpha: 0.08),
              child: InkWell(
                onTap: () => Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => SosActiveScreen(call: call)),
                ),
                borderRadius: BorderRadius.circular(12),
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Row(
                    children: [
                      Icon(Icons.notifications_active, color: color, size: 28),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(call.title,
                                style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 14,
                                    color: color)),
                            const SizedBox(height: 2),
                            Text(call.body,
                                style: TextStyle(
                                    fontSize: 12, color: context.bb.body)),
                          ],
                        ),
                      ),
                      Icon(Icons.chevron_right, color: context.bb.faint),
                    ],
                  ),
                ),
              ),
            );
          }).toList(),
        );
      },
    );
  }

  Widget _buildNoProfile(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.bloodtype, size: 80, color: context.bb.danger).animate().scale(delay: 200.ms, duration: 600.ms, curve: Curves.easeOutBack),
            const SizedBox(height: 24),
            const Text(
              'Chào mừng đến BLOODBLINK SOS',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),
            Text(
              'Đăng ký hồ sơ người hiến máu để nhận thông báo SOS khi có nhu cầu cấp cứu.',
              style: TextStyle(fontSize: 14, color: context.bb.body),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            ElevatedButton.icon(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const DonorProfileScreen(isOnboarding: true)),
              ),
              icon: const Icon(Icons.person_add),
              label: const Text('Tạo hồ sơ người hiến'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildProfileHome(BuildContext context, WidgetRef ref, DonorProfile profile) {
    final donationHistory = Hive.box<DonationRecord>('donation_history');
    final records = donationHistory.values.toList();
    final canDonate = profile.canDonate(records);
    final weeksLeft = profile.weeksUntilNextDonation(records);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Lời kêu gọi đang chờ trả lời — thứ quan trọng nhất nên nằm trên cùng
        _buildPendingCalls(context),

        // Bệnh viện gần bạn — câu hỏi kế tiếp sau khi nhận lời luôn là "đi đâu".
        Card(
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            leading: Icon(Icons.local_hospital_outlined, color: context.bb.danger, size: 30),
            title: Text('Bệnh viện gần bạn',
                style: TextStyle(fontWeight: FontWeight.w600, color: context.bb.strong)),
            subtitle: Text('Xếp theo khoảng cách · chỉ đường bằng bản đồ trên máy',
                style: TextStyle(fontSize: 12.5, color: context.bb.muted)),
            trailing: Icon(Icons.chevron_right, color: context.bb.faint),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => const NearbyFacilitiesScreen(),
            )),
          ),
        ),

        const SizedBox(height: 16),

        // Impact / Gamification Card
        Card(
          color: context.bb.infoSoft, // Light blue background
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Icon(Icons.stars, color: context.bb.infoBright, size: 40).animate().rotate(duration: 2.seconds, curve: Curves.easeInOut).then().shake(),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Người hùng thầm lặng',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: context.bb.infoDeep),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        records.isEmpty 
                          ? 'Mạng lưới y tế đã sẵn sàng bảo vệ bạn.'
                          : 'Sự cống hiến của bạn đã đóng góp trực tiếp cứu sống ${records.length * 3} sinh mạng!',
                        style: TextStyle(fontSize: 13, color: context.bb.infoDeep),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ).animate().slideY(begin: 0.2, duration: 400.ms, curve: Curves.easeOut).fadeIn(),

        const SizedBox(height: 16),

        // Blood type and eligibility
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                BloodTypeBadge(abo: profile.abo, rh: profile.rh, size: 56).animate().scale(duration: 500.ms, curve: Curves.easeOutBack),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        profile.name.isNotEmpty ? profile.name : 'Người hiến máu',
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(height: 4),
                      EligibilityCard(
                        canDonate: canDonate,
                        weeksLeft: weeksLeft,
                        lastDonationType: records.isNotEmpty
                          ? records.reduce((a, b) => a.donatedAt.isAfter(b.donatedAt) ? a : b).type
                          : null,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ).animate().slideY(begin: 0.2, delay: 100.ms, duration: 400.ms, curve: Curves.easeOut).fadeIn(),

        const SizedBox(height: 16),

        // SOS ring visualization
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Leo thang huy động',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 16),
                ...SosRing.rings.map((ring) => _buildRingTile(context, ring)),
              ],
            ),
          ),
        ),

        const SizedBox(height: 16),

        // Privacy architecture note
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.shield, size: 18, color: context.bb.info),
                    SizedBox(width: 8),
                    Text('Kiến trúc quyền riêng tư', style: TextStyle(fontWeight: FontWeight.w600)),
                  ],
                ),
                SizedBox(height: 8),
                _PrivacyNote(
                  icon: Icons.location_on_outlined,
                  text: 'Ô lưới H3 (~1 km) thay vì tọa độ GPS — vị trí chỉ được lưu dưới dạng ô lưới có TTL 4 giờ',
                ),
                _PrivacyNote(
                  icon: Icons.block,
                  text: 'Không lưu bệnh án — chỉ có chỉ mục và mã yêu cầu',
                ),
                _PrivacyNote(
                  icon: Icons.timer_outlined,
                  text: 'Máy chủ phán quyết khoảng cách hiến: 12 tuần máu toàn phần, '
                      '2 tuần tiểu cầu (Điều 6) — app chỉ hiển thị',
                ),
              ],
            ),
          ),
        ),

        const SizedBox(height: 16),

        // Donation interval table
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Khoảng cách hiến máu (Điều 6 TT 26/2013)',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 12),
                _buildIntervalTable(context),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildRingTile(BuildContext context, SosRing ring) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: _hexToColor(ring.color).withOpacity(0.15),
              shape: BoxShape.circle,
            ),
            child: Center(
              child: Text(
                '${ring.ring}',
                style: TextStyle(
                  color: _hexToColor(ring.color),
                  fontWeight: FontWeight.w700,
                  fontSize: 16,
                ),
              ),
            ),
          ).animate(onPlay: (controller) => controller.repeat()).shimmer(duration: 1200.ms, color: _hexToColor(ring.color).withOpacity(0.5)).scale(begin: const Offset(1, 1), end: const Offset(1.1, 1.1), duration: 600.ms, curve: Curves.easeInOut).then().scale(begin: const Offset(1.1, 1.1), end: const Offset(1, 1), duration: 600.ms, curve: Curves.easeInOut),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(ring.label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                Text(
                  'T+${ring.triggerMinutes} phút · ${ring.radius}',
                  style: TextStyle(fontSize: 11, color: context.bb.muted),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildIntervalTable(BuildContext context) {
    return Table(
      columnWidths: const {0: FlexColumnWidth(2), 1: FlexColumnWidth(1), 2: FlexColumnWidth(1)},
      children: [
        TableRow(
          decoration: BoxDecoration(color: context.bb.surfaceAlt),
          children: [
            Padding(padding: EdgeInsets.all(8), child: Text('Loại hiến', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 12))),
            Padding(padding: EdgeInsets.all(8), child: Text('Khoảng cách', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 12))),
            Padding(padding: EdgeInsets.all(8), child: Text('Lọc', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 12))),
          ],
        ),
        ...DonationType.values.map((t) => TableRow(
          children: [
            Padding(padding: const EdgeInsets.all(8), child: Text(t.label, style: const TextStyle(fontSize: 12))),
            Padding(padding: const EdgeInsets.all(8), child: Text('${t.minWeeks} tuần', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
            Padding(
              padding: const EdgeInsets.all(8),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: t.minWeeks <= 2 ? context.bb.dangerSoft : context.bb.successSoft,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  t.minWeeks <= 2 ? 'Phân biệt' : 'Tự động',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: t.minWeeks <= 2 ? context.bb.danger : context.bb.success,
                  ),
                ),
              ),
            ),
          ],
        )),
      ],
    );
  }
}

class _PrivacyNote extends StatelessWidget {
  final IconData icon;
  final String text;

  const _PrivacyNote({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: context.bb.body),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text, style: TextStyle(fontSize: 13, color: context.bb.body)),
          ),
        ],
      ),
    );
  }
}

Color _hexToColor(String hex) {
  return Color(int.parse(hex.replaceFirst('#', 'FF'), radix: 16));
}