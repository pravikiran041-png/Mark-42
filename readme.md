# JARVIS AI System

A highly capable, Iron Man-inspired AI assistant featuring a holographic UI and powerful local automation capabilities.

## Features

- **Holographic UI**: A sleek, translucent, draggable overlay built with PyQt6, featuring a responsive command input and real-time activity logging.
- **Floating HUD Orb**: Integrated Next.js and Three.js 3D animated orb interface that reacts to voice and input.
- **Deep System Integration**: Capable of automating web browser tasks, local device controls, searching files, and managing desktop environment.
- **Memory & Intelligence**: Advanced vector-based memory for recalling past events and a deep intelligence scraping system for fetching context.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set up environment variables (if required for LLMs).
3. Run the system:
   ```bash
   python3 main.py
   ```

## Structure

- `ui.py`: Core PyQt6 desktop overlay interface.
- `main.py`: Main backend entry point for routing logic.
- `actions/`: Automation scripts and capability modules.
- `memory/`: Vector DB and context managers.
- `orb/`: Next.js 3D Holographic HUD.

## Disclaimer

This project is intended for personal use. It interacts directly with your system and desktop, so please review action scripts before executing potentially destructive automated commands.
