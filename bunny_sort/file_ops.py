from __future__ import annotations

import shutil
from pathlib import Path

from .models import ActionRecord, ConflictStrategy, RuleAction


def resolve_destination(source_path: str, target_dir: str, strategy: ConflictStrategy) -> Path | None:
    source = Path(source_path)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    dest = target / source.name
    if not dest.exists() or strategy == ConflictStrategy.OVERWRITE:
        return dest
    if strategy == ConflictStrategy.SKIP_EXISTING:
        return None
    if strategy == ConflictStrategy.ASK_USER:
        return dest

    stem = source.stem
    suffix = source.suffix
    counter = 1
    while True:
        candidate = target / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def execute_file_action(
    source_path: str,
    target_dir: str | None,
    action: RuleAction,
    strategy: ConflictStrategy,
) -> str | None:
    if action == RuleAction.SKIP:
        return None
    if not target_dir:
        raise ValueError("Copy/Move rules require a target folder.")

    dest = resolve_destination(source_path, target_dir, strategy)
    if dest is None:
        return None

    source = Path(source_path)
    if action == RuleAction.COPY:
        shutil.copy2(source, dest)
    elif action == RuleAction.MOVE:
        shutil.move(str(source), str(dest))
    return str(dest)


def undo_file_action(record: ActionRecord) -> None:
    if record.action == RuleAction.COPY and record.dest_path:
        copied = Path(record.dest_path)
        if copied.exists():
            copied.unlink()
    elif record.action == RuleAction.MOVE and record.dest_path:
        moved_to = Path(record.dest_path)
        original = Path(record.source_path)
        original.parent.mkdir(parents=True, exist_ok=True)
        if moved_to.exists() and not original.exists():
            shutil.move(str(moved_to), str(original))
