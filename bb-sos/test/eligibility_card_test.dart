import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:bb_sos/widgets/components.dart';
import 'package:bb_sos/models/donor_profile.dart';

void main() {
  group('EligibilityCard Widget Tests', () {
    testWidgets('Displays "Có thể hiến máu" when canDonate is true', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: EligibilityCard(canDonate: true),
          ),
        ),
      );

      expect(find.text('Có thể hiến máu'), findsOneWidget);
    });

    testWidgets('Displays remaining weeks when canDonate is false', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: EligibilityCard(
              canDonate: false,
              weeksLeft: 4,
              lastDonationType: DonationType.wholeBlood,
            ),
          ),
        ),
      );

      expect(find.textContaining('Còn 4 tuần'), findsOneWidget);
      expect(find.textContaining('Máu toàn phần'), findsOneWidget);
    });
    
    testWidgets('Displays "Chưa đủ điều kiện" when canDonate is false and no weeks left', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: EligibilityCard(
              canDonate: false,
            ),
          ),
        ),
      );

      expect(find.text('Chưa đủ điều kiện'), findsOneWidget);
    });
  });
}
