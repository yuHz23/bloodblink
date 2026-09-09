/// BB-SOS — BLOODBLINK Donor Escalation App
///
/// Architecture:
///   - 4-ring SOS escalation (T+0/10/25/45 min)
///   - H3 geocell ~1 km with TTL for privacy (NO raw coordinates stored)
///   - Offline-first with Hive local DB
///   - Donation interval filter per Article 6 TT 26/2013/TT-BYT
///   - Two architectural constraints:
///     1. NO patient medical data stored — only request codes
///     2. H3 geocell with TTL, NOT raw GPS coordinates

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hive_flutter/hive_flutter.dart';
import 'package:google_fonts/google_fonts.dart';

import 'screens/home_screen.dart';
import 'screens/sos_active_screen.dart';
import 'screens/donor_profile_screen.dart';
import 'screens/history_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/login_screen.dart';
import 'models/donor_profile.dart';
import 'models/donor_profile.g.dart';
import 'services/api_service.dart';
import 'theme/bb_colors.dart';
import 'services/sos_inbox_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize Hive for offline-first storage
  await Hive.initFlutter();

  // Register adapters
  Hive.registerAdapter(DonorProfileAdapter());
  Hive.registerAdapter(DonationRecordAdapter());

  // Open boxes
  await Hive.openBox<DonorProfile>('donor_profile');
  await Hive.openBox<DonationRecord>('donation_history');
  await Hive.openBox('settings');
  await Hive.openBox('sos_events');
  await Hive.openBox('pending_responses');

  // Nạp địa chỉ máy chủ người dùng đã lưu TRƯỚC khi dựng giao diện — nếu không,
  // mọi lời gọi đầu tiên vẫn trỏ về máy chủ mặc định lúc build.
  final api = ApiService();
  await api.init();

  // Có mạng thì đẩy nốt những gì đã xếp hàng lúc ngoại tuyến.
  if (await api.isOnline()) {
    unawaited(api.processOfflineQueue());
  }

  // Theo dõi hộp thư lời kêu gọi. Tự bỏ qua nếu máy chưa có hồ sơ người hiến.
  unawaited(SosInboxService.instance.start());

  final settingsBox = Hive.box('settings');
  final isLoggedIn = settingsBox.get('is_logged_in', defaultValue: false);

  runApp(ProviderScope(child: BBSOSApp(isLoggedIn: isLoggedIn)));
}

class BBSOSApp extends StatelessWidget {
  final bool isLoggedIn;
  
  const BBSOSApp({super.key, required this.isLoggedIn});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BLOODBLINK SOS',
      debugShowCheckedModeBanner: false,
      theme: _buildTheme(brightness: Brightness.light),
      darkTheme: _buildTheme(brightness: Brightness.dark),
      // Theo cài đặt hệ thống: người trực đêm bật chế độ tối cho cả máy thì app
      // cũng tối theo. Màu trong các màn hình lấy từ `context.bb` (xem
      // theme/bb_colors.dart) nên đổi chủ đề là đổi theo, không còn chữ xám
      // đậm nằm trên nền tối như trước.
      themeMode: ThemeMode.system,
      home: isLoggedIn ? const MainNavigation() : const LoginScreen(),
    );
  }

  /// Bảng màu dùng chung cho cả hai chủ đề.
  ///
  /// Đỏ máu là màu thương hiệu nhưng KHÔNG dùng làm màu nền lớn: giao diện y tế
  /// đọc dưới áp lực thì nền phải trung tính, đỏ để dành cho thứ thật sự khẩn.
  static const _bbRed = Color(0xFFC62828);
  static const _bbRedDark = Color(0xFFEF5F76);
  static const _bbBlue = Color(0xFF1D4ED8);
  static const _bbBlueDark = Color(0xFF7EA6FF);

  ThemeData _buildTheme({required Brightness brightness}) {
    final dark = brightness == Brightness.dark;

    final scheme = ColorScheme.fromSeed(
      seedColor: _bbRed,
      brightness: brightness,
    ).copyWith(
      primary: dark ? _bbRedDark : _bbRed,
      secondary: dark ? _bbBlueDark : _bbBlue,
      surface: dark ? const Color(0xFF171C25) : Colors.white,
      onPrimary: dark ? const Color(0xFF2A0B10) : Colors.white,
    );

    final background = dark ? const Color(0xFF0E1116) : const Color(0xFFF4F5F7);
    final outline = dark ? const Color(0xFF2A323F) : const Color(0xFFE3E6EA);

    // Be Vietnam Pro dựng riêng cho tiếng Việt — dấu không bị chồng lên chữ hoa
    // như Inter. google_fonts tải phông lúc chạy rồi lưu lại; lần chạy đầu mà
    // không có mạng thì rơi về phông hệ thống, giao diện vẫn đọc được.
    final base = ThemeData(useMaterial3: true, brightness: brightness);
    final text = GoogleFonts.beVietnamProTextTheme(base.textTheme).apply(
      bodyColor: scheme.onSurface,
      displayColor: scheme.onSurface,
    );

    return base.copyWith(
      colorScheme: scheme,
      extensions: [dark ? BBColors.dark : BBColors.light],
      scaffoldBackgroundColor: background,
      textTheme: text.copyWith(
        headlineMedium: text.headlineMedium?.copyWith(
            fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: -0.5),
        titleLarge: text.titleLarge?.copyWith(fontSize: 20, fontWeight: FontWeight.w600),
        labelLarge: text.labelLarge?.copyWith(fontWeight: FontWeight.w600),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0.5,
        centerTitle: true,
        titleTextStyle: text.titleMedium?.copyWith(
            fontWeight: FontWeight.w700, color: scheme.onSurface),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: scheme.surface,
        surfaceTintColor: Colors.transparent,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: BorderSide(color: outline),
        ),
      ),
      dividerTheme: DividerThemeData(color: outline, space: 1, thickness: 1),
      listTileTheme: const ListTileThemeData(
        contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: scheme.primary,
          foregroundColor: scheme.onPrimary,
          elevation: 0,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 15),
          textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: scheme.onSurface,
          side: BorderSide(color: outline),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 15),
          textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: dark ? const Color(0xFF1D232E) : Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: outline),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: outline),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: scheme.secondary, width: 1.6),
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        indicatorColor: scheme.primary.withValues(alpha: dark ? 0.24 : 0.14),
        elevation: 0,
        height: 66,
        labelTextStyle: WidgetStatePropertyAll(
          text.labelSmall?.copyWith(fontWeight: FontWeight.w600),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      dialogTheme: DialogThemeData(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
    );
  }
}

class MainNavigation extends StatefulWidget {
  const MainNavigation({super.key});

  @override
  State<MainNavigation> createState() => _MainNavigationState();
}

class _MainNavigationState extends State<MainNavigation> {
  int _currentIndex = 0;

  final List<Widget> _screens = const [
    HomeScreen(),
    DonorProfileScreen(),
    HistoryScreen(),
    SettingsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _screens[_currentIndex],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) => setState(() => _currentIndex = index),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home),
            label: 'Trang chủ',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outlined),
            selectedIcon: Icon(Icons.person),
            label: 'Hồ sơ',
          ),
          NavigationDestination(
            icon: Icon(Icons.history_outlined),
            selectedIcon: Icon(Icons.history),
            label: 'Lịch sử',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: 'Cài đặt',
          ),
        ],
      ),
    );
  }
}