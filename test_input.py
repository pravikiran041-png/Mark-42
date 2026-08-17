import asyncio, subprocess

async def test():
    adb_prefix = ['adb']
    question_text = 'Does this work?'
    escaped_text = question_text[:500].replace('\n', ' ').replace(' ', '%s').replace("'", "'\\''")
    safe_text = f"'{escaped_text}'"
    
    print('Sending:', safe_text)
    
    proc = await asyncio.create_subprocess_exec(
        *(adb_prefix + ['shell', 'input', 'text', safe_text]),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    print('stdout:', stdout)
    print('stderr:', stderr)

asyncio.run(test())
