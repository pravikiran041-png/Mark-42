import os
import json
import subprocess
import datetime
from typing import Dict, Any, List

# Ensure backend directory exists
BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
os.makedirs(BACKEND_DIR, exist_ok=True)
LOG_FILE = os.path.join(BACKEND_DIR, "terminal_log.json")

BLOCKED_COMMANDS = [
    "rm -rf",
    "sudo rm",
    "format",
    "mkfs",
    "dd if=",
    "chmod 777 /",
    "chown -R root",
    "> /dev/sda",
    "shutdown",
    "reboot",
    ":(){ :|:& };:",  # fork bomb
    "curl | sh",
    "wget | sh",
]

def is_safe_command(cmd: str) -> bool:
    cmd_lower = cmd.lower()
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return False
    return True

def _log_command(command: str, output_summary: str, safe: bool, confirmed: bool):
    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)
    except Exception:
        logs = []
    
    logs.append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "command": command,
        "output_summary": output_summary,
        "safe": safe,
        "confirmed": confirmed
    })
    
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

def _summarize_output(command: str, output: str) -> str:
    """Summarize long terminal outputs using Gemini so JARVIS doesn't read raw text."""
    if len(output) < 150 and "\n" not in output:
        return output.strip()
    
    # We use Gemini to summarize the output to keep it clean.
    try:
        from google import genai
        import json
        
        # We need the API key to use genai
        api_key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "api_keys.json")
        api_key = None
        if os.path.exists(api_key_path):
            with open(api_key_path, "r") as f:
                keys = json.load(f)
                api_key = keys.get("gemini_api_key")
        
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")
            
        if api_key:
            client = genai.Client(api_key=api_key)
            prompt = f"Summarize the following terminal output for the command '{command}' in one or two short natural sentences suitable for a voice assistant to speak. Output ONLY the summary.\n\nOutput:\n{output[:4000]}"
            resp = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
            )
            return resp.text.strip()
    except Exception as e:
        print(f"Summarization error: {e}")
        return output[:200] + "... (truncated)"
    
    return output[:200] + "... (truncated)"

def execute_terminal_command(command: str, confirmed: bool = False, log_callback=None) -> str:
    """
    Executes a terminal command natively.
    Requires confirmed=True for risky commands (pkill, rm, etc).
    """
    if not is_safe_command(command):
        _log_command(command, "BLOCKED: Unsafe command", safe=False, confirmed=confirmed)
        return "I cannot run that command Sir, it appears unsafe."
    
    if "sudo " in command.lower():
        return "I cannot run commands as sudo automatically. Please perform this action manually."
    
    is_risky = any(x in command.lower() for x in ["pkill", "kill", "rm ", "quit", "close"])
    if is_risky and not confirmed:
        return f"CONFIRMATION_REQUIRED: Are you sure Sir? This will execute '{command}' and any unsaved work may be lost. Please confirm."

    try:
        print(f"\n[JARVIS-TERMINAL] Executing: {command}", flush=True)
        if log_callback:
            log_callback(f"[JARVIS-TERMINAL] Executing: {command}")
            
        import threading
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        raw_output_lines = []
        def read_output():
            for line in iter(process.stdout.readline, ''):
                print(f"[Terminal] {line}", end='', flush=True)
                if log_callback:
                    log_callback(f"[Terminal] {line.strip()}")
                raw_output_lines.append(line)
                
        reader_thread = threading.Thread(target=read_output)
        reader_thread.start()
        
        # Wait up to 10 seconds
        reader_thread.join(timeout=10)
        
        if reader_thread.is_alive():
            process.terminate()
            reader_thread.join()
            _log_command(command, "Timeout exceeded 10 seconds.", safe=True, confirmed=confirmed)
            return "The command took too long and was terminated Sir."
            
        process.wait()
        raw_output = "".join(raw_output_lines).strip()
        
        if not raw_output:
            summary = "Command executed successfully with no output."
        else:
            summary = _summarize_output(command, raw_output)
            
        _log_command(command, summary, safe=True, confirmed=confirmed)
        return f"Done. [SYSTEM NOTE: The user is watching the live terminal logs on their screen. Do NOT read the summary out loud. Just acknowledge that the command finished. Summary for your knowledge: {summary}]"

    except Exception as e:
        _log_command(command, f"Failed: {e}", safe=True, confirmed=confirmed)
        return f"The command failed to execute Sir: {e}"
    except Exception as e:
        _log_command(command, f"Error: {str(e)}", safe=True, confirmed=confirmed)
        return f"An error occurred while executing the command: {str(e)}"

def get_recent_commands(count: int = 5) -> str:
    """Reads the recent terminal commands executed by JARVIS."""
    try:
        if not os.path.exists(LOG_FILE):
            return "I haven't run any terminal commands recently Sir."
            
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
            
        if not logs:
            return "I haven't run any terminal commands recently Sir."
            
        recent = logs[-count:]
        summary = "Recently I ran the following commands:\n"
        for idx, log in enumerate(recent, 1):
            summary += f"{idx}. '{log['command']}' (Result: {log['output_summary']})\n"
            
        return summary
    except Exception as e:
        return f"Failed to read command logs: {e}"

# Tool registration for JARVIS AI router
terminal_control_tool = {
    "name": "execute_terminal",
    "description": "Execute a safe terminal command on the Mac (e.g. 'flutter --version', 'df -h', 'top', 'pkill -f App'). Risky commands require confirmed=True. If you need to check if something is installed, use 'which' or '--version'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "command": {
                "type": "STRING",
                "description": "The bash command to execute"
            },
            "confirmed": {
                "type": "BOOLEAN",
                "description": "Set to true ONLY if the user explicitly confirmed a risky command (like killing an app)."
            }
        },
        "required": ["command"]
    }
}

recent_commands_tool = {
    "name": "get_recent_commands",
    "description": "Read the last 5 terminal commands JARVIS executed. Use this when the user asks 'what commands have you run' or 'what did you just do'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": []
    }
}
