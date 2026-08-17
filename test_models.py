import asyncio
from google import genai
import json

def get_key():
    with open('config/api_keys.json') as f:
        return json.load(f)['gemini_api_key']

async def test_model(model_name):
    client = genai.Client(api_key=get_key())
    try:
        async with client.aio.live.connect(model=model_name) as session:
            print(f"SUCCESS with {model_name}")
            return True
    except Exception as e:
        print(f"FAILED {model_name}: {e}")
        return False

async def main():
    models_to_test = [
        "gemini-2.5-flash",
        "models/gemini-2.5-flash",
        "gemini-2.5-flash-native-audio-latest",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro"
    ]
    for model in models_to_test:
        print(f"Testing {model}...")
        await test_model(model)

if __name__ == "__main__":
    asyncio.run(main())
