/// BB-SOS — Bộ màu ngữ nghĩa cho hai chủ đề.
///
/// Trước đây các màn hình cắm cứng mã màu (`Color(0xFF6B7280)` cho chữ mờ,
/// `Color(0xFFFEE2E2)` cho nền cảnh báo…). Cách đó chỉ đúng ở chủ đề sáng: trên
/// nền tối, chữ xám đậm cho tương phản dưới 3:1 — không đọc nổi trong ca cấp cứu.
///
/// `ColorScheme` của Material không có chỗ cho những vai trò riêng của ứng dụng
/// này (nền cảnh báo nhạt, màu "đủ điều kiện hiến"…), nên bọc thành một
/// ThemeExtension: đăng ký một lần cho mỗi chủ đề, màn hình chỉ gọi `context.bb`.
library;

import 'package:flutter/material.dart';

@immutable
class BBColors extends ThemeExtension<BBColors> {
  // Chữ, theo độ đậm giảm dần
  final Color strong;      // tiêu đề
  final Color body;        // nội dung
  final Color muted;       // chú thích
  final Color faint;       // nhãn phụ, biểu tượng mờ

  // Đường viền và nền phụ
  final Color border;
  final Color surfaceAlt;

  // Trạng thái — mỗi màu kèm một nền nhạt tương ứng
  final Color danger;
  final Color dangerSoft;
  final Color success;
  final Color successDeep;
  final Color successSoft;
  final Color info;
  final Color infoBright;
  final Color infoDeep;
  final Color infoSoft;
  final Color warning;
  final Color warningSoft;
  final Color purple;

  const BBColors({
    required this.strong,
    required this.body,
    required this.muted,
    required this.faint,
    required this.border,
    required this.surfaceAlt,
    required this.danger,
    required this.dangerSoft,
    required this.success,
    required this.successDeep,
    required this.successSoft,
    required this.info,
    required this.infoBright,
    required this.infoDeep,
    required this.infoSoft,
    required this.warning,
    required this.warningSoft,
    required this.purple,
  });

  /// Giữ nguyên bảng màu cũ để chủ đề sáng không đổi diện mạo.
  static const light = BBColors(
    strong: Color(0xFF111827),
    body: Color(0xFF4B5563),
    muted: Color(0xFF6B7280),
    faint: Color(0xFF9CA3AF),
    border: Color(0xFFE5E7EB),
    surfaceAlt: Color(0xFFF3F4F6),
    danger: Color(0xFFDC2626),
    dangerSoft: Color(0xFFFEE2E2),
    success: Color(0xFF16A34A),
    successDeep: Color(0xFF059669),
    successSoft: Color(0xFFF0FDF4),
    info: Color(0xFF2563EB),
    infoBright: Color(0xFF3B82F6),
    infoDeep: Color(0xFF1E40AF),
    infoSoft: Color(0xFFEFF6FF),
    warning: Color(0xFFF59E0B),
    warningSoft: Color(0xFFFFFBEB),
    purple: Color(0xFF7C3AED),
  );

  /// Chữ sáng lên, nền trạng thái tối lại — tương phản tối thiểu 4.5:1 trên
  /// nền `0xFF171C25` của thẻ ở chủ đề tối.
  static const dark = BBColors(
    strong: Color(0xFFE9ECF1),
    body: Color(0xFFC3CAD6),
    muted: Color(0xFFA4ADBD),
    faint: Color(0xFF8B94A3),
    border: Color(0xFF2A323F),
    surfaceAlt: Color(0xFF1D232E),
    danger: Color(0xFFEF5F76),
    dangerSoft: Color(0xFF3A1C24),
    success: Color(0xFF34D399),
    successDeep: Color(0xFF34D399),
    successSoft: Color(0xFF12312A),
    info: Color(0xFF7EA6FF),
    infoBright: Color(0xFF93B4FF),
    infoDeep: Color(0xFFB9CDFF),
    infoSoft: Color(0xFF1A2740),
    warning: Color(0xFFF0A742),
    warningSoft: Color(0xFF362A15),
    purple: Color(0xFFB191F5),
  );

  @override
  BBColors copyWith({
    Color? strong, Color? body, Color? muted, Color? faint,
    Color? border, Color? surfaceAlt,
    Color? danger, Color? dangerSoft,
    Color? success, Color? successDeep, Color? successSoft,
    Color? info, Color? infoBright, Color? infoDeep, Color? infoSoft,
    Color? warning, Color? warningSoft, Color? purple,
  }) {
    return BBColors(
      strong: strong ?? this.strong,
      body: body ?? this.body,
      muted: muted ?? this.muted,
      faint: faint ?? this.faint,
      border: border ?? this.border,
      surfaceAlt: surfaceAlt ?? this.surfaceAlt,
      danger: danger ?? this.danger,
      dangerSoft: dangerSoft ?? this.dangerSoft,
      success: success ?? this.success,
      successDeep: successDeep ?? this.successDeep,
      successSoft: successSoft ?? this.successSoft,
      info: info ?? this.info,
      infoBright: infoBright ?? this.infoBright,
      infoDeep: infoDeep ?? this.infoDeep,
      infoSoft: infoSoft ?? this.infoSoft,
      warning: warning ?? this.warning,
      warningSoft: warningSoft ?? this.warningSoft,
      purple: purple ?? this.purple,
    );
  }

  @override
  BBColors lerp(BBColors? other, double t) {
    if (other == null) return this;
    return BBColors(
      strong: Color.lerp(strong, other.strong, t)!,
      body: Color.lerp(body, other.body, t)!,
      muted: Color.lerp(muted, other.muted, t)!,
      faint: Color.lerp(faint, other.faint, t)!,
      border: Color.lerp(border, other.border, t)!,
      surfaceAlt: Color.lerp(surfaceAlt, other.surfaceAlt, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      dangerSoft: Color.lerp(dangerSoft, other.dangerSoft, t)!,
      success: Color.lerp(success, other.success, t)!,
      successDeep: Color.lerp(successDeep, other.successDeep, t)!,
      successSoft: Color.lerp(successSoft, other.successSoft, t)!,
      info: Color.lerp(info, other.info, t)!,
      infoBright: Color.lerp(infoBright, other.infoBright, t)!,
      infoDeep: Color.lerp(infoDeep, other.infoDeep, t)!,
      infoSoft: Color.lerp(infoSoft, other.infoSoft, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      warningSoft: Color.lerp(warningSoft, other.warningSoft, t)!,
      purple: Color.lerp(purple, other.purple, t)!,
    );
  }
}

extension BBColorsContext on BuildContext {
  /// Bộ màu của chủ đề đang dùng: `context.bb.muted`, `context.bb.dangerSoft`…
  BBColors get bb => Theme.of(this).extension<BBColors>() ?? BBColors.light;
}
