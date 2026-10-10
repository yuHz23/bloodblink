/// BB-SOS — Donor Profile Screen
///
/// Registration and profile management for blood donors.
/// Key features:
///   - Blood type selection (ABO/Rh)
///   - H3 geocell consent (NOT raw coordinates)
///   - Donation interval tracking per Article 6
///   - Privacy-first: only H3 cell + TTL sent to server
///
/// P0: màn này giờ ĐỌC LẠI hồ sơ đã lưu (trước đây luôn hiện giá trị mặc định)
/// và ĐẨY LÊN MÁY CHỦ sau khi lưu. Không có bước đẩy này thì bảng `donor` bên
/// bb-core rỗng và không cơ sở nào tìm ra người cùng nhóm máu.

import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/bb_colors.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hive/hive.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../models/donor_profile.dart';
import '../services/api_service.dart';
import '../services/location_service.dart';
import '../services/sos_inbox_service.dart';
import '../widgets/components.dart';
import '../widgets/bb_gold_dragon_backdrop.dart';
import '../main.dart'; // For MainNavigation

class DonorProfileScreen extends ConsumerStatefulWidget {
  final bool isOnboarding;
  const DonorProfileScreen({super.key, this.isOnboarding = false});

  @override
  ConsumerState<DonorProfileScreen> createState() => _DonorProfileScreenState();
}

class _DonorProfileScreenState extends ConsumerState<DonorProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  final _api = ApiService();

  String? _profileId;
  String _name = '';
  String _abo = 'O';
  String _rh = '+';
  int _birthYear = 2000;
  String? _sex;
  double? _weightKg;
  String? _facilityId;
  bool _locationConsent = false;

  // Trạng thái đồng bộ với bb-core
  bool _syncing = false;
  String? _syncMessage;
  bool _syncOk = false;
  bool _serverVerified = false;
  String? _h3Cell;
  DateTime? _h3CellTtl;

  late bool _isEditing;

  @override
  void initState() {
    super.initState();
    _isEditing = widget.isOnboarding;
    _loadProfile();
  }

  Future<void> _loadProfile() async {
    final box = await Hive.openBox<DonorProfile>('donor_profile');
    final prefs = await SharedPreferences.getInstance();
    if (box.isEmpty) {
      setState(() => _locationConsent = prefs.getBool('location_sharing') ?? false);
      return;
    }

    final p = box.values.first;
    setState(() {
      _profileId = p.id;
      _name = p.name;
      _abo = p.abo;
      _rh = p.rh;
      _birthYear = p.birthYear;
      _sex = p.sex;
      _weightKg = p.weightKg;
      _facilityId = p.facilityId;
      _h3Cell = p.h3Cell;
      _h3CellTtl = p.h3CellTtl;
      _locationConsent = prefs.getBool('location_sharing') ?? (p.h3Cell != null);
      _serverVerified = prefs.getBool('donor_verified') ?? false;
      final syncedAt = prefs.getString('donor_synced_at');
      if (syncedAt != null) {
        _syncOk = true;
        _syncMessage = 'Đã đồng bộ lúc ${_formatTime(DateTime.parse(syncedAt))}';
      }
    });
  }

  String _formatTime(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')} ${t.day}/${t.month}';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Hồ sơ'),
        flexibleSpace: const BBGoldDragonBackdrop(),
        actions: [
          if (!_isEditing)
            IconButton(
              icon: const Icon(Icons.edit),
              onPressed: () => setState(() => _isEditing = true),
            ),
        ],
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Blood type badge
            Center(
              child: BloodTypeBadge(abo: _abo, rh: _rh, size: 72),
            ),
            const SizedBox(height: 24),

            // Name
            TextFormField(
              initialValue: _name,
              decoration: const InputDecoration(
                labelText: 'Họ và tên',
                hintText: 'Nguyễn Văn A',
                prefixIcon: Icon(Icons.person_outline),
                helperText: 'Chỉ lưu trên máy này — không gửi lên máy chủ',
              ),
              enabled: _isEditing,
              validator: (v) => v?.trim().isEmpty == true ? 'Vui lòng nhập họ tên' : null,
              onSaved: (v) => _name = v?.trim() ?? '',
            ),
            const SizedBox(height: 16),

            // ABO group
            DropdownButtonFormField<String>(
              value: _abo,
              decoration: const InputDecoration(
                labelText: 'Nhóm máu ABO',
                prefixIcon: Icon(Icons.bloodtype_outlined),
              ),
              items: const ['O', 'A', 'B', 'AB'].map((g) =>
                DropdownMenuItem(value: g, child: Text('Nhóm $g')),
              ).toList(),
              onChanged: _isEditing ? (v) => setState(() => _abo = v!) : null,
            ),
            const SizedBox(height: 16),

            // RhD
            DropdownButtonFormField<String>(
              value: _rh,
              decoration: const InputDecoration(
                labelText: 'RhD',
                prefixIcon: Icon(Icons.water_drop_outlined),
              ),
              items: [
                DropdownMenuItem(value: '+', child: Text('RhD⁺ (dương tính)')),
                DropdownMenuItem(value: '-', child: Text('RhD⁻ (âm tính — hiếm ở Việt Nam, ~0.1%)')),
              ],
              onChanged: _isEditing ? (v) => setState(() => _rh = v!) : null,
            ),
            const SizedBox(height: 16),

            // Birth year
            DropdownButtonFormField<int>(
              value: _birthYear,
              decoration: const InputDecoration(
                labelText: 'Năm sinh',
                prefixIcon: Icon(Icons.calendar_today_outlined),
              ),
              items: List.generate(60, (i) => 1965 + i).map((y) =>
                DropdownMenuItem(value: y, child: Text('$y (${DateTime.now().year - y} tuổi)')),
              ).toList(),
              onChanged: _isEditing ? (v) => setState(() => _birthYear = v!) : null,
            ),
            const SizedBox(height: 16),

            // Sex (needed for RhD constraint — women 18-45)
            DropdownButtonFormField<String>(
              value: _sex,
              decoration: const InputDecoration(
                labelText: 'Giới tính',
                prefixIcon: Icon(Icons.wc_outlined),
              ),
              items: const [
                DropdownMenuItem(value: 'M', child: Text('Nam')),
                DropdownMenuItem(value: 'F', child: Text('Nữ')),
              ],
              onChanged: _isEditing ? (v) => setState(() => _sex = v) : null,
            ),
            const SizedBox(height: 16),

            // Weight
            if (_isEditing)
              TextFormField(
                initialValue: _weightKg?.toStringAsFixed(0),
                decoration: const InputDecoration(
                  labelText: 'Cân nặng (kg)',
                  hintText: '55',
                  prefixIcon: Icon(Icons.monitor_weight_outlined),
                ),
                keyboardType: TextInputType.number,
                validator: (v) {
                  if (v == null || v.isEmpty) return 'Vui lòng nhập cân nặng';
                  final weight = double.tryParse(v);
                  if (weight == null) return 'Cân nặng không hợp lệ';
                  if (_sex == 'F' && weight < 42) return 'Nữ cần tối thiểu 42kg (TT 26/2013)';
                  if (_sex == 'M' && weight < 45) return 'Nam cần tối thiểu 45kg (TT 26/2013)';
                  return null;
                },
                onSaved: (v) => _weightKg = v != null ? double.tryParse(v) : null,
              )
            else if (_weightKg != null)
              ListTile(
                leading: const Icon(Icons.monitor_weight_outlined),
                title: Text('Cân nặng: ${_weightKg}kg'),
                subtitle: Text(_weightKg! >= 45 ? 'Đủ điều kiện hiến máu cơ bản' : 'Cần lưu ý chuẩn cân nặng'),
              ),
            const SizedBox(height: 16),

            // Location consent
            Card(
              color: context.bb.infoSoft,
              child: SwitchListTile(
                value: _locationConsent,
                onChanged: _isEditing ? _onConsentChanged : null,
                title: const Text('Cho phép chia sẻ vị trí'),
                subtitle: const Text(
                  'Ô lưới H3 (~1 km) có TTL 4 giờ — KHÔNG lưu tọa độ GPS thô',
                  style: TextStyle(fontSize: 12),
                ),
                secondary: Icon(
                  _locationConsent ? Icons.location_on : Icons.location_off,
                  color: _locationConsent ? context.bb.info : context.bb.faint,
                ),
              ),
            ),

            // RhD constraint warning for women
            if (_sex == 'F' && _rh == '-' && _birthYear >= DateTime.now().year - 45 && _birthYear <= DateTime.now().year - 18)
              Container(
                margin: const EdgeInsets.only(top: 12),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: context.bb.dangerSoft,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    Icon(Icons.warning_amber, color: context.bb.danger, size: 20),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Ràng buộc chuyên môn: Không hạ chuẩn RhD cho phụ nữ tuổi sinh đẻ (18–45) — rủi ro bệnh tan máu ở thai nhi.',
                        style: TextStyle(fontSize: 13, color: context.bb.danger),
                      ),
                    ),
                  ],
                ),
              ),

            const SizedBox(height: 16),

            _buildSyncCard(),

            const SizedBox(height: 24),

            // Save button
            if (_isEditing)
              ElevatedButton(
                onPressed: _syncing ? null : _saveProfile,
                child: Text(_syncing ? 'Đang lưu…' : 'Lưu hồ sơ'),
              ),

            const SizedBox(height: 16),

            // Privacy note
            Card(
              child: Padding(
                padding: EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(Icons.shield_outlined, size: 16, color: context.bb.info),
                        SizedBox(width: 8),
                        Text('Quyền riêng tư', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                      ],
                    ),
                    SizedBox(height: 6),
                    Text(
                      '• Vị trí chỉ lưu dưới dạng ô lưới H3 (~1 km) có thời hạn sống 4 giờ\n'
                      '• Không lưu tọa độ GPS thô trên máy chủ\n'
                      '• Họ tên chỉ nằm trên máy này — máy chủ chỉ biết mã người hiến\n'
                      '• Không lưu bệnh án — chỉ có chỉ mục và mã yêu cầu\n'
                      '• Khoảng cách hiến do máy chủ phán quyết: 12 tuần máu toàn phần, 2 tuần tiểu cầu',
                      style: TextStyle(fontSize: 12, color: context.bb.body),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Thẻ trạng thái đồng bộ — cho biết hồ sơ đã tới được máy chủ hay chưa.
  Widget _buildSyncCard() {
    final Color color = _syncing
        ? context.bb.muted
        : (_syncOk ? context.bb.successDeep : context.bb.danger);
    final IconData icon = _syncing
        ? Icons.sync
        : (_syncOk ? Icons.cloud_done_outlined : Icons.cloud_off_outlined);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 18, color: color),
                const SizedBox(width: 8),
                const Text('Trạng thái trên máy chủ',
                    style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                const Spacer(),
                if (!_syncing && _profileId != null)
                  TextButton(
                    onPressed: _syncNow,
                    child: const Text('Đồng bộ lại'),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              _syncMessage ?? 'Chưa gửi lên máy chủ — chưa cơ sở nào tìm thấy bạn',
              style: TextStyle(fontSize: 12, color: color),
            ),
            if (_syncOk) ...[
              const SizedBox(height: 4),
              Text(
                _serverVerified
                    ? 'Đã được cơ sở y tế xác minh ✓'
                    : 'Chờ cơ sở y tế xác minh — chưa hiện trong tìm kiếm mặc định',
                style: TextStyle(fontSize: 12, color: context.bb.muted),
              ),
            ],
            if (_h3Cell != null) ...[
              const SizedBox(height: 4),
              Text(
                'Ô lưới: $_h3Cell'
                '${_h3CellTtl != null ? ' · hết hạn ${_formatTime(_h3CellTtl!)}' : ''}',
                style: TextStyle(fontSize: 11, color: context.bb.muted),
              ),
            ],
            const SizedBox(height: 4),
            Text('Máy chủ: ${_api.baseUrl}',
                style: TextStyle(fontSize: 11, color: context.bb.faint)),
          ],
        ),
      ),
    );
  }

  Future<void> _onConsentChanged(bool value) async {
    setState(() => _locationConsent = value);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('location_sharing', value);

    if (!value) {
      // Rút lại đồng ý: xoá ô lưới cả trên máy lẫn trên máy chủ, không đợi TTL.
      setState(() {
        _h3Cell = null;
        _h3CellTtl = null;
      });

      // Phải xoá trong HỒ SƠ nữa, không chỉ trong state của màn hình.
      //
      // `SosInboxService._ensureSession` đăng ký lại kèm `profile.h3Cell`, nên
      // nếu chỉ xoá ở state thì lần làm mới phiên kế tiếp đẩy đúng ô lưới vừa bị
      // rút lên máy chủ, kèm TTL 4 giờ mới. Người dùng tắt chia sẻ vị trí mà máy
      // chủ vẫn có — im lặng.
      final box = await Hive.openBox<DonorProfile>('donor_profile');
      if (box.isNotEmpty) {
        final profile = box.values.first;
        profile.h3Cell = null;
        profile.h3CellTtl = null;
        await profile.save();
      }

      if (_profileId != null) {
        try {
          await _api.revokeGeocell(_profileId!);
        } on ApiException {
          // Ngoại tuyến — ô lưới vẫn tự hết hạn sau TTL 4 giờ.
        }
      }
    }
  }

  Future<void> _saveProfile() async {
    if (!_formKey.currentState!.validate()) return;
    _formKey.currentState!.save();

    final box = await Hive.openBox<DonorProfile>('donor_profile');
    final existing = box.isNotEmpty ? box.values.first : null;

    final profile = DonorProfile(
      // Giữ nguyên id cũ: máy chủ upsert theo id, đổi id là tạo người hiến mới.
      id: existing?.id ?? _profileId ?? const Uuid().v4(),
      name: _name,
      abo: _abo,
      rh: _rh,
      birthYear: _birthYear,
      sex: _sex,
      weightKg: _weightKg,
      h3Cell: _h3Cell,
      h3CellTtl: _h3CellTtl,
      facilityId: _facilityId,
      isRegistered: true,
      createdAt: existing?.createdAt,
    );

    await box.clear();
    await box.add(profile);
    _profileId = profile.id;

    await _syncNow();

    if (!mounted) return;
    if (widget.isOnboarding) {
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (context) => const MainNavigation()),
      );
    } else {
      setState(() => _isEditing = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_syncOk
            ? 'Đã lưu và đồng bộ hồ sơ ✓'
            : 'Đã lưu cục bộ — ${_syncMessage ?? 'chưa gửi được lên máy chủ'}')),
      );
    }
  }

  /// Lấy ô lưới (nếu được phép) rồi đẩy hồ sơ lên bb-core.
  Future<void> _syncNow() async {
    if (_profileId == null) return;
    setState(() {
      _syncing = true;
      _syncMessage = 'Đang gửi lên máy chủ…';
    });

    // 1) Ô lưới H3 — chỉ khi người dùng đồng ý chia sẻ vị trí.
    String? cell = _h3Cell;
    if (_locationConsent) {
      try {
        final geocell = await LocationService.instance.currentGeocell();
        cell = geocell.h3Cell;
        _h3Cell = geocell.h3Cell;
        _h3CellTtl = geocell.ttl;
      } on LocationException catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Không lấy được vị trí: $e')),
          );
        }
      } catch (e) {
        // Không chặn việc đăng ký hồ sơ chỉ vì GPS trục trặc.
      }
    }

    // 2) Đẩy hồ sơ.
    try {
      final result = await _api.registerDonor(
        donorId: _profileId!,
        abo: _abo,
        rh: _rh,
        birthYear: _birthYear,
        sex: _sex,
        weightKg: _weightKg,
        h3Cell: cell,
        geocellTtlHours: H3Config.cellTtl.inHours,
      );

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('donor_synced_at', DateTime.now().toIso8601String());
      await prefs.setBool('donor_verified', result.verified);
      await prefs.setString('donor_id', result.id);

      // Có hồ sơ rồi thì bắt đầu nhận lời kêu gọi.
      unawaited(SosInboxService.instance.start());

      // Ghi ô lưới máy chủ đã nhận vào hồ sơ cục bộ.
      final box = await Hive.openBox<DonorProfile>('donor_profile');
      if (box.isNotEmpty) {
        final p = box.values.first;
        p.h3Cell = result.geocellH3;
        p.h3CellTtl = result.geocellTtl;
        await p.save();
      }

      if (!mounted) return;
      setState(() {
        _syncing = false;
        _syncOk = true;
        _serverVerified = result.verified;
        _h3Cell = result.geocellH3;
        _h3CellTtl = result.geocellTtl;
        _syncMessage = 'Đã đồng bộ — mã người hiến ${result.id.substring(0, 8)}…';
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _syncing = false;
        _syncOk = false;
        _syncMessage = e.message;
      });
    }
  }
}
