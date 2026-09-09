import 'package:flutter/material.dart';

import '../theme/bb_colors.dart';
import '../models/donor_profile.dart' show DonationType, SosRing;

/// BB-SOS — Blood Type Badge Widget
///
/// Displays ABO/Rh blood type with color coding:
///   O- = red (critical resource, ~0.1% VN population)
///   O+ = amber (universal RBC donor for Rh+)
///   AB- = purple (rare)
///   AB+ = blue (universal plasma donor)
///   Others = default

class BloodTypeBadge extends StatelessWidget {
  final String abo;
  final String rh;
  final double size;

  const BloodTypeBadge({
    super.key,
    required this.abo,
    required this.rh,
    this.size = 48,
  });

  @override
  Widget build(BuildContext context) {
    final color = _badgeColor(context);
    final label = '$abo${rh == '+' ? '⁺' : '⁻'}';

    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        shape: BoxShape.circle,
        border: Border.all(color: color, width: 2),
      ),
      child: Center(
        child: Text(
          label,
          style: TextStyle(
            color: color,
            fontWeight: FontWeight.w700,
            fontSize: size * 0.32,
          ),
        ),
      ),
    );
  }

  Color _badgeColor(BuildContext context) {
    // O- is the most critical — penalized in matching engine
    if (abo == 'O' && rh == '-') return context.bb.danger; // red
    // O+ is common but important
    if (abo == 'O' && rh == '+') return context.bb.warning; // amber
    // AB- is very rare
    if (abo == 'AB' && rh == '-') return context.bb.purple; // purple
    // AB+ is universal plasma donor
    if (abo == 'AB' && rh == '+') return context.bb.info; // blue
    // Others
    return context.bb.success; // green
  }
}

/// Eligibility status card — shows whether donor can donate now
class EligibilityCard extends StatelessWidget {
  final bool canDonate;
  final int? weeksLeft;
  final DonationType? lastDonationType;

  const EligibilityCard({
    super.key,
    required this.canDonate,
    this.weeksLeft,
    this.lastDonationType,
  });

  @override
  Widget build(BuildContext context) {
    if (canDonate) {
      return Row(
        children: [
          Container(
            width: 10, height: 10,
            decoration: BoxDecoration(
              color: context.bb.success,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            'Có thể hiến máu',
            style: TextStyle(
              color: context.bb.success,
              fontWeight: FontWeight.w600,
              fontSize: 14,
            ),
          ),
        ],
      );
    }

    final weeks = weeksLeft ?? 0;
    final typeLabel = lastDonationType?.label ?? '';

    return Row(
      children: [
        Container(
          width: 10, height: 10,
          decoration: BoxDecoration(
            color: context.bb.danger,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 8),
        Text(
          weeks > 0 ? 'Còn $weeks tuần ($typeLabel)' : 'Chưa đủ điều kiện',
          style: TextStyle(
            color: context.bb.danger,
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
        ),
      ],
    );
  }
}

/// Ring progress indicator for SOS escalation
class RingProgress extends StatelessWidget {
  final int activeRing;  // 0-3, or -1 for no active ring
  final double progress;  // 0.0-1.0 for current ring progress

  const RingProgress({
    super.key,
    required this.activeRing,
    this.progress = 0.0,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 200,
      height: 200,
      child: Stack(
        alignment: Alignment.center,
        children: [
          // Background rings
          ...List.generate(4, (i) {
            final radius = 40.0 + i * 22.0;
            final isActive = i <= activeRing;
            final colors = [
              context.bb.infoBright,  // Ring 0: blue
              context.bb.warning,  // Ring 1: amber
              context.bb.danger,  // Ring 2: red
              context.bb.purple,  // Ring 3: purple
            ];

            return SizedBox(
              width: radius * 2,
              height: radius * 2,
              child: CircularProgressIndicator(
                value: i == activeRing ? progress : (i < activeRing ? 1.0 : 0.0),
                strokeWidth: 4,
                backgroundColor: context.bb.border,
                valueColor: AlwaysStoppedAnimation(
                  isActive ? colors[i] : context.bb.faint,
                ),
              ),
            );
          }),

          // Center text
          if (activeRing >= 0)
            Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Vòng $activeRing',
                  style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                ),
                Text(
                  'T+${SosRing.rings[activeRing].triggerMinutes} phút',
                  style: TextStyle(fontSize: 12, color: context.bb.muted),
                ),
              ],
            ),
        ],
      ),
    );
  }
}