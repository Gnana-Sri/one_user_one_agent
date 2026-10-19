from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PACK = ROOT / "data_pack" / "one_user_one_agent_pack"
OUT = ROOT / "sample_run"

def run(command):
    print("\n> " + " ".join(str(x) for x in command), flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode

def main() -> int:
    commands = [
        [sys.executable, "-m", "src.agent", "--pack", str(PACK), "--out", str(OUT)],
        [sys.executable, str(PACK / "simulator" / "simulate_outcomes.py"), "--pack", str(PACK), "--actions", str(OUT / "actions.jsonl"), "--out", str(OUT / "sim")],
        [sys.executable, "-m", "src.evaluation", "--pack", str(PACK), "--out", str(OUT)],
    ]
    for command in commands:
        code = run(command)
        if code:
            return code
    print(f"\nFull replay and evaluation completed. Review: {OUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
