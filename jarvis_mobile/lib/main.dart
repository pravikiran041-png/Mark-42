import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/io.dart';
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
  bool _ghostRunning = false;
  bool _ghostPaused = false;
  
  // Navigation
  int _currentIndex = 0;

  // Controls Tab
  final TextEditingController _textController = TextEditingController();

  // Vision Tab
  bool _isViewingScreen = false;
  Uint8List? _screenBytes;
  String _extractedText = "";

  // Ghost Tab
  final TextEditingController _solverModeController = TextEditingController(text: 'phone_chatgpt');
  final TextEditingController _phoneIpController = TextEditingController(text: 'usb');
  final TextEditingController _phonePinController = TextEditingController(text: '2580');
  final TextEditingController _injectModeController = TextEditingController(text: 'none');

  @override
  void initState() {
    super.initState();
    _initDevice();
    
    // Live config updates to daemon
    void sendConfigUpdate() {
      if (_isConnected && _channel != null) {
        _channel!.sink.add(jsonEncode({
          "type": "ghost_update_config",
          "inject_mode": _injectModeController.text,
          "solver_mode": _solverModeController.text,
        }));
      }
    }
    _injectModeController.addListener(sendConfigUpdate);
    _solverModeController.addListener(sendConfigUpdate);
  }

  // Hardcoded connection details — no QR code needed ever!
  static const String _defaultServerIp = 'facsimile-radio-oxford.ngrok-free.dev';
  static const String _defaultServerPort = '443';
  static const String _defaultServerToken = 'db0de22e-b700-477c-ada9-af227122742f';

  Future<void> _initDevice() async {
    final prefs = await SharedPreferences.getInstance();
    _deviceId = prefs.getString('device_id') ?? const Uuid().v4();
    await prefs.setString('device_id', _deviceId);
    
    // Auto-connect immediately using hardcoded server details
    // No QR code, no laptop UI needed!
    final ip = prefs.getString('last_server_ip') ?? _defaultServerIp;
    final port = prefs.getString('last_server_port') ?? _defaultServerPort;
    final token = prefs.getString('last_server_token') ?? _defaultServerToken;
    print('[JARVIS] Auto-connecting to $ip...');
    _connect(ip, port, token);
  }

  static const _accessibilityChannel = MethodChannel('com.jarvis.mobile/accessibility');
  static const _screenChannel = MethodChannel('com.jarvis.mobile/screen');
  static const _screenStream = EventChannel('com.jarvis.mobile/screen_stream');

  void _connect(String ip, String port, String token) {
    _savedIp = ip;
    _savedPort = port;
    _savedToken = token;
    _intentionalDisconnect = false;
    
    // Persist connection details so we can auto-reconnect even after app restart
    SharedPreferences.getInstance().then((prefs) {
      prefs.setString('last_server_ip', ip);
      prefs.setString('last_server_port', port);
      prefs.setString('last_server_token', token);
    });
    
    try {
      final isSecure = port == '443';
      final wsUrl = isSecure
          ? Uri.parse('wss://$ip')
          : Uri.parse('ws://$ip:$port');
      print('[JARVIS] Connecting to $wsUrl');
      _channel = IOWebSocketChannel.connect(wsUrl,
        headers: {
          'ngrok-skip-browser-warning': 'true',
          'User-Agent': 'jarvis-mobile'
        },
        pingInterval: const Duration(seconds: 30),
      );
      
      _channel!.stream.listen(
        (message) {
          if (message is Uint8List || message is List<int>) {
            setState(() {
              _screenBytes = message as Uint8List;
            });
            return;
          }
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
                _reconnectAttempts = 0; // Reset on successful connection
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
                    _channel!.sink.add(imageBytes);
                  }
                });
                
              } else if (data['type'] == 'pair_failed') {
                _disconnect("Pairing failed. Invalid token.");
              } else if (data['type'] == 'control') {
                if (data['action'] == 'tap') {
                  _accessibilityChannel.invokeMethod('tap', {'x': data['x'], 'y': data['y']});
                } else if (data['action'] == 'swipe') {
                  _accessibilityChannel.invokeMethod('swipe', {
                    'x1': data['x1'], 'y1': data['y1'], 'x2': data['x2'], 'y2': data['y2']
                  });
                } else if (data['action'] == 'ask_chatgpt') {
                  _accessibilityChannel.invokeMethod('ask_chatgpt', {'prompt': data['prompt']}).then((response) {
                    _channel!.sink.add(jsonEncode({
                      'type': 'chatgpt_response',
                      'response': response
                    }));
                  }).catchError((e) {
                    _channel!.sink.add(jsonEncode({
                      'type': 'chatgpt_response',
                      'error': e.toString()
                    }));
                  });
                }
              } else if (data['type'] == 'ghost_status') {
                setState(() {
                  _ghostRunning = data['status'] == 'running';
                  if (_ghostRunning) _ghostPaused = false;
                });
              } else if (data['type'] == 'ghost_pause_status') {
                setState(() {
                  _ghostPaused = data['paused'] == true;
                });
              } else if (data['type'] == 'ghost_log') {
                final msg = data['msg'] ?? '';
                if (msg.isNotEmpty && mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(msg), duration: const Duration(seconds: 2)),
                  );
                }
              } else if (data['type'] == 'extracted_text') {
                setState(() {
                  _extractedText = data['text'] ?? "";
                });
              }
            } catch (e) {
              // Ignore JSON decode errors for binary data
            }
          }
        },
        onDone: () {
          print('[JARVIS] WebSocket onDone fired');
          _handleDisconnect();
        },
        onError: (error) {
          print('[JARVIS] WebSocket onError: $error');
          _handleDisconnect();
        },
      );
    } catch (e) {
      print('[JARVIS] Connect exception: $e');
      _disconnect("Network error: $e");
    }
  }

  // Saved connection params for auto-reconnect
  String? _savedIp;
  String? _savedPort;
  String? _savedToken;
  bool _intentionalDisconnect = false;
  int _reconnectAttempts = 0;

  void _handleDisconnect() {
    if (_intentionalDisconnect) {
      _disconnect("Disconnected.");
      return;
    }
    // Auto-reconnect FOREVER (never give up)
    if (_savedIp != null && _savedPort != null && _savedToken != null) {
      _reconnectAttempts++;
      // Smart backoff: 2s, 2s, 5s, 5s, 10s, 10s, then cap at 15s
      int delay;
      if (_reconnectAttempts <= 2) {
        delay = 2;
      } else if (_reconnectAttempts <= 4) {
        delay = 5;
      } else if (_reconnectAttempts <= 6) {
        delay = 10;
      } else {
        delay = 15;
      }
      print('[JARVIS] Auto-reconnecting in ${delay}s (attempt $_reconnectAttempts)...');
      setState(() {
        _isConnected = false;
      });
      Future.delayed(Duration(seconds: delay), () {
        if (mounted && !_intentionalDisconnect) {
          _connect(_savedIp!, _savedPort!, _savedToken!);
        }
      });
    } else {
      _disconnect("Connection lost.");
    }
  }

  void _disconnect([String? reason]) {
    _stopRecording();
    _intentionalDisconnect = true;
    _channel?.sink.close();
    _savedIp = null;
    _savedPort = null;
    _savedToken = null;
    _reconnectAttempts = 0;
    // Clear saved connection so app doesn't auto-reconnect on restart
    SharedPreferences.getInstance().then((prefs) {
      prefs.remove('last_server_ip');
      prefs.remove('last_server_port');
      prefs.remove('last_server_token');
    });
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
    _textController.dispose();
    _solverModeController.dispose();
    _phoneIpController.dispose();
    _phonePinController.dispose();
    _injectModeController.dispose();
    super.dispose();
  }

  Widget _buildPairConnectSection() {
    return Column(
      children: [
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
    );
  }

  Widget _buildControlsTab() {
    return SingleChildScrollView(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const SizedBox(height: 40),
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
          const SizedBox(height: 40),
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
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 30),
            child: TextField(
              controller: _textController,
              decoration: const InputDecoration(
                labelText: 'Inject Text',
                border: OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(height: 10),
          ElevatedButton(
            onPressed: () {
              if (_isConnected && _channel != null) {
                _channel!.sink.add(jsonEncode({
                  "type": "paste_text",
                  "text": _textController.text,
                }));
                _textController.clear();
              }
            },
            child: const Text('Inject Text'),
          ),
          const SizedBox(height: 30),
          _buildPairConnectSection(),
          const SizedBox(height: 30),
        ],
      ),
    );
  }

  Widget _buildVisionTab() {
    return SingleChildScrollView(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const SizedBox(height: 40),
          ElevatedButton(
            onPressed: () {
              if (_isConnected && _channel != null) {
                final newViewing = !_isViewingScreen;
                _channel!.sink.add(jsonEncode({
                  "type": newViewing ? "start_screen" : "stop_screen"
                }));
                setState(() {
                  _isViewingScreen = newViewing;
                });
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: _isViewingScreen ? Colors.blue.shade800 : Colors.grey.shade800,
            ),
            child: Text(_isViewingScreen ? 'Stop Laptop Screen' : 'View Laptop Screen'),
          ),
          const SizedBox(height: 20),
          if (_screenBytes != null)
            Padding(
              padding: const EdgeInsets.all(8.0),
              child: Image.memory(
                _screenBytes!,
                height: 200,
                fit: BoxFit.contain,
                gaplessPlayback: true,
              ),
            ),
          const SizedBox(height: 20),
          ElevatedButton(
            onPressed: () {
              if (_isConnected && _channel != null) {
                _channel!.sink.add(jsonEncode({"type": "read_screen"}));
              }
            },
            child: const Text('Extract Text'),
          ),
          const SizedBox(height: 20),
          if (_extractedText.isNotEmpty)
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: Text(
                _extractedText,
                style: const TextStyle(color: Colors.white, fontSize: 14),
                textAlign: TextAlign.center,
              ),
            ),
          const SizedBox(height: 30),
          _buildPairConnectSection(),
          const SizedBox(height: 30),
        ],
      ),
    );
  }

  Widget _buildGhostTab() {
    return SingleChildScrollView(
      child: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          children: [
            const SizedBox(height: 20),
            TextField(
              controller: _solverModeController,
              decoration: const InputDecoration(labelText: 'Solver Mode', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _phoneIpController,
              decoration: const InputDecoration(labelText: 'Phone IP', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _phonePinController,
              decoration: const InputDecoration(labelText: 'Phone PIN', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _injectModeController,
              decoration: const InputDecoration(labelText: 'Inject Mode', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 30),
            if (_isConnected)
              Container(
                decoration: BoxDecoration(
                  boxShadow: [
                    BoxShadow(
                      color: _ghostRunning ? Colors.purpleAccent.withOpacity(0.5) : Colors.greenAccent.withOpacity(0.5),
                      blurRadius: 15,
                      spreadRadius: 2,
                    ),
                  ],
                ),
                child: ElevatedButton(
                  onPressed: () {
                    if (_channel != null) {
                      final newStatus = !_ghostRunning;
                      if (newStatus) {
                        _channel!.sink.add(jsonEncode({
                          "type": "ghost_start",
                          "solver_mode": _solverModeController.text,
                          "phone_ip": _phoneIpController.text,
                          "phone_pin": _phonePinController.text,
                          "inject_mode": _injectModeController.text,
                        }));
                      } else {
                        _channel!.sink.add(jsonEncode({"type": "ghost_stop"}));
                      }
                      setState(() {
                        _ghostRunning = newStatus;
                      });
                    }
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _ghostRunning ? Colors.purple.shade800 : Colors.green.shade800,
                    padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 20),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(30),
                      side: BorderSide(color: _ghostRunning ? Colors.purpleAccent : Colors.greenAccent, width: 2),
                    ),
                  ),
                  child: Text(
                    _ghostRunning ? '👻 STOP GHOST MODE' : '👻 START GHOST MODE',
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, letterSpacing: 2.0, color: Colors.white),
                  ),
                ),
              ),
            if (_ghostRunning)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: ElevatedButton.icon(
                  onPressed: () {
                    if (_channel != null) {
                      _channel!.sink.add(jsonEncode({"type": "ghost_toggle_pause"}));
                      setState(() {
                        _ghostPaused = !_ghostPaused;
                      });
                    }
                  },
                  icon: Icon(_ghostPaused ? Icons.play_arrow : Icons.pause, size: 28),
                  label: Text(
                    _ghostPaused ? '▶️ RESUME SCANNING' : '⏸️ PAUSE SCANNING',
                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _ghostPaused ? Colors.orange.shade800 : Colors.blue.shade800,
                    padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                  ),
                ),
              ),
            const SizedBox(height: 30),
            _buildPairConnectSection(),
            const SizedBox(height: 30),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final List<Widget> _tabs = [
      _buildControlsTab(),
      _buildVisionTab(),
      _buildGhostTab(),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text('JARVIS', style: TextStyle(letterSpacing: 2.0)),
        centerTitle: true,
        backgroundColor: Colors.transparent,
        elevation: 0,
      ),
      body: _tabs[_currentIndex],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (index) {
          setState(() {
            _currentIndex = index;
          });
        },
        selectedItemColor: Colors.cyan,
        unselectedItemColor: Colors.grey,
        backgroundColor: Colors.black,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.settings_remote), label: 'Controls'),
          BottomNavigationBarItem(icon: Icon(Icons.remove_red_eye), label: 'Vision'),
          BottomNavigationBarItem(icon: Icon(Icons.adb), label: 'Ghost'),
        ],
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
