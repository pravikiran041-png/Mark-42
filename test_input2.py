import asyncio, subprocess

async def test():
    adb_prefix = ['adb', '-s', 'R5CX43EFMFR']
    
    # 1. Open ChatGPT
    print("Opening ChatGPT...")
    proc = await asyncio.create_subprocess_exec(*(adb_prefix + ["shell", "monkey", "-p", "com.openai.chatgpt", "-c", "android.intent.category.LAUNCHER", "1"]))
    await proc.wait()
    await asyncio.sleep(3)
    
    # 2. Tap roughly where the input box is (middle bottom)
    print("Tapping input box...")
    proc = await asyncio.create_subprocess_exec(*(adb_prefix + ["shell", "input", "tap", "500", "2000"]))
    await proc.wait()
    await asyncio.sleep(1)
    
    # 3. Type text with parenthesis
    question_text = "What is 10 + 15? A) 20 B) 25 (Test)"
    print("Typing text:", question_text)
    
    escaped_text = question_text[:500].replace('\n', ' ').replace(' ', '%s').replace("'", "'\\''")
    safe_text = f"'{escaped_text}'"
    
    proc = await asyncio.create_subprocess_exec(
        *(adb_prefix + ['shell', 'input', 'text', safe_text])
    )
    await proc.wait()
    print("Done!")

asyncio.run(test())
