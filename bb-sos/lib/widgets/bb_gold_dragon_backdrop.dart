import 'package:flutter/material.dart';

/// Subtle Theme 1 ornament used behind page titles.
class BBGoldDragonBackdrop extends StatelessWidget {
  const BBGoldDragonBackdrop({super.key});

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Align(
        alignment: Alignment.centerRight,
        child: ExcludeSemantics(
          child: Opacity(
            opacity: 0.14,
            child: Image.asset(
              'assets/images/gold-dragon-ornament.png',
              width: 220,
              height: kToolbarHeight,
              fit: BoxFit.contain,
              alignment: Alignment.centerRight,
              errorBuilder: (_, __, ___) => const SizedBox.shrink(),
            ),
          ),
        ),
      ),
    );
  }
}
