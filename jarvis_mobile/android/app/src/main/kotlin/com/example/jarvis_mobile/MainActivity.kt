package com.example.jarvis_mobile

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import android.util.Log

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.content.Context

class MainActivity : FlutterActivity() {
    private val ACCESSIBILITY_CHANNEL = "com.jarvis.mobile/accessibility"
    private val SCREEN_CHANNEL = "com.jarvis.mobile/screen"
    private val REQUEST_CODE_SCREEN_CAPTURE = 1001
    
    private var screenResult: io.flutter.plugin.common.MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        
        // ACCESSIBILITY CHANNEL
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, ACCESSIBILITY_CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "tap" -> {
                    val x = call.argument<Double>("x")?.toFloat()
                    val y = call.argument<Double>("y")?.toFloat()
                    if (x != null && y != null) {
                        JarvisAccessibilityService.instance?.tap(x, y)
                        result.success(true)
                    } else result.error("ERR", "Missing args", null)
                }
                "swipe" -> {
                    val x1 = call.argument<Double>("x1")?.toFloat()
                    val y1 = call.argument<Double>("y1")?.toFloat()
                    val x2 = call.argument<Double>("x2")?.toFloat()
                    val y2 = call.argument<Double>("y2")?.toFloat()
                    if (x1 != null && y1 != null && x2 != null && y2 != null) {
                        JarvisAccessibilityService.instance?.swipe(x1, y1, x2, y2, 300L)
                        result.success(true)
                    } else result.error("ERR", "Missing args", null)
                }
                "checkService" -> {
                    result.success(JarvisAccessibilityService.instance != null)
                }
                else -> result.notImplemented()
            }
        }
        
        // SCREEN CAPTURE CHANNEL
        val screenChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, SCREEN_CHANNEL)
        screenChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "start" -> {
                    if (ScreenCaptureService.isRunning) {
                        result.success(true)
                        return@setMethodCallHandler
                    }
                    screenResult = result
                    val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                    startActivityForResult(manager.createScreenCaptureIntent(), REQUEST_CODE_SCREEN_CAPTURE)
                }
                "stop" -> {
                    val intent = Intent(this, ScreenCaptureService::class.java)
                    intent.action = ScreenCaptureService.ACTION_STOP
                    startService(intent)
                    ScreenCaptureService.listener = null
                    result.success(true)
                }
                else -> result.notImplemented()
            }
        }
        
        // Set up EventChannel or just callback for images
        io.flutter.plugin.common.EventChannel(flutterEngine.dartExecutor.binaryMessenger, "com.jarvis.mobile/screen_stream").setStreamHandler(
            object : io.flutter.plugin.common.EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: io.flutter.plugin.common.EventChannel.EventSink?) {
                    ScreenCaptureService.listener = { bytes ->
                        runOnUiThread { events?.success(bytes) }
                    }
                }
                override fun onCancel(arguments: Any?) {
                    ScreenCaptureService.listener = null
                }
            }
        )
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQUEST_CODE_SCREEN_CAPTURE) {
            if (resultCode == Activity.RESULT_OK && data != null) {
                val intent = Intent(this, ScreenCaptureService::class.java).apply {
                    action = ScreenCaptureService.ACTION_START
                    putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, resultCode)
                    putExtra(ScreenCaptureService.EXTRA_DATA, data)
                }
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                    startForegroundService(intent)
                } else {
                    startService(intent)
                }
                screenResult?.success(true)
            } else {
                screenResult?.error("DENIED", "Screen capture permission denied", null)
            }
            screenResult = null
        } else {
            super.onActivityResult(requestCode, resultCode, data)
        }
    }
}
