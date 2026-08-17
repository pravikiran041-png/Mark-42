import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import 'package:record/record.dart';
import 'package:permission_handler/permission_handler.dart';

void main() {
  runApp(const JarvisMobileApp());
}

class JarvisMobileApp extends StatelessWidget {
  const JarvisMobileApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'JARVIS Companion',
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: Colors.black,
        colorScheme: const ColorScheme.dark(
          primary: Colors.blueAccent,
          secondary: Colors.lightBlueAccent,
        ),
      ),
      home: const JarvisHome(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class JarvisHome extends StatefulWidget {
  const JarvisHome({super.key});

  @override
  State<JarvisHome> createState() => _JarvisHomeState();
}

class _JarvisHomeState extends State<JarvisHome> {
  WebSocketChannel? _channel;
  bool _isConnected = false;
  String _deviceId = "";
  
  final AudioRecorder _audioRecorder = AudioRecorder();
  bool _isRecording = false;

  @override
  void initState() {
    super.initState();
    _initDevice();
  }

  Future<void> _initDevice() async {
    final prefs = await SharedPreferences.getInstance();
    _deviceId = prefs.getString('device_id') ?? const Uuid().v4();
    await prefs.setString('device_id', _deviceId);
  }

  static const _accessibilityChannel = MethodChannel('com.jarvis.mobile/accessibility');
  static const _screenChannel = MethodChannel('com.jarvis.mobile/screen');
  static const _screenStream = EventChannel('com.jarvis.mobile/screen_stream');

  void _connect(String ip, String port, String token) {
    try {
      final wsUrl = Uri.parse('ws://$ip:$port');
      _channel = WebSocketChannel.connect(wsUrl);
      
      _channel!.stream.listen(
        (message) {
          if (message is String) {
            try {
              final data = jsonDecode(message);
              if (data['type'] == 'status' && data['status'] == 'connected') {
                _channel!.sink.add(jsonEncode({
                  'type': 'pair',
                  'token': token,
                  'device_id': _deviceId,
                }));
              } else if (data['type'] == 'pair_success') {
                setState(() {
                  _isConnected = true;
                });
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Connected to JARVIS successfully!')),
                );
                
                // Start Native Screen Streaming
                _screenChannel.invokeMethod('start');
                _screenStream.receiveBroadcastStream().listen((imageBytes) {
                  if (_isConnected && _channel != null) {
                    // Prepend a tiny header or just send as is? 
                    // Let's send as raw bytes and the server can sniff JPEG header (0xFF 0xD8)
                    _channel!.sink.add(imageBytes);
                  }
                });
                
              } else if (data['type'] == 'pair_failed') {
                _disconnect("Pairing failed. Invalid token.");
              } else if (data['type'] == 'control') {
                // JARVIS is trying to control the phone!
                if (data['action'] == 'tap') {
                  _accessibilityChannel.invokeMethod('tap', {'x': data['x'], 'y': data['y']});
                } else if (data['action'] == 'swipe') {
                  _accessibilityChannel.invokeMethod('swipe', {
                    'x1': data['x1'], 'y1': data['y1'], 'x2': data['x2'], 'y2': data['y2']
                  });
                }
              }
            } catch (e) {
              // Ignore JSON decode errors for binary data
            }
          }
        },
        onDone: () {
          _disconnect("Connection closed by JARVIS.");
        },
        onError: (error) {
          _disconnect("Connection error: $error");
        },
      );
    } catch (e) {
      _disconnect("Network error: $e");
    }
  }

  void _disconnect([String? reason]) {
    _stopRecording();
    _channel?.sink.close();
    setState(() {
      _isConnected = false;
    });
    if (reason != null && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(reason), backgroundColor: Colors.redAccent),
      );
    }
  }

  void _openScanner() {
    Navigator.of(context).push(MaterialPageRoute(
      builder: (context) => QRScannerScreen(
        onScan: (ip, port, token) {
          Navigator.pop(context);
          _connect(ip, port, token);
        },
      ),
    ));
  }

  Future<void> _toggleRecording() async {
    if (_isRecording) {
      await _stopRecording();
    } else {
      await _startRecording();
    }
  }

  Future<void> _startRecording() async {
    if (!_isConnected || _channel == null) return;
    
    final status = await Permission.microphone.request();
    if (status != PermissionStatus.granted) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Microphone permission required.'), backgroundColor: Colors.orange),
        );
      }
      return;
    }

    try {
      // 16kHz, 16-bit, Mono PCM
      final stream = await _audioRecorder.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: 16000,
          numChannels: 1,
        ),
      );

      stream.listen(
        (data) {
          if (_isConnected && _channel != null) {
            _channel!.sink.add(data);
          }
        },
        onDone: () {
          _stopRecording();
        },
        onError: (e) {
          _stopRecording();
        }
      );

      setState(() {
        _isRecording = true;
      });
    } catch (e) {
      debugPrint("Error starting record: $e");
    }
  }

  Future<void> _stopRecording() async {
    if (!_isRecording) return;
    try {
      await _audioRecorder.stop();
    } catch (e) {
      debugPrint("Error stopping record: $e");
    }
    setState(() {
      _isRecording = false;
    });
  }

  @override
  void dispose() {
    _stopRecording();
    _audioRecorder.dispose();
    _channel?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Glowing Core
            GestureDetector(
              onTap: _isConnected ? _toggleRecording : null,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                width: _isRecording ? 180 : 150,
                height: _isRecording ? 180 : 150,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: _isConnected 
                        ? (_isRecording ? Colors.redAccent : Colors.cyan) 
                        : Colors.blueAccent.withOpacity(0.5), 
                    width: _isRecording ? 4 : 2
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: (_isConnected 
                          ? (_isRecording ? Colors.redAccent : Colors.cyan) 
                          : Colors.blueAccent).withOpacity(_isConnected ? (_isRecording ? 0.6 : 0.4) : 0.2),
                      blurRadius: _isRecording ? 80 : 50,
                      spreadRadius: _isRecording ? 20 : 10,
                    ),
                  ],
                ),
                child: Center(
                  child: _isRecording 
                    ? const Icon(Icons.mic, size: 60, color: Colors.redAccent)
                    : Text(
                        'JARVIS',
                        style: TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 4.0,
                          color: _isConnected ? Colors.cyan : Colors.blueAccent,
                        ),
                      ),
                ),
              ),
            ),
            const SizedBox(height: 60),
            
            // Connection Status
            Text(
              _isConnected 
                  ? (_isRecording ? 'TRANSMITTING VOICE...' : 'SYSTEM ONLINE - TAP TO SPEAK')
                  : 'SYSTEM OFFLINE',
              style: TextStyle(
                color: _isConnected 
                    ? (_isRecording ? Colors.redAccent : Colors.cyan) 
                    : Colors.redAccent,
                letterSpacing: 2.0,
                fontSize: 12,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 30),

            // Pair Button
            if (!_isConnected)
              OutlinedButton.icon(
                onPressed: _openScanner,
                icon: const Icon(Icons.qr_code_scanner, color: Colors.blueAccent),
                label: const Text(
                  'PAIR WITH DESKTOP',
                  style: TextStyle(color: Colors.blueAccent, letterSpacing: 1.5),
                ),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: Colors.blueAccent),
                  padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 15),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(30),
                  ),
                ),
              ),
              
            if (_isConnected)
              OutlinedButton.icon(
                onPressed: () => _disconnect("Disconnected by user."),
                icon: const Icon(Icons.link_off, color: Colors.redAccent),
                label: const Text(
                  'DISCONNECT',
                  style: TextStyle(color: Colors.redAccent, letterSpacing: 1.5),
                ),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: Colors.redAccent),
                  padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 15),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(30),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class QRScannerScreen extends StatefulWidget {
  final Function(String ip, String port, String token) onScan;

  const QRScannerScreen({super.key, required this.onScan});

  @override
  State<QRScannerScreen> createState() => _QRScannerScreenState();
}

class _QRScannerScreenState extends State<QRScannerScreen> {
  bool _scanned = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Scan JARVIS QR Code', style: TextStyle(fontSize: 16, letterSpacing: 1.2)),
        backgroundColor: Colors.transparent,
        elevation: 0,
      ),
      body: MobileScanner(
        onDetect: (capture) {
          if (_scanned) return;
          final List<Barcode> barcodes = capture.barcodes;
          for (final barcode in barcodes) {
            final rawValue = barcode.rawValue;
            if (rawValue != null && rawValue.startsWith('jarvis://pair')) {
              _scanned = true;
              final uri = Uri.parse(rawValue);
              final ip = uri.queryParameters['ip'];
              final port = uri.queryParameters['port'];
              final token = uri.queryParameters['token'];
              
              if (ip != null && port != null && token != null) {
                widget.onScan(ip, port, token);
                break;
              }
            }
          }
        },
      ),
    );
  }
}
