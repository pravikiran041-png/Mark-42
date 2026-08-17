import json
from google import genai

def get_key():
    with open('config/api_keys.json') as f:
        return json.load(f)['gemini_api_key']

client = genai.Client(api_key=get_key())
try:
    for model in client.models.list():
        print(f"Model: {model.name}")
except Exception as e:
    print(f"Error: {e}")
print("Done listing.")
