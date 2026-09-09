# ProGuard rules for BLOODBLINK SOS
# Keep Flutter engine
-keep class io.flutter.** { *; }
-keep class io.flutter.plugins.** { *; }

# Keep Firebase
-keep class com.google.firebase.** { *; }
-keepattributes *Annotation*

# Keep H3
-keep class com.uber.h3core.** { *; }

# Keep Riverpod generated code
-keep class ** extends flutter_riverpod.** { *; }

# Keep Hive adapters
-keep class ** extends com.hivedb.** { *; }

# General Android rules
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
-dontwarn com.google.android.play.core.**
