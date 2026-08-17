import asyncio, subprocess

async def test():
    adb_prefix = ['adb']
    cx, cy = 540, 2176
    
    print("Triple tapping...")
    for _ in range(3):
        proc = await asyncio.create_subprocess_exec(*(adb_prefix + ["shell", "input", "tap", str(cx), str(cy)]))
        await proc.wait()
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)
    
    print("Typing test...")
    proc = await asyncio.create_subprocess_exec(*(adb_prefix + ["shell", "input", "text", "Test"]))
    await proc.wait()
    print("Done!")

asyncio.run(test())
