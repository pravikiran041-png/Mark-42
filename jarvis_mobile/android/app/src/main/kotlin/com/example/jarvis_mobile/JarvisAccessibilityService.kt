package com.example.jarvis_mobile

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.view.accessibility.AccessibilityEvent
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
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

    fun askChatGPT(prompt: String, callback: (String) -> Unit) {
        kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.IO).launch {
            try {
                // 1. Launch ChatGPT App
                val intent = packageManager.getLaunchIntentForPackage("com.openai.chatgpt")
                if (intent == null) {
                    callback("Error: ChatGPT app not found.")
                    return@launch
                }
                intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                startActivity(intent)

                // 2. Wait for Input Field and paste text
                var inputNode: android.view.accessibility.AccessibilityNodeInfo? = null
                for (i in 0..20) {
                    kotlinx.coroutines.delay(500)
                    val root = rootInActiveWindow
                    if (root != null) {
                        inputNode = findEditableNode(root)
                        if (inputNode != null) break
                    }
                }
                
                if (inputNode == null) {
                    callback("Error: Could not find ChatGPT input field.")
                    return@launch
                }
                
                // Paste text
                val arguments = android.os.Bundle()
                arguments.putCharSequence(android.view.accessibility.AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, prompt)
                inputNode.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
                kotlinx.coroutines.delay(1000)
                
                // 3. Find and click Send button
                var sendClicked = false
                val rootAfterPaste = rootInActiveWindow
                if (rootAfterPaste != null) {
                    var sendBtn = findSendButton(rootAfterPaste, strict = true)
                    if (sendBtn == null) {
                        sendBtn = findSendButton(rootAfterPaste, strict = false)
                    }
                    if (sendBtn != null) {
                        sendBtn.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK)
                        sendClicked = true
                    }
                }
                
                if (!sendClicked) {
                    callback("Error: Could not click Send button.")
                    return@launch
                }
                
                // 4. Wait for response to generate
                // ChatGPT responses appear as non-editable text views.
                // We will poll until a new long text bubble appears that matches neither the prompt nor empty.
                kotlinx.coroutines.delay(3000)
                var lastResponse = ""
                var stableCount = 0
                
                for (i in 0..60) { // wait up to 30 seconds
                    kotlinx.coroutines.delay(500)
                    val r = rootInActiveWindow ?: continue
                    val bubbles = findTextNodes(r).filter { it.text != null && it.text.toString() != prompt && !it.isEditable }
                    
                    if (bubbles.isNotEmpty()) {
                        // The last bubble is usually the latest response
                        val currentResponse = bubbles.last().text.toString()
                        if (currentResponse.length > 5 && currentResponse == lastResponse) {
                            stableCount++
                            if (stableCount >= 4) { // stable for 2 seconds = finished
                                callback(currentResponse)
                                return@launch
                            }
                        } else {
                            stableCount = 0
                        }
                        lastResponse = currentResponse
                    }
                }
                if (lastResponse.isNotEmpty()) {
                    callback(lastResponse)
                } else {
                    callback("Error: Timeout waiting for ChatGPT response.")
                }
                
            } catch (e: Exception) {
                callback("Error: ${e.message}")
            }
        }
    }

    private fun findEditableNode(node: android.view.accessibility.AccessibilityNodeInfo?): android.view.accessibility.AccessibilityNodeInfo? {
        if (node == null) return null
        if (node.isEditable || node.className?.toString()?.contains("EditText") == true) return node
        for (i in 0 until node.childCount) {
            val child = findEditableNode(node.getChild(i))
            if (child != null) return child
        }
        return null
    }

    private fun findSendButton(node: android.view.accessibility.AccessibilityNodeInfo?, strict: Boolean = true): android.view.accessibility.AccessibilityNodeInfo? {
        if (node == null) return null
        val desc = node.contentDescription?.toString()?.lowercase() ?: ""
        val text = node.text?.toString()?.lowercase() ?: ""
        val id = node.viewIdResourceName?.lowercase() ?: ""
        val className = node.className?.toString()?.lowercase() ?: ""
        
        val isSendIndicator = desc.contains("send") || desc.contains("submit") || text.contains("send") || id.contains("send")
        
        if (strict) {
            if (node.isClickable && isSendIndicator) return node
            if (isSendIndicator && node.parent != null && node.parent.isClickable) return node.parent
        } else {
            // Fallback pass: Any clickable image/button that isn't clearly something else
            val isIcon = className.contains("image") || className.contains("button")
            val isNotOtherStuff = !desc.contains("menu") && !desc.contains("settings") && !desc.contains("attach") && !text.contains("menu")
            if (node.isClickable && isIcon && isNotOtherStuff && text.isEmpty()) return node
        }
        
        for (i in 0 until node.childCount) {
            val child = findSendButton(node.getChild(i), strict)
            if (child != null) return child
        }
        return null
    }

    private fun findTextNodes(node: android.view.accessibility.AccessibilityNodeInfo?): List<android.view.accessibility.AccessibilityNodeInfo> {
        val result = mutableListOf<android.view.accessibility.AccessibilityNodeInfo>()
        if (node == null) return result
        if (node.text != null && node.text.toString().isNotEmpty()) {
            result.add(node)
        }
        for (i in 0 until node.childCount) {
            result.addAll(findTextNodes(node.getChild(i)))
        }
        return result
    }
}
