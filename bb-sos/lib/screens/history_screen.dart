/// BB-SOS — History Screen
///
/// Shows donation history with interval tracking per Article 6.

import 'package:flutter/material.dart';

import '../theme/bb_colors.dart';
import 'package:hive/hive.dart';
import 'package:uuid/uuid.dart';

import '../models/donor_profile.dart';
import '../widgets/components.dart';

class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Lịch sử hiến máu')),
      body: FutureBuilder<List<DonationRecord>>(
        future: _loadHistory(),
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }

          final records = snapshot.data ?? [];

          if (records.isEmpty) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(32),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.history, size: 64, color: context.bb.faint),
                    const SizedBox(height: 16),
                    const Text(
                      'Chưa có lịch sử hiến máu',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Thêm lần hiến để hệ thống tự động lọc khoảng cách theo Điều 6 TT 26/2013.',
                      style: TextStyle(fontSize: 13, color: context.bb.muted),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 16),
                    ElevatedButton.icon(
                      onPressed: () => _addDonationDialog(context),
                      icon: const Icon(Icons.add),
                      label: const Text('Thêm lần hiến'),
                    ),
                  ],
                ),
              ),
            );
          }

          // Sort by date descending
          records.sort((a, b) => b.donatedAt.compareTo(a.donatedAt));

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // Summary card
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      Icon(Icons.volunteer_activism, size: 32, color: context.bb.success),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '${records.length} lần hiến',
                              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                            ),
                            Text(
                              'Lần gần nhất: ${_formatDate(records.first.donatedAt)}',
                              style: TextStyle(fontSize: 13, color: context.bb.muted),
                            ),
                          ],
                        ),
                      ),
                      ElevatedButton.icon(
                        onPressed: () => _addDonationDialog(context),
                        icon: const Icon(Icons.add, size: 18),
                        label: const Text('Thêm'),
                      ),
                    ],
                  ),
                ),
              ),

              const SizedBox(height: 16),

              // Donation records
              ...records.map((r) => _buildDonationCard(context, r)),

              const SizedBox(height: 16),

              // Interval rules
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.info_outline, size: 16, color: context.bb.info),
                          SizedBox(width: 8),
                          Text('Khoảng cách hiến (Điều 6 TT 26/2013)', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                        ],
                      ),
                      const SizedBox(height: 8),
                      _buildIntervalRow(context, 'Máu toàn phần / Hồng cầu', '12 tuần', false),
                      _buildIntervalRow(context, 'Tiểu cầu / Huyết tương', '2 tuần', true),
                      _buildIntervalRow(context, 'Bạch cầu hạt trung tính', '≤3 lần / 7 ngày', false),
                    ],
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildDonationCard(BuildContext context, DonationRecord record) {
    final canDonate = record.type.canDonateAfter(record.donatedAt);
    final elapsed = DateTime.now().difference(record.donatedAt);
    final elapsedWeeks = elapsed.inDays ~/ 7;

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            CircleAvatar(
              backgroundColor: context.bb.dangerSoft,
              child: Icon(
                record.type == DonationType.platelet || record.type == DonationType.plasma 
                  ? Icons.water_drop 
                  : Icons.bloodtype, 
                color: context.bb.danger,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    record.type.label,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  Text(
                    _formatDate(record.donatedAt),
                    style: TextStyle(fontSize: 12, color: context.bb.muted),
                  ),
                  if (record.facilityId != null)
                    Text(
                      record.facilityId!.replaceAll('fac-', ''),
                      style: TextStyle(fontSize: 11, color: context.bb.faint),
                    ),
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: canDonate ? context.bb.successSoft : context.bb.dangerSoft,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    canDonate ? 'Có thể hiến' : '$elapsedWeeks/${record.type.minWeeks} tuần',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: canDonate ? context.bb.success : context.bb.danger,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildIntervalRow(BuildContext context, String type, String interval, bool isWarning) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Expanded(child: Text(type, style: const TextStyle(fontSize: 12))),
          Text(interval, style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            fontFamily: 'monospace',
            color: isWarning ? context.bb.danger : context.bb.success,
          )),
        ],
      ),
    );
  }

  Future<List<DonationRecord>> _loadHistory() async {
    final box = await Hive.openBox<DonationRecord>('donation_history');
    return box.values.toList();
  }

  String _formatDate(DateTime date) {
    return '${date.day.toString().padLeft(2, '0')}/${date.month.toString().padLeft(2, '0')}/${date.year}';
  }

  void _addDonationDialog(BuildContext context) {
    DonationType selectedType = DonationType.wholeBlood;
    DateTime selectedDate = DateTime.now();

    showDialog(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('Thêm lần hiến máu'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<DonationType>(
                value: selectedType,
                decoration: const InputDecoration(labelText: 'Loại hiến'),
                items: DonationType.values.map((t) =>
                  DropdownMenuItem(value: t, child: Text('${t.label} (${t.minWeeks} tuần)')),
                ).toList(),
                onChanged: (v) => setState(() => selectedType = v!),
              ),
              const SizedBox(height: 16),
              Text('Ngày hiến: ${_formatDate(selectedDate)}'),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Hủy'),
            ),
            ElevatedButton(
              onPressed: () async {
                final record = DonationRecord(
                  id: const Uuid().v4(),
                  type: selectedType,
                  donatedAt: selectedDate,
                );
                final box = await Hive.openBox<DonationRecord>('donation_history');
                await box.add(record);
                if (context.mounted) Navigator.pop(context);
              },
              child: const Text('Thêm'),
            ),
          ],
        ),
      ),
    );
  }
}