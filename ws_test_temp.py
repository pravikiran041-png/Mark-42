import asyncio
import websockets

async def test():
    url = "wss://facsimile-radio-oxford.ngrok-free.dev:443"
    print(f"Connecting to {url}...")
    try:
        async with websockets.connect(url, additional_headers={"ngrok-skip-browser-warning": "true"}) as ws:
            print("Connected!")
    except Exception as e:
        print(f"Failed: {e}")

asyncio.run(test())
