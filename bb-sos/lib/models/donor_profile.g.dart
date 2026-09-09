/// BB-SOS — Hive adapters for DonorProfile and DonationRecord
///
/// Manual adapters — run `flutter pub run build_runner build` for full codegen.

import 'package:hive/hive.dart';

import 'donor_profile.dart';

// Manual adapter for DonorProfile (type ID 0)
class DonorProfileAdapter extends TypeAdapter<DonorProfile> {
  @override
  final int typeId = 0;

  @override
  DonorProfile read(BinaryReader reader) {
    final numOfFields = reader.readByte();
    final fields = <int, dynamic>{
      for (var i = 0; i < numOfFields; i++) reader.readByte(): reader.read(),
    };
    return DonorProfile(
      id: fields[0] as String,
      name: fields[1] as String,
      abo: fields[2] as String,
      rh: fields[3] as String,
      birthYear: fields[4] as int,
      sex: fields[5] as String?,
      weightKg: fields[6] as double?,
      h3Cell: fields[7] as String?,
      h3CellTtl: fields[8] as DateTime?,
      facilityId: fields[9] as String?,
      isRegistered: fields[10] as bool? ?? false,
      createdAt: fields[11] as DateTime?,
    );
  }

  @override
  void write(BinaryWriter writer, DonorProfile obj) {
    writer
      ..writeByte(12)
      ..writeByte(0)..write(obj.id)
      ..writeByte(1)..write(obj.name)
      ..writeByte(2)..write(obj.abo)
      ..writeByte(3)..write(obj.rh)
      ..writeByte(4)..write(obj.birthYear)
      ..writeByte(5)..write(obj.sex)
      ..writeByte(6)..write(obj.weightKg)
      ..writeByte(7)..write(obj.h3Cell)
      ..writeByte(8)..write(obj.h3CellTtl)
      ..writeByte(9)..write(obj.facilityId)
      ..writeByte(10)..write(obj.isRegistered)
      ..writeByte(11)..write(obj.createdAt);
  }
}

// Manual adapter for DonationRecord (type ID 1)
class DonationRecordAdapter extends TypeAdapter<DonationRecord> {
  @override
  final int typeId = 1;

  @override
  DonationRecord read(BinaryReader reader) {
    final numOfFields = reader.readByte();
    final fields = <int, dynamic>{
      for (var i = 0; i < numOfFields; i++) reader.readByte(): reader.read(),
    };
    return DonationRecord(
      id: fields[0] as String,
      type: DonationType.values[fields[1] as int],
      donatedAt: fields[2] as DateTime,
      facilityId: fields[3] as String?,
      notes: fields[4] as String?,
    );
  }

  @override
  void write(BinaryWriter writer, DonationRecord obj) {
    writer
      ..writeByte(5)
      ..writeByte(0)..write(obj.id)
      ..writeByte(1)..write(obj.type.index)
      ..writeByte(2)..write(obj.donatedAt)
      ..writeByte(3)..write(obj.facilityId)
      ..writeByte(4)..write(obj.notes);
  }
}