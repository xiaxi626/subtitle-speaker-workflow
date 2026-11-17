from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import transfer_subtitle_text as transfer

TRANSFER_SCRIPT = SCRIPT_DIR / "transfer_subtitle_text.py"
MINIMAL_DEFAULT_STYLE = "Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,30,30,20,1"
HIDE_TAG = r"{\hide}"


def read_text(path: Path) -> tuple[str, str]:
    return transfer.read_text(path)


def ass_time(milliseconds: int) -> str:
    centiseconds = milliseconds // 10
    hours, centiseconds = divmod(centiseconds, 360000)
    minutes, centiseconds = divmod(centiseconds, 6000)
    seconds, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"


def parse_style_names(lines: list[str]) -> set[str]:
    return {transfer.style_name(line) for line in lines if line.startswith("Style:")}


def choose_hidden_styles(lines: list[str], include: list[str], exclude: list[str]) -> list[str]:
    all_names = [transfer.style_name(line) for line in lines if line.startswith("Style:")]
    include_set = {name.strip() for value in include for name in value.split(",") if name.strip()}
    exclude_set = {name.strip() for value in exclude for name in value.split(",") if name.strip()}
    selected = []
    for name in all_names:
        if include_set:
            if name in include_set and name not in exclude_set:
                selected.append(name)
            continue
        if name in exclude_set:
            continue
        if re.search(r"(?i)(jp|ja|jap|orig|src)", name) or re.search(r"2$", name):
            continue
        selected.append(name)
    return selected


def load_hidden_events(path: Path, forced_format: str, hidden_styles: list[str], hidden_exclude_styles: list[str]) -> tuple[list[str], list[str], list[str]]:
    text, _ = read_text(path)
    suffix = path.suffix.lower()
    kind = forced_format
    if kind == "auto":
        if suffix in {".ass", ".ssa"} or text.lstrip().lower().startswith("[script info]"):
            kind = "ass"
        else:
            kind = "vtt" if text.lstrip().lower().startswith("webvtt") else "srt"

    if kind == "ass":
        lines = text.splitlines()
        selected_styles = choose_hidden_styles(lines, hidden_styles, hidden_exclude_styles)
        style_lines = [
            line for line in lines
            if line.startswith("Style:") and transfer.style_name(line) in selected_styles
        ]
        events = []
        for line in lines:
            if not line.startswith("Dialogue:"):
                continue
            parts = line.split(",", 9)
            if len(parts) == 10 and parts[3] in selected_styles and parts[9].strip():
                events.append(line)
        return lines, style_lines, events

    cues = transfer.parse_srt_or_vtt(text)
    events = []
    for cue in cues:
        cue_text = r"\N".join(cue["lines"])
        events.append(
            f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},Default,NTP,0,0,0,,{cue_text}"
        )
    return [], [MINIMAL_DEFAULT_STYLE], events


def parse_fallbacks(values: list[str]) -> list[tuple[int, int, str]]:
    result = []
    for value in values:
        match = re.fullmatch(r"\s*(.+?)-(.+?)=(\S+)\s*", value)
        if not match:
            raise ValueError(f"Invalid hidden fallback: {value!r}; expected START-END=SPEAKER")
        start_text, end_text, speaker = match.groups()
        result.append(
            (
                transfer.parse_time(start_text, False),
                transfer.parse_time(end_text, False),
                speaker.strip(),
            )
        )
    return result


def find_visible_event(hidden_event: dict, visible_events: list[dict], gap_tolerance: int) -> dict | None:
    best = None
    best_score = None
    for event in visible_events:
        overlap = min(hidden_event["end"], event["end"]) - max(hidden_event["start"], event["start"])
        gap = max(hidden_event["start"] - event["end"], event["start"] - hidden_event["end"], 0)
        if overlap <= 0 and gap > gap_tolerance:
            continue
        hidden_span = max(hidden_event["end"] - hidden_event["start"], 1)
        event_span = max(event["end"] - event["start"], 1)
        score = overlap / hidden_span + overlap / event_span - gap / 1000.0
        if best_score is None or score > best_score:
            best_score = score
            best = event
    return best


def run_visible_transfer(args, visible_path: Path, visible_report_path: Path) -> None:
    command = [
        sys.executable,
        str(TRANSFER_SCRIPT),
        "--content",
        str(args.content),
        "--timing",
        str(args.timing),
        "--output",
        str(visible_path),
        "--report",
        str(visible_report_path),
    ]
    for option in ("content_format", "speaker_label", "speaker_map", "blank_threshold", "gap_tolerance", "dedupe_gap"):
        value = getattr(args, option)
        if value is None or value == "auto":
            continue
        if isinstance(value, list):
            for item in value:
                command.extend([f"--{option.replace('_', '-')}", str(item)])
        else:
            command.extend([f"--{option.replace('_', '-')}", str(value)])
    if args.no_auto_speakers:
        command.append("--no-auto-speakers")
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(command, check=True, env=environment)


