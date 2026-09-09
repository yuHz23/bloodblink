# BB-SOS — BLOODBLINK Donor Escalation App

Flutter mobile app (iOS + Android) for blood donor SOS escalation.

## Architecture

### 4-Ring SOS Escalation (per planning doc)
| Ring | Time | Radius | Target |
|------|------|--------|--------|
| 0 | T+0 min | ~1 km | Same blood type, push notification |
| 1 | T+10 min | ~3 km | Compatible blood types |
| 2 | T+25 min | ~5 km | All compatible + registered donors |
| 3 | T+45 min | City-wide | Hospital-wide alert, emergency protocols |

### Privacy Architecture
- **H3 geocell (~1 km)** with TTL 4 hours — NOT raw GPS coordinates
- **No patient medical data** stored — only request codes and indexes
- **Donation interval filtering on-device** per Article 6 TT 26/2013/TT-BYT:
  - WB/RBC = 12 weeks
  - PLT/plasma = 2 weeks
  - Granulocyte ≤ 3 times / 7 days

### Offline-First
- Hive local DB for donor profile and donation history
- Queue pending responses when offline
- Sync when connectivity returns

## Project Structure

```
lib/
├── main.dart                    # App entry, Hive init, Riverpod provider
├── models/
│   ├── donor_profile.dart       # DonorProfile, DonationRecord, H3Config, SosRing
│   └── donor_profile.g.dart     # Hive adapters
├── services/
│   └── api_service.dart         # Offline-first API client with queue
├── screens/
│   ├── home_screen.dart          # Main screen with eligibility + ring visualization
│   ├── sos_active_screen.dart   # Active SOS event with escalation timeline
│   ├── donor_profile_screen.dart # Blood type, consent, interval tracking
│   ├── history_screen.dart       # Donation history with Article 6 intervals
│   └── settings_screen.dart     # API URL, privacy controls, H3 config
└── widgets/
    └── components.dart          # BloodTypeBadge, EligibilityCard, RingProgress

test/
└── donor_profile_test.dart      # Donation interval + H3 privacy tests
```

## Key Design Decisions

1. **Donation interval must filter by last donation type** — PLT donors need only 2 weeks, not 12 weeks. A single 12-week threshold would incorrectly block PLT/plasma donors.

2. **O⁻ penalty** — O⁻ is ~0.1% of Vietnamese population. The system must heavily penalize using O⁻ for non-O⁻ patients.

3. **RhD constraint for women 18-45** — Never downgrade RhD+ → RhD- for women of childbearing age (risk of HDFN in future pregnancies).

4. **Button label must be "Đề xuất"** (propose), NOT "Điều chuyển" (transfer) — the system proposes, medical staff decides.

5. **Two temperature threshold modes** per Article 20 TT 26/2013/TT-BYT: storage vs transport (BB-Box differentiates these).

## Getting Started

```bash
# Install dependencies
flutter pub get

# Run code generation for Hive adapters
flutter pub run build_runner build

# Run on emulator
flutter run

# Run tests
flutter test
```

## BB-Core Backend

The app connects to BB-Core at `http://10.0.2.2:8000/api` (Android emulator → host localhost).
Change this in Settings or via `--dart-define=API_URL=...`.