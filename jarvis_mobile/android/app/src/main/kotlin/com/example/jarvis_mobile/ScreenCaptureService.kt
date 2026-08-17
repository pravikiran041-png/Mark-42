package com.example.jarvis_mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationCompat
import java.io.ByteArrayOutputStream

class ScreenCaptureService : Service() {
    companion object {
        var isRunning = false
        var listener: ((ByteArray) -> Unit)? = null
        
        const val ACTION_START = "START_CAPTURE"
        const val ACTION_STOP = "STOP_CAPTURE"
        const val EXTRA_RESULT_CODE = "RESULT_CODE"
        const val EXTRA_DATA = "DATA"
    }

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private val handler = Handler(Looper.getMainLooper())
    private var isCapturing = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                startForeground()
                val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
                val data: Intent? = intent.getParcelableExtra(EXTRA_DATA)
                if (data != null) {
                    startCapture(resultCode, data)
                }
            }
            ACTION_STOP -> {
                stopCapture()
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    private fun startForeground() {
        val channelId = "jarvis_screen_capture"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(channelId, "Screen Capture", NotificationManager.IMPORTANCE_LOW)
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
        val notification: Notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("JARVIS Vision")
            .setContentText("Screen mirroring is active")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1, notification, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(1, notification)
        }
        isRunning = true
    }

    private fun startCapture(resultCode: Int, data: Intent) {
        val projectionManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjection = projectionManager.getMediaProjection(resultCode, data)
        
        // Android 14+ requires registering a callback before creating virtual display
        mediaProjection?.registerCallback(object : MediaProjection.Callback() {}, handler)
        
        val metrics = resources.displayMetrics
        val width = metrics.widthPixels // Stream in FULL resolution for clarity and touch coordinate accuracy
        val height = metrics.heightPixels
        val density = metrics.densityDpi

        imageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        
        virtualDisplay = mediaProjection?.createVirtualDisplay(
            "JarvisScreen",
            width, height, density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader?.surface, null, handler
        )

        isCapturing = true
        captureLoop(width, height)
    }

    private fun captureLoop(width: Int, height: Int) {
        if (!isCapturing) return
        
        try {
            val image = imageReader?.acquireLatestImage()
            if (image != null) {
                val planes = image.planes
                val buffer = planes[0].buffer
                val pixelStride = planes[0].pixelStride
                val rowStride = planes[0].rowStride
                val rowPadding = rowStride - pixelStride * width
                
                val bitmap = Bitmap.createBitmap(width + rowPadding / pixelStride, height, Bitmap.Config.ARGB_8888)
                bitmap.copyPixelsFromBuffer(buffer)
                image.close()

                // Compress with higher quality for sharp text and UI
                val out = ByteArrayOutputStream()
                bitmap.compress(Bitmap.CompressFormat.JPEG, 70, out) 
                val bytes = out.toByteArray()
                
                listener?.invoke(bytes)
            }
        } catch (e: Exception) {
            Log.e("ScreenCapture", "Capture error", e)
        }
        
        // 15 FPS for a smoother experience
        handler.postDelayed({ captureLoop(width, height) }, 60)
    }

    private fun stopCapture() {
        isCapturing = false
        virtualDisplay?.release()
        imageReader?.close()
        mediaProjection?.stop()
        isRunning = false
    }
}
