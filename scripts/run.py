#!/usr/bin/env python3
"""
OpenEvidence Skill Runner

Wrapper script that:
1. Creates virtual environment if needed
2. Installs dependencies
3. Runs the requested script

Usage:
    python run.py auth_manager.py setup
    python run.py ask_question.py --question "..."
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
VENV_DIR = SKILL_DIR / ".venv"
REQUIREMENTS_FILE = SKILL_DIR / "requirements.txt"
SCRIPTS_DIR = SKILL_DIR / "scripts"


def get_venv_python() -> Path:
    """Get path to Python in virtual environment."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def get_venv_pip() -> Path:
    """Get path to pip in virtual environment."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def create_venv() -> bool:
    """Create virtual environment if it doesn't exist."""
    if VENV_DIR.exists():
        return True

    print("Creating virtual environment...")
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
            check=True,
            capture_output=True,
        )
        print("  Virtual environment created.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Failed to create venv: {e}")
        return False


def install_dependencies() -> bool:
    """Install dependencies from requirements.txt."""
    if not REQUIREMENTS_FILE.exists():
        print("  No requirements.txt found, skipping dependency install.")
        return True

    # Check if patchright is already installed
    pip = get_venv_pip()
    try:
        result = subprocess.run(
            [str(pip), "show", "patchright"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True  # Already installed
    except subprocess.SubprocessError:
        pass

    print("Installing dependencies...")
    try:
        subprocess.run(
            [str(pip), "install", "-r", str(REQUIREMENTS_FILE)],
            check=True,
            capture_output=True,
        )
        print("  Dependencies installed.")

        # Install Chromium for patchright
        print("Installing Chromium browser...")
        python = get_venv_python()
        subprocess.run(
            [str(python), "-m", "patchright", "install", "chromium"],
            check=True,
            capture_output=True,
        )
        print("  Chromium installed.")

        return True
    except subprocess.CalledProcessError as e:
        print(f"  Failed to install dependencies: {e}")
        if e.stderr:
            print(f"  Error: {e.stderr.decode()}")
        return False


def run_script(script_name: str, args: list[str]) -> int:
    """
    Run a script in the virtual environment.

    Args:
        script_name: Name of script to run (e.g., "auth_manager.py")
        args: Arguments to pass to the script

    Returns:
        Exit code from the script
    """
    script_path = SCRIPTS_DIR / script_name

    if not script_path.exists():
        print(f"Script not found: {script_name}")
        print(f"Available scripts:")
        for f in SCRIPTS_DIR.glob("*.py"):
            if f.name not in ("__init__.py", "run.py"):
                print(f"  - {f.name}")
        return 1

    python = get_venv_python()

    # Run the script
    result = subprocess.run(
        [str(python), str(script_path)] + args,
        cwd=str(SCRIPTS_DIR),
    )

    return result.returncode


def main():
    if len(sys.argv) < 2:
        print("Usage: python run.py <script.py> [args...]")
        print()
        print("Available scripts:")
        for f in SCRIPTS_DIR.glob("*.py"):
            if f.name not in ("__init__.py", "run.py"):
                print(f"  - {f.name}")
        print()
        print("Examples:")
        print("  python run.py auth_manager.py setup")
        print("  python run.py auth_manager.py status")
        print('  python run.py ask_question.py --question "..."')
        sys.exit(1)

    script_name = sys.argv[1]
    script_args = sys.argv[2:]

    # Setup environment
    if not create_venv():
        sys.exit(1)

    if not install_dependencies():
        sys.exit(1)

    # Run the script
    exit_code = run_script(script_name, script_args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
