import asyncio
import websockets
import json

async def test():
    with open("core/.ngrok_url", "r") as f:
        url = "wss://" + f.read().strip() + ":443"
    print(f"Connecting to {url}...")
    try:
        async with websockets.connect(url, additional_headers={"ngrok-skip-browser-warning": "true"}) as ws:
            print("Connected!")
            await ws.send(json.dumps({"type": "ghost_start", "solver_mode": "phone_chatgpt"}))
            print("Sent ghost_start")
            
            while True:
                msg = await ws.recv()
                print("Received:", msg)
    except Exception as e:
        print(f"Failed: {e}")

asyncio.run(test())
