import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

class DeviceIdService {
  static const String _deviceIdKey = 'jarvis_device_id';

  /// Retrieves the unique device ID from persistent storage.
  /// If one doesn't exist, it generates a new UUID, saves it, and returns it.
  static Future<String> getOrCreateDeviceId() async {
    final prefs = await SharedPreferences.getInstance();
    String? deviceId = prefs.getString(_deviceIdKey);

    if (deviceId == null) {
      // Generate a new UUIDv4 for this specific phone installation
      const uuid = Uuid();
      deviceId = uuid.v4();
      await prefs.setString(_deviceIdKey, deviceId);
    }

    return deviceId;
  }
}
