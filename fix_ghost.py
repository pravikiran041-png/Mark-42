import re

with open("ghost_mode.py", "r") as f:
    content = f.read()

pattern = re.compile(r"    async def _get_answer_phone_chatgpt\(self, question_text: str\) -> str:.*?    # ── Answer Injection ────────────────────────────────────────────", re.DOTALL)

new_method = """    async def _get_answer_phone_chatgpt(self, question_text: str) -> str:
        \"\"\"Runs the Phone ChatGPT Route entirely natively on the phone over WebSocket (No ADB required).\"\"\"
        await self._emit({"type": "ghost_log", "msg": "🤖 Asking ChatGPT natively on your phone..."})
        
        if not hasattr(self, 'phone_chatgpt_callback') or not self.phone_chatgpt_callback:
            return "[Error: Native phone ChatGPT automation is not available. Please restart the daemon.]"
            
        try:
            answer = await self.phone_chatgpt_callback(question_text)
            await self._emit({"type": "ghost_log", "msg": "✅ Native ChatGPT response received."})
            return answer
        except Exception as e:
            return f"[Error: Native Phone ChatGPT failed: {e}]"

    # ── Answer Injection ────────────────────────────────────────────"""

content = pattern.sub(new_method, content)

with open("ghost_mode.py", "w") as f:
    f.write(content)

print("Fixed ghost_mode.py")
