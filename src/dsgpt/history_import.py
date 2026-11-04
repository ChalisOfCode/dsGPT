"""Local operator CLI. Never uploads the archive or accepts a remote file path."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from .history import History
from .history_archive import ArchiveError, preview, read_archive
from .storage import InstanceLock, Store


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local dsGPT ChatGPT history import")
    parser.add_argument("command", choices=["preview", "apply", "list", "remove", "remember"])
    parser.add_argument("--file", type=Path, help="Chosen ChatGPT export ZIP or conversation JSON")
    parser.add_argument("--data-dir", type=Path, help="Existing dsGPT backend data directory")
    parser.add_argument("--sha256", help="Exact archive SHA256 shown by preview")
    parser.add_argument("--request-id", type=UUID, help="Keep the same UUID for retries")
    parser.add_argument("--conversation", action="append", default=[], help="Select source ID")
    parser.add_argument("--id", type=UUID, help="Local chat ID for remove; message ID for remember")
    parser.add_argument("--title", help="Title for an explicitly saved memory")
    parser.add_argument("--task-id", type=UUID, help="Save memory in this existing Work project")
    parser.add_argument("--confirm-remove", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args(argv)
    lock = None
    supervisor_lock = None
    try:
        if args.command in {"preview", "apply"}:
            if not args.file:
                parser.error("preview/apply requires --file")
            archive = read_archive(args.file)
            if args.command == "preview":
                print(json.dumps(preview(archive, args.conversation), ensure_ascii=True, indent=2))
                return 0
            if not args.sha256 or not args.request_id:
                parser.error("apply requires preview --sha256 and a stable --request-id UUID")
        if not args.data_dir or not (args.data_dir / "dsgpt.db").is_file():
            parser.error("Choose the existing backend --data-dir; no empty database is created")
        if args.offset < 0:
            parser.error("offset must be nonnegative")
        supervisor_lock = InstanceLock(args.data_dir, "managed-supervisor.lock")
        supervisor_lock.acquire()
        # Store validates schema/ownership and refuses migrations while a backend runs.
        store = Store(args.data_dir)
        lock = InstanceLock(args.data_dir)
        lock.acquire()
        history = History(store)
        if args.command == "apply":
            result = history.apply(archive, str(args.request_id), args.sha256, args.conversation)
        elif args.command == "list":
            result = history.list(offset=args.offset)
        elif args.command == "remove":
            if not args.id or not args.confirm_remove:
                parser.error("remove requires --id and --confirm-remove; all source versions clear")
            result = history.remove(str(args.id))
        else:
            if not args.id or not args.request_id or not args.title or len(args.title) > 200:
                parser.error("remember requires --id, --request-id and --title (1–200 characters)")
            result = history.promote(
                str(args.id),
                str(args.request_id),
                args.title,
                str(args.task_id) if args.task_id else None,
            )
            # Do not print the copied private message to the terminal.
            result = {k: result[k] for k in ("id", "task_id", "revision", "source")}
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except HTTPException as exc:
        print(json.dumps({"error": exc.detail, "status": exc.status_code}), file=sys.stderr)
        return 1
    except (ArchiveError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print(json.dumps({"error": "Local file/database operation failed"}), file=sys.stderr)
        return 1
    finally:
        if lock:
            lock.release()
        if supervisor_lock:
            supervisor_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
