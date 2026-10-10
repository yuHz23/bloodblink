import 'package:flutter/material.dart';

import '../theme/bb_colors.dart';
import 'package:hive/hive.dart';
import 'package:bb_sos/screens/donor_profile_screen.dart';
import 'package:bb_sos/main.dart'; // For MainNavigation
import 'package:bb_sos/models/donor_profile.dart';
import '../widgets/bb_gold_dragon_backdrop.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phoneController = TextEditingController();
  final _otpController = TextEditingController();
  bool _otpSent = false;
  bool _isLoading = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const SizedBox(
                height: kToolbarHeight,
                child: BBGoldDragonBackdrop(),
              ),
              Icon(Icons.water_drop, size: 80, color: context.bb.danger),
              const SizedBox(height: 16),
              Text(
                'BLOODBLINK SOS',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: context.bb.danger),
              ),
              const SizedBox(height: 8),
              const Text(
                'Nền tảng điều phối máu khẩn cấp',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 16, color: Colors.grey),
              ),
              const SizedBox(height: 48),

              if (!_otpSent) ...[
                TextFormField(
                  controller: _phoneController,
                  keyboardType: TextInputType.phone,
                  decoration: const InputDecoration(
                    labelText: 'Số điện thoại',
                    prefixIcon: Icon(Icons.phone),
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: _isLoading ? null : _sendOtp,
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  child: _isLoading 
                    ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                    : const Text('Gửi mã OTP', style: TextStyle(fontSize: 16)),
                ),
              ] else ...[
                Text(
                  'Mã OTP đã được gửi đến ${_phoneController.text}',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: _otpController,
                  keyboardType: TextInputType.number,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 24, letterSpacing: 8),
                  maxLength: 6,
                  decoration: const InputDecoration(
                    hintText: '000000',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: _isLoading ? null : _verifyOtp,
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  child: _isLoading 
                    ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                    : const Text('Xác nhận đăng nhập', style: TextStyle(fontSize: 16)),
                ),
                TextButton(
                  onPressed: () => setState(() => _otpSent = false),
                  child: const Text('Dùng số điện thoại khác'),
                )
              ],
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _sendOtp() async {
    if (_phoneController.text.length < 9) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vui lòng nhập số điện thoại hợp lệ')));
      return;
    }
    
    setState(() => _isLoading = true);
    // Simulate network delay
    await Future.delayed(const Duration(seconds: 1));
    setState(() {
      _isLoading = false;
      _otpSent = true;
      _otpController.text = '123456'; // Auto-fill for demo
    });

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Chế độ Demo: Mã OTP "123456" đã được tự động điền.'),
          backgroundColor: context.bb.success, // Green
          duration: Duration(seconds: 3),
        )
      );
    }
  }

  Future<void> _verifyOtp() async {
    if (_otpController.text.length < 4) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vui lòng nhập mã OTP hợp lệ (mặc định: 123456)')));
      return;
    }

    try {
      setState(() => _isLoading = true);
      // Simulate network delay
      await Future.delayed(const Duration(seconds: 1));
      
      // Save auth state
      final box = Hive.box('settings'); // Already opened in main.dart
      await box.put('is_logged_in', true);
      await box.put('phone_number', _phoneController.text);
      
      setState(() => _isLoading = false);

      if (mounted) {
        // Check if user has profile, if not go to profile setup
        // Need to import DonorProfile
        final profileBox = Hive.box<DonorProfile>('donor_profile'); // Already opened in main.dart
        if (profileBox.isEmpty) {
          Navigator.pushReplacement(
            context, 
            MaterialPageRoute(builder: (context) => const DonorProfileScreen(isOnboarding: true))
          );
        } else {
          Navigator.pushReplacement(
            context, 
            MaterialPageRoute(builder: (context) => const MainNavigation())
          );
        }
      }
    } catch (e) {
      setState(() => _isLoading = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Lỗi: $e')));
      }
    }
  }
}
