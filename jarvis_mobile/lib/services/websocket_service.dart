import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/status.dart' as status;

class WebSocketService {
  WebSocketChannel? _channel;
  final StreamController<bool> _connectionStatusController = StreamController<bool>.broadcast();
  final StreamController<Map<String, dynamic>> _messageController = StreamController<Map<String, dynamic>>.broadcast();

  Stream<bool> get connectionStatusStream => _connectionStatusController.stream;
  Stream<Map<String, dynamic>> get messageStream => _messageController.stream;

  bool get isConnected => _channel != null;

  /// Connects to the JARVIS backend via WebSocket
  /// [url] should look like ws://192.168.1.5:8000/ws
  Future<bool> connect(String url, String deviceId, String token) async {
    try {
      final wsUrl = Uri.parse('$url/ws/mobile?device_id=$deviceId&token=$token');
      _channel = WebSocketChannel.connect(wsUrl);

      // Listen for incoming messages
      _channel!.stream.listen(
        (message) {
          try {
            final decoded = jsonDecode(message);
            _messageController.add(decoded);
          } catch (e) {
            print("Error decoding WS message: $e");
          }
        },
        onDone: () {
          print("WebSocket Disconnected.");
          _setDisconnected();
        },
        onError: (error) {
          print("WebSocket Error: $error");
          _setDisconnected();
        },
      );

      // Successfully connected
      _connectionStatusController.add(true);
      return true;
    } catch (e) {
      print("Failed to connect: $e");
      _setDisconnected();
      return false;
    }
  }

  void _setDisconnected() {
    _channel = null;
    _connectionStatusController.add(false);
  }

  void sendMessage(Map<String, dynamic> data) {
    if (_channel != null) {
      _channel!.sink.add(jsonEncode(data));
    }
  }

  void disconnect() {
    if (_channel != null) {
      _channel!.sink.close(status.goingAway);
      _setDisconnected();
    }
  }

  void dispose() {
    disconnect();
    _connectionStatusController.close();
    _messageController.close();
  }
}
