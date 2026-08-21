import os
import json
import uuid

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "api_keys.json")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "core", ".pairing_token")

DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "groq_api_key": "",
    "openrouter_api_key": "",
    "os_system": "mac" if os.name != "nt" else "windows",
    "morning_brief_enabled": False,
    "assistant_name": "JARVIS",
    "user_name": "",
    "ui_color": "#00d4ff",
    "camera_index": 0,
    "ngrok_authtoken": "",
    "ngrok_domain": ""
}

def print_header(title):
    print("\n" + "="*50)
    print(f"  {title}")
    print("="*50 + "\n")

def run_wizard():
    print_header("JARVIS First-Run Setup Wizard")
    
    # Ensure config directory exists
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "core"), exist_ok=True)

    # Load existing config or use default
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                existing_config = json.load(f)
                config.update(existing_config)
        except Exception:
            pass

    # Check if setup is needed
    needs_setup = False
    if not config.get("gemini_api_key") or "PASTE" in config.get("gemini_api_key"):
        needs_setup = True
    if not config.get("ngrok_authtoken") or "PASTE" in config.get("ngrok_authtoken"):
        needs_setup = True
    if not config.get("ngrok_domain") or "YOUR-OWN-DOMAIN" in config.get("ngrok_domain"):
        needs_setup = True

    if not needs_setup:
        print("✅ Config looks good. Skipping setup.")
        return

    print("Welcome! Let's get JARVIS configured for your laptop.\n")
    
    # Gemini API Key
    while not config.get("gemini_api_key") or "PASTE" in config.get("gemini_api_key"):
        print("1. Get a FREE Gemini API Key from: https://aistudio.google.com/apikey")
        key = input("   Paste your Gemini API Key here: ").strip()
        if key:
            config["gemini_api_key"] = key

    # Ngrok Authtoken
    while not config.get("ngrok_authtoken") or "PASTE" in config.get("ngrok_authtoken"):
        print("\n2. Get your FREE Ngrok Authtoken from: https://dashboard.ngrok.com/get-started/your-authtoken")
        token = input("   Paste your Ngrok Authtoken here: ").strip()
        if token:
            config["ngrok_authtoken"] = token

    # Ngrok Domain
    while not config.get("ngrok_domain") or "YOUR-OWN-DOMAIN" in config.get("ngrok_domain"):
        print("\n3. Get your FREE Ngrok Domain from: https://dashboard.ngrok.com/cloud-edge/domains")
        print("   (It looks like: something-random.ngrok-free.dev)")
        domain = input("   Paste your Ngrok Domain here: ").strip()
        if domain:
            # Clean up domain input just in case they pasted the full URL
            domain = domain.replace("https://", "").replace("http://", "").split("/")[0]
            config["ngrok_domain"] = domain

    # Save Config
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
        
    # Generate Pairing Token
    if not os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "w") as f:
            f.write(str(uuid.uuid4()))

    print_header("Setup Complete! JARVIS is ready.")

if __name__ == "__main__":
    run_wizard()
