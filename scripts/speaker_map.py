from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import group_by_speaker as group
import transfer_subtitle_text as transfer

CURRENT_HEADERS = {
    "当前说话人", "当前", "现在的说话人", "现在的", "原说话人", "原", "旧说话人",
    "current", "current speaker", "old", "old speaker", "from", "source",
}
NEW_HEADERS = {
    "新说话人", "新的说话人", "新的", "新", "改后说话人", "改后", "重命名后",
    "new", "new speaker", "to", "target", "renamed",
}
LEADING_SPEAKER_RE = re.compile(r"^((?:\{[^{}]*\})*)(\[\s*([^\]]+?)\s*\])")
COMMENT_SPEAKER_RE = re.compile(r"(//\s*Speaker:\s*)([^\r\n]*)")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def write_ass(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        output_file.write("\r\n".join(lines) + "\r\n")


def write_report(path: Path | None, report: dict) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def is_header(row: list[str]) -> bool:
    if len(row) < 2:
        return False
    return row[0].strip().lower() in CURRENT_HEADERS and row[1].strip().lower() in NEW_HEADERS


def read_speaker_map(path: Path) -> tuple[dict[str, str], list[str]]:
    rows = [row for row in csv.reader(io.StringIO(read_text(path))) if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError(f"Speaker map CSV is empty: {path}")

    start = 1 if is_header(rows[0]) else 0
    mapping: dict[str, str] = {}
    blank_targets: list[str] = []

    for line_number, row in enumerate(rows[start:], start=start + 1):
        if len(row) < 2:
            raise ValueError(f"Speaker map CSV row {line_number} needs two columns")
        current = row[0].strip()
        new = row[1].strip()
        if not current:
            continue
        if not new:
            blank_targets.append(current)
            new = current
        if "," in new or "\r" in new or "\n" in new:
            raise ValueError(f"Speaker name cannot contain commas or line breaks at CSV row {line_number}: {new!r}")
        if current in mapping and mapping[current] != new:
            raise ValueError(f"Conflicting rows for speaker {current!r} in speaker map CSV")
        mapping[current] = new

    if not mapping:
        raise ValueError(f"No usable speaker rows found in {path}")
    return mapping, blank_targets


def replace_leading_speaker(text: str, mapping: dict[str, str]) -> str:
    match = LEADING_SPEAKER_RE.match(text)
    if not match:
        return text
    label = match.group(3).strip()
    new = mapping.get(label)
    if not new or new == label:
        return text
    return text[:match.start(2)] + f"[{new}]" + text[match.end(2):]


def replace_comment_speaker(text: str, old: str, new: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group(2).strip() == old:
            return match.group(1) + new
        return match.group(0)

    return COMMENT_SPEAKER_RE.sub(replace, text)


def apply_mapping(lines: list[str], mapping: dict[str, str], replace_text_prefix: bool) -> tuple[list[str], dict]:
    updated: list[str] = []
    before: Counter[str] = Counter()
    after: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    seen_old: set[str] = set()
    renamed_dialogues = 0
    renamed_comments = 0

    for line in lines:
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            if len(parts) == 10:
                old = parts[4]
                new = mapping.get(old, old)
                seen_old.add(old)
                before[old] += 1
                after[new] += 1
                if old != new:
                    renamed_dialogues += 1
                    pairs[(old, new)] += 1
                parts[4] = new
                if replace_text_prefix:
                    parts[9] = replace_leading_speaker(parts[9], mapping)
                updated.append(",".join(parts))
                continue

        if line.startswith("Comment:"):
            parts = line.split(",", 9)
            if len(parts) == 10:
                old = parts[4]
                new = mapping.get(old, old)
                seen_old.add(old)
                if old != new:
                    renamed_comments += 1
                parts[4] = new
                parts[9] = replace_comment_speaker(parts[9], old, new)
                updated.append(",".join(parts))
                continue

        updated.append(line)

    stats = {
        "dialogue_counts_before": dict(sorted(before.items())),
        "dialogue_counts_after": dict(sorted(after.items())),
        "renamed_dialogues": renamed_dialogues,
        "renamed_comments": renamed_comments,
        "pair_counts": [
            {"from": old, "to": new, "dialogues": count}
            for (old, new), count in sorted(pairs.items())
        ],
        "unused_map_rows": [name for name in mapping if name not in seen_old],
        "dialogues_before": sum(before.values()),
        "dialogues_after": sum(after.values()),
    }
    return updated, stats


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name).strip(" .")
    if not cleaned:
        cleaned = "speaker"
    cleaned = cleaned[:80].rstrip(" .")
    if cleaned.split(".", 1)[0].upper() in WINDOWS_RESERVED:
        cleaned = f"speaker_{cleaned}"
    return cleaned


def extract_preamble(lines: list[str]) -> list[str]:
    events_index = next((index for index, line in enumerate(lines) if line.strip() == "[Events]"), None)
    search_start = events_index + 1 if events_index is not None else 0
    first_event = next(
        (
            index for index in range(search_start, len(lines))
            if lines[index].startswith(("Dialogue:", "Comment:"))
        ),
        len(lines),
    )
    return list(lines[:first_event])


def collect_speaker_groups(lines: list[str]) -> tuple[list[str], dict[str, list[str]], set[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    order: list[str] = []
    has_dialogue: set[str] = set()

    for line in lines:
        if not line.startswith(("Dialogue:", "Comment:")):
            continue
        parts = line.split(",", 9)
        if len(parts) != 10:
            continue
        name = parts[4]
        if name not in groups:
            order.append(name)
        groups[name].append(line)
        if line.startswith("Dialogue:"):
            has_dialogue.add(name)
    return order, groups, has_dialogue


def split_ass(lines: list[str], output_dir: Path) -> dict[str, str]:
    preamble = extract_preamble(lines)
    order, groups, has_dialogue = collect_speaker_groups(lines)

    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for index, name in enumerate((name for name in order if name in has_dialogue), start=1):
        output_path = output_dir / f"{index:02d}_{safe_filename(name)}.ass"
        write_ass(output_path, preamble + groups[name])
        written[name] = str(output_path)
    return written


def dialogue_to_text(line: str) -> str:
    parts = line.split(",", 9)
    if len(parts) != 10:
        return ""
    text = transfer.clean_ass_text(parts[9]).replace("\n", " / ").strip()
    return f"[{parts[1]} --> {parts[2]}] {text}".rstrip()


def split_txt(lines: list[str], output_dir: Path) -> dict[str, str]:
    order, groups, has_dialogue = collect_speaker_groups(lines)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    for index, name in enumerate((name for name in order if name in has_dialogue), start=1):
        output_path = output_dir / f"{index:02d}_{safe_filename(name)}.txt"
        body = [f"# {name}", ""]
        for line in groups[name]:
            if line.startswith("Dialogue:"):
                text_line = dialogue_to_text(line)
                if text_line:
                    body.append(text_line)
        with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
            output_file.write("\r\n".join(body) + "\r\n")
        written[name] = str(output_path)
    return written


def cmd_export(args: argparse.Namespace) -> int:
    lines = read_text(args.input).splitlines()
    _, ordered, excluded = group.group_dialogues(lines, args.include_hidden, args.include_empty)
    names = list(dict.fromkeys(item["name"] for item in ordered))
    output_path = args.output or args.input.with_name(args.input.stem + ".speaker-map.csv")
    group.write_speaker_map_csv(names, output_path)

    report = {
        "input": str(args.input),
        "output": str(output_path),
        "speakers": names,
        "grouped_events": len(ordered),
        "excluded_events": len(excluded),
    }
    write_report(args.report, report)

    print(f"Speakers exported: {len(names)}")
    print(f"Output: {output_path}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    mapping, blank_targets = read_speaker_map(args.map)
    lines = read_text(args.input).splitlines()
    updated, stats = apply_mapping(lines, mapping, not args.no_replace_text_prefix)

    output_path = args.output or args.input.with_name(args.input.stem + ".renamed.ass")
    write_ass(output_path, updated)

    split_files: dict[str, str] = {}
    split_dir: Path | None = None
    if not args.no_split:
        split_dir = args.split_dir or output_path.with_name(output_path.stem + ".speakers")
        split_files = split_ass(updated, split_dir)

    verified = None
    if args.verify:
        verified = stats["dialogues_before"] == stats["dialogues_after"] and all(stats["dialogue_counts_after"])

    report = {
        "input": str(args.input),
        "speaker_map": str(args.map),
        "output": str(output_path),
        "split_dir": str(split_dir) if split_dir else None,
        "mapped_rows": len(mapping),
        "blank_target_rows": blank_targets,
        "replaced_text_prefix": not args.no_replace_text_prefix,
        "verify": "passed" if verified else ("failed" if verified is False else None),
        "split_files": split_files,
        **stats,
    }
    write_report(args.report, report)

    print(f"Mapped dialogue lines: {stats['renamed_dialogues']}")
    print(f"Unused map rows: {stats['unused_map_rows']}")
    if args.verify:
        print(f"Verify: {'passed' if verified else 'failed'}")
    if split_dir:
        print(f"Speaker files: {len(split_files)}")
        print(f"Split dir: {split_dir}")
    print(f"Output: {output_path}")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    lines = read_text(args.input).splitlines()
    output_dir = args.split_dir or args.input.with_name(args.input.stem + ".speakers")

    ass_files = split_ass(lines, output_dir) if args.format in ("ass", "both") else {}
    txt_files = split_txt(lines, output_dir) if args.format in ("txt", "both") else {}

    order, groups, _ = collect_speaker_groups(lines)
    counts = Counter({
        name: sum(1 for line in groups[name] if line.startswith("Dialogue:"))
        for name in order
    })
    counts = Counter({name: count for name, count in counts.items() if count})

    verified = None
    if args.verify:
        verified = bool(counts)
        for name, path in ass_files.items():
            check_lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
            names = {
                line.split(",", 9)[4]
                for line in check_lines
                if line.startswith("Dialogue:") and len(line.split(",", 9)) == 10
            }
            verified = verified and names == {name}
        for path in txt_files.values():
            verified = verified and Path(path).exists()

    report = {
        "input": str(args.input),
        "split_dir": str(output_dir),
        "format": args.format,
        "speakers": list(counts),
        "dialogue_counts": dict(sorted(counts.items())),
        "total_dialogues": sum(counts.values()),
        "ass_files": ass_files,
        "txt_files": txt_files,
        "verify": "passed" if verified else ("failed" if verified is False else None),
    }
    write_report(args.report, report)

    print(f"Speakers split: {len(counts)}")
    print(f"Dialogues split: {sum(counts.values())}")
    if args.verify:
        print(f"Verify: {'passed' if verified else 'failed'}")
    print(f"Split dir: {output_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Export an editable speaker map CSV, apply it to ASS, and split dialogues by speaker in ASS, TXT, or both.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export a two-column current/new speaker map CSV")
    export_parser.add_argument("--input", required=True, type=Path, help="Speaker-grouped ASS file")
    export_parser.add_argument("--output", type=Path, help="Output CSV path")
    export_parser.add_argument("--include-hidden", action="store_true", help="Include hidden events when collecting speakers")
    export_parser.add_argument("--include-empty", action="store_true", help="Include empty visible events when collecting speakers")
    export_parser.add_argument("--report", type=Path, help="Write a JSON report")
    export_parser.set_defaults(func=cmd_export)

    apply_parser = subparsers.add_parser("apply", help="Apply the edited speaker map CSV and split by speaker")
    apply_parser.add_argument("--input", required=True, type=Path, help="Speaker-grouped ASS file")
    apply_parser.add_argument("--map", required=True, type=Path, help="Edited speaker map CSV")
    apply_parser.add_argument("--output", type=Path, help="Output renamed ASS path")
    apply_parser.add_argument("--split-dir", type=Path, help="Directory for per-speaker ASS files")
    apply_parser.add_argument("--no-split", action="store_true", help="Only rename; do not write per-speaker files")
    apply_parser.add_argument("--no-replace-text-prefix", action="store_true", help="Keep leading [S#] speaker markers unchanged")
    apply_parser.add_argument("--verify", action="store_true", help="Verify dialogue count and speaker names after replacement")
    apply_parser.add_argument("--report", type=Path, help="Write a JSON report")
    apply_parser.set_defaults(func=cmd_apply)

    split_parser = subparsers.add_parser("split", help="Split an ASS by speaker without renaming")
    split_parser.add_argument("--input", required=True, type=Path, help="Grouped or renamed ASS file")
    split_parser.add_argument("--split-dir", type=Path, help="Directory for per-speaker files")
    split_parser.add_argument("--format", choices=("ass", "txt", "both"), default="ass", help="Output format; default: ass")
    split_parser.add_argument("--verify", action="store_true", help="Verify that each output file contains only its own speaker")
    split_parser.add_argument("--report", type=Path, help="Write a JSON report")
    split_parser.set_defaults(func=cmd_split)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
