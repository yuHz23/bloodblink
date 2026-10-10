import 'package:flutter_test/flutter_test.dart';
import 'package:bb_sos/services/api_service.dart';

void main() {
  group('ApiService.resolveSavedBaseUrl', () {
    test('migrates the retired Tailscale hostname to the current laptop', () {
      expect(
        ApiService.resolveSavedBaseUrl(
          'http://desktop-kijp57s.tail85e1ba.ts.net:8000/api',
        ),
        'http://laptop-rrqk96mj.tail85e1ba.ts.net:8000/api',
      );
    });

    test('migrates the retired Tailscale IP to the current laptop', () {
      expect(
        ApiService.resolveSavedBaseUrl('http://100.106.118.107:8000/api'),
        'http://laptop-rrqk96mj.tail85e1ba.ts.net:8000/api',
      );
    });

    test('uses the configured default when no URL was saved', () {
      expect(ApiService.resolveSavedBaseUrl(null), kDefaultApiUrl);
      expect(ApiService.resolveSavedBaseUrl('  '), kDefaultApiUrl);
    });

    test('preserves a custom server URL', () {
      const customUrl = 'https://api.example.test/bloodblink';
      expect(ApiService.resolveSavedBaseUrl(customUrl), customUrl);
    });
  });
}