def insert_missing_styles(lines: list[str], style_lines: list[str]) -> list[str]:
    existing = parse_style_names(lines)
    missing = [line for line in style_lines if transfer.style_name(line) not in existing]
    if not missing:
        return lines
    events_index = next(index for index, line in enumerate(lines) if line.strip() == "[Events]")
    insert_index = events_index
    while insert_index > 0 and not lines[insert_index - 1].strip():
        insert_index -= 1
    result = list(lines)
    result[insert_index:insert_index] = missing
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Transfer source-language text into a speaker ASS and add hidden target-language lines with aligned speakers.")
    parser.add_argument("--content", required=True, type=Path, help="Accurate source-language text subtitle")
    parser.add_argument("--timing", required=True, type=Path, help="Source-language ASS with timing and speakers")
    parser.add_argument("--hidden-content", required=True, type=Path, help="Target-language subtitle to hide")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hidden-format", choices=("auto", "srt", "vtt", "ass"), default="auto")
    parser.add_argument("--hidden-styles", action="append", default=[], help="Styles to include from hidden ASS; comma-separated or repeatable")
    parser.add_argument("--hidden-exclude-styles", action="append", default=[], help="Styles to exclude from hidden ASS")
    parser.add_argument("--hidden-fallback", action="append", default=[], help="Manual speaker override: START-END=SPEAKER")
    parser.add_argument("--hidden-gap-tolerance", type=int, default=2000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--content-format", choices=("auto", "srt", "vtt", "ass"), default="auto")
    parser.add_argument("--speaker-label", action="append", default=[])
    parser.add_argument("--speaker-map", action="append", default=[])
    parser.add_argument("--no-auto-speakers", action="store_true")
    parser.add_argument("--blank-threshold", type=int, default=15)
    parser.add_argument("--gap-tolerance", type=int, default=2000)
    parser.add_argument("--dedupe-gap", type=int, default=200)
    args = parser.parse_args()

    output_path = args.output or args.timing.with_name(args.timing.stem + ".bilingual_hidden.ass")
    fallbacks = parse_fallbacks(args.hidden_fallback)

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        visible_path = temporary / "visible.ass"
        visible_report_path = temporary / "visible_report.json"
        run_visible_transfer(args, visible_path, visible_report_path)

        visible_text, _ = read_text(visible_path)
        visible_lines = visible_text.splitlines()
        _, visible_events = transfer.parse_ass_events(visible_text)

        hidden_source_lines, hidden_style_lines, hidden_event_lines = load_hidden_events(
            args.hidden_content, args.hidden_format, args.hidden_styles, args.hidden_exclude_styles
        )
        _ = hidden_source_lines

        output_lines = insert_missing_styles(visible_lines, hidden_style_lines)
        output_lines.append(
            "Comment: 0,0:00:00.00,0:00:00.00,Default,NTP,0,0,0,,// hidden target-language subtitle with aligned speakers"
        )
        speaker_counts = Counter()
        fallback_uses = []
        unmapped = []

        for line in hidden_event_lines:
            parts = line.split(",", 9)
            if len(parts) != 10:
                continue
            hidden_event = {
                "start": transfer.parse_time(parts[1], False),
                "end": transfer.parse_time(parts[2], False),
            }
            best = find_visible_event(hidden_event, visible_events, args.hidden_gap_tolerance)
            if best is None:
                for start, end, speaker in fallbacks:
                    if hidden_event["start"] >= start and hidden_event["end"] <= end:
                        candidates = [event for event in visible_events if event["name"] == speaker]
                        if candidates:
                            best = min(
                                candidates,
                                key=lambda event: abs(event["start"] - hidden_event["start"]),
                            )
                            fallback_uses.append({"speaker": speaker, "time": parts[1]})
                            break
            if best is None:
                unmapped.append({"line": parts[1], "style": parts[3], "text": parts[9]})
                parts[9] = HIDE_TAG + parts[9].strip()
            else:
                original_text = parts[9].strip()
                if original_text.startswith(HIDE_TAG):
                    original_text = original_text[len(HIDE_TAG) :].strip()
                parts[4] = best["name"]
                parts[9] = HIDE_TAG + transfer.text_prefix(best["text"]) + original_text
                speaker_counts[best["name"]] += 1
            output_lines.append(",".join(parts))

        if not args.dry_run:
            with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
                output_file.write("\r\n".join(output_lines) + "\r\n")

    report = {
        "content": str(args.content),
        "timing": str(args.timing),
        "hidden_content": str(args.hidden_content),
        "output": str(output_path),
        "visible_dialogues": len(visible_events),
        "hidden_dialogues": len(hidden_event_lines),
        "mapped_hidden_dialogues": sum(speaker_counts.values()),
        "unmapped_hidden_dialogues": unmapped,
        "fallback_uses": fallback_uses,
        "hidden_speaker_distribution": dict(sorted(speaker_counts.items())),
        "hidden_styles_used": [transfer.style_name(line) for line in hidden_style_lines],
    }
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Visible dialogues: {len(visible_events)}")
    print(f"Hidden dialogues: {len(hidden_event_lines)}; mapped: {sum(speaker_counts.values())}")
    print(f"Manual fallback uses: {len(fallback_uses)}")
    print(f"Unmapped hidden dialogues: {len(unmapped)}")
    print(f"Output: {output_path}" if not args.dry_run else "Dry run: no output written")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
