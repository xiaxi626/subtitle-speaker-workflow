from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def ass_ms(value: str) -> int:
    match = re.fullmatch(r"(\d+):(\d+):(\d+)\.(\d+)", value.strip())
    if not match:
        raise ValueError(f"Invalid ASS time: {value!r}")
    hours, minutes, seconds, centiseconds = map(int, match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + centiseconds * 10


def parse_dialogue(line: str) -> dict | None:
    if not line.startswith("Dialogue:"):
        return None
    parts = line.split(",", 9)
    if len(parts) != 10:
        return None
    return {
        "line": line,
        "start": ass_ms(parts[1]),
        "end": ass_ms(parts[2]),
        "style": parts[3],
        "name": parts[4],
        "text": parts[9],
        "layer": int(parts[0].split(":", 1)[1].strip()) if parts[0].split(":", 1)[1].strip().lstrip("-").isdigit() else 0,
    }


def write_speaker_map_csv(names: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(["当前说话人", "新说话人"])
        for name in names:
            writer.writerow([name, name])


def group_dialogues(lines: list[str], include_hidden: bool, include_empty: bool) -> tuple[list[str], list[dict], list[dict]]:
    events_index = next((index for index, line in enumerate(lines) if line.strip() == "[Events]"), len(lines))
    header = lines[:events_index]
    excluded_hidden = []
    excluded_empty = []
    dialogues = []

    for line in lines[events_index:]:
        parsed = parse_dialogue(line)
        if parsed is None:
            continue
        if not include_hidden and parsed["text"].startswith(r"{\hide}"):
            excluded_hidden.append(parsed)
            continue
        plain = re.sub(r"^(?:\{[^{}]*\})*", "", parsed["text"]).strip()
        if not include_empty and not plain:
            excluded_empty.append(parsed)
            continue
        dialogues.append(parsed)

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in dialogues:
        groups[item["name"]].append(item)

    group_order = sorted(groups, key=lambda name: min(item["start"] for item in groups[name]))
    ordered = []
    for name in group_order:
        items = sorted(groups[name], key=lambda item: (item["start"], item["end"], item["layer"]))
        ordered.extend(items)
    return header, ordered, excluded_hidden + excluded_empty


def build_output(header: list[str], ordered: list[dict]) -> list[str]:
    output = list(header)
    if not any(line.strip() == "[Events]" for line in output):
        output.append("[Events]")
    output.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

    current_name = None
    for item in ordered:
        if item["name"] != current_name:
            output.append(
                f"Comment: 0,0:00:00.00,0:00:00.00,Default,{item['name']},0,0,0,,// Speaker: {item['name']}"
            )
            current_name = item["name"]
        output.append(item["line"])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Reorder visible ASS dialogue events by speaker and timestamp, excluding hidden target-language events.")
    parser.add_argument("--input", required=True, type=Path, help="Generated ASS file to reorganize")
    parser.add_argument("--output", type=Path, help="Output speaker-grouped ASS path")
    parser.add_argument("--include-hidden", action="store_true", help="Keep hidden target-language events instead of excluding them")
    parser.add_argument("--include-empty", action="store_true", help="Keep visible events whose text is empty after tags")
    parser.add_argument("--speaker-map-csv", type=Path, help="Write a two-column current/new speaker map CSV")
    parser.add_argument("--report", type=Path, help="Write a JSON report")
    parser.add_argument("--verify", action="store_true", help="Verify that output dialogue content matches input visible content after reordering")
    args = parser.parse_args()

    output_path = args.output or args.input.with_name(args.input.stem + ".speaker-grouped.ass")
    lines = read_text(args.input).splitlines()
    header, ordered, excluded = group_dialogues(lines, args.include_hidden, args.include_empty)
    output_lines = build_output(header, ordered)

    with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
        output_file.write("\r\n".join(output_lines) + "\r\n")

    speaker_order = list(dict.fromkeys(item["name"] for item in ordered))
    if args.speaker_map_csv:
        write_speaker_map_csv(speaker_order, args.speaker_map_csv)

    speaker_counts = Counter(item["name"] for item in ordered)
    report = {
        "input": str(args.input),
        "output": str(output_path),
        "speaker_map_csv": str(args.speaker_map_csv) if args.speaker_map_csv else None,
        "visible_grouped_events": len(ordered),
        "excluded_events": len(excluded),
        "speaker_distribution": dict(sorted(speaker_counts.items())),
    }
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Grouped events: {len(ordered)}")
    print(f"Excluded events: {len(excluded)}")
    print(f"Speaker distribution: {dict(sorted(speaker_counts.items()))}")
    if args.speaker_map_csv:
        print(f"Speaker map CSV: {args.speaker_map_csv}")
    if args.verify:
        input_visible = Counter(item["line"] for item in ordered)
        output_dialogue = Counter(line for line in output_lines if line.startswith("Dialogue:"))
        verified = input_visible == output_dialogue
        report["verify"] = "passed" if verified else "failed"
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Verify: {'passed' if verified else 'failed'}")
    print(f"Output: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
