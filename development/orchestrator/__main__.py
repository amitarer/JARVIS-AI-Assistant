import argparse
import json

from .permissions import STATE


def main():
    parser = argparse.ArgumentParser(description="Approved project-local development controller")
    parser.add_argument("command", choices=("run", "stop", "status", "preflight"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--resume-setup-run", help="Explicit bounded recovery of the initial quota-interrupted smoke test")
    args = parser.parse_args()
    if args.command == "run":
        if not args.once:
            parser.error("Only explicit --once mode is approved; continuous operation is disabled")
        from .runner import run_once
        return run_once(resume_run=args.resume_setup_run)
    if args.command == "preflight":
        from .preflight import main as preflight_main
        return preflight_main()
    if args.command == "stop":
        STATE.mkdir(exist_ok=True)
        (STATE / "STOP").write_text("User requested STOP\n", encoding="utf-8")
        print("STOP requested for the owned development cycle only.")
        return 0
    path = STATE / "status.json"
    print(path.read_text(encoding="utf-8") if path.exists() else json.dumps({"status": "not_started"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
