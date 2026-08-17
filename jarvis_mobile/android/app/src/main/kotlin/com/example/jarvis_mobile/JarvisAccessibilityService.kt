package com.example.jarvis_mobile

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.view.accessibility.AccessibilityEvent
import android.util.Log

class JarvisAccessibilityService : AccessibilityService() {

    companion object {
        var instance: JarvisAccessibilityService? = null
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.d("JarvisAccessibility", "JARVIS Accessibility Service Connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // We don't necessarily need to process events for view-only, just perform gestures
    }

    override fun onInterrupt() {
        Log.d("JarvisAccessibility", "JARVIS Accessibility Service Interrupted")
    }

    override fun onDestroy() {
        super.onDestroy()
        instance = null
        Log.d("JarvisAccessibility", "JARVIS Accessibility Service Destroyed")
    }

    fun tap(x: Float, y: Float) {
        val path = Path()
        path.moveTo(x, y)
        val gestureBuilder = GestureDescription.Builder()
        val stroke = GestureDescription.StrokeDescription(path, 0, 100)
        gestureBuilder.addStroke(stroke)
        
        val result = dispatchGesture(gestureBuilder.build(), object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                Log.d("JarvisAccessibility", "Tap completed at $x, $y")
            }

            override fun onCancelled(gestureDescription: GestureDescription?) {
                Log.d("JarvisAccessibility", "Tap cancelled at $x, $y")
            }
        }, null)
        Log.d("JarvisAccessibility", "Dispatch gesture result: $result")
    }

    fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, durationMs: Long) {
        val path = Path()
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
        val gestureBuilder = GestureDescription.Builder()
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs)
        gestureBuilder.addStroke(stroke)
        dispatchGesture(gestureBuilder.build(), null, null)
    }
}
