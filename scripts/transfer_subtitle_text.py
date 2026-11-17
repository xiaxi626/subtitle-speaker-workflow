from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path


TAG_RE = re.compile(r"\{[^{}]*\}")
LABEL_PATTERNS = (
    re.compile(r"^（([^）]+)）\s*(.*)$"),
    re.compile(r"^\[([^\]]+)\]\s*(.*)$"),
    re.compile(r"^【([^】]+)】\s*(.*)$"),
)
PUNCTUATION_RE = re.compile(r"[\s、。，,.…・！？!?「」『』“”\"'’‘（）()\[\]【】―—\-~～]")
RUBY_RE = re.compile(r"[（(][^）)]*[）)]")


def read_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932", "gb18030"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def parse_time(value: str, srt_style: bool) -> int:
    value = value.strip().split()[0]
    if srt_style:
        match = re.fullmatch(r"(\d+):(\d+):(\d+)[,.](\d+)", value)
        if not match:
            raise ValueError(f"Invalid subtitle time: {value!r}")
        hours, minutes, seconds, fraction = map(int, match.groups())
        return ((hours * 60 + minutes) * 60 + seconds) * 1000 + fraction
    match = re.fullmatch(r"(\d+):(\d+):(\d+)\.(\d+)", value)
    if not match:
        raise ValueError(f"Invalid ASS time: {value!r}")
    hours, minutes, seconds, fraction = map(int, match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + fraction * 10


def parse_srt_or_vtt(text: str) -> list[dict]:
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timestamp_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timestamp_index is None:
            continue
        start_text, end_text = [part.strip() for part in lines[timestamp_index].split("-->")]
        cues.append(
            {
                "number": len(cues) + 1,
                "start": parse_time(start_text, True),
                "end": parse_time(end_text, True),
                "lines": lines[timestamp_index + 1 :],
            }
        )
    return cues


def clean_ass_text(text: str) -> str:
    text = TAG_RE.sub("", text)
    return text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")


def parse_ass_cues(text: str) -> list[dict]:
    cues = []
    for line in text.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) != 10:
            continue
        content_lines = [piece.strip() for piece in clean_ass_text(parts[9]).splitlines() if piece.strip()]
        cues.append(
            {
                "number": len(cues) + 1,
                "start": parse_time(parts[1], False),
                "end": parse_time(parts[2], False),
                "lines": content_lines,
            }
        )
    return cues


def load_content_cues(path: Path, forced_format: str) -> tuple[list[dict], str]:
    text, encoding = read_text(path)
    suffix = path.suffix.lower()
    if forced_format != "auto":
        kind = forced_format
    elif suffix in {".srt"}:
        kind = "srt"
    elif suffix in {".vtt"}:
        kind = "vtt"
    elif suffix in {".ass", ".ssa"}:
        kind = "ass"
    elif text.lstrip().lower().startswith("webvtt"):
        kind = "vtt"
    elif "Dialogue:" in text:
        kind = "ass"
    else:
        kind = "srt"
    if kind == "ass":
        return parse_ass_cues(text), encoding
    return parse_srt_or_vtt(text), encoding


def parse_ass_events(text: str) -> tuple[list[str], list[dict]]:
    lines = text.splitlines()
    events = []
    for line_index, line in enumerate(lines):
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) != 10:
            raise ValueError(f"Invalid ASS Dialogue at line {line_index + 1}")
        events.append(
            {
                "line_index": line_index,
                "start": parse_time(parts[1], False),
                "end": parse_time(parts[2], False),
                "name": parts[4],
                "style": parts[3],
                "text": parts[9],
            }
        )
    return lines, events


def detect_label(line: str) -> tuple[str | None, str]:
    for pattern in LABEL_PATTERNS:
        match = pattern.match(line.strip())
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None, line.strip()


def canonical_speaker(label: str) -> str:
    return RUBY_RE.sub("", label).strip()


def collect_speaker_labels(cues: list[dict], explicit: set[str]) -> set[str]:
    labels = set(explicit)
    for cue in cues:
        for index, line in enumerate(cue["lines"]):
            label, rest = detect_label(line)
            if label and rest:
                labels.add(canonical_speaker(label))
            elif label and index + 1 < len(cue["lines"]):
                next_label, next_rest = detect_label(cue["lines"][index + 1])
                if next_rest and not next_label:
                    labels.add(canonical_speaker(label))
    return labels


def split_cues_into_segments(cues: list[dict], speaker_labels: set[str]) -> list[dict]:
    segments = []

    def finish(current: dict | None) -> None:
        if not current:
            return
        text = " ".join(part for part in current["parts"] if part).strip()
        if not text:
            return
        current["id"] = len(segments) + 1
        current["text"] = text
        segments.append(current)

    for cue in cues:
        current = None
        for raw_line in cue["lines"]:
            label, rest = detect_label(raw_line)
            if label and canonical_speaker(label) in speaker_labels:
                finish(current)
                current = {
                    "cue": cue["number"],
                    "start": cue["start"],
                    "end": cue["end"],
                    "speaker": canonical_speaker(label),
                    "parts": [rest] if rest else [],
                }
            else:
                if current is None:
                    current = {
                        "cue": cue["number"],
                        "start": cue["start"],
                        "end": cue["end"],
                        "speaker": None,
                        "parts": [],
                    }
                current["parts"].append(raw_line.strip())
        finish(current)
    return segments


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("嗯", "ん")
    return PUNCTUATION_RE.sub("", text)


def style_name(line: str) -> str:
    return line.split(":", 1)[1].split(",", 1)[0].strip()


def text_prefix(text: str) -> str:
    match = re.match(r"^((?:\{[^{}]*\})+(?:\[[^\]]+\])?(?:\{[^{}]*\})*\s*)", text)
    if match:
        return match.group(1)
    tag_only = re.match(r"^((?:\{[^{}]*\})+\s*)", text)
    return tag_only.group(1) if tag_only else ""


def plain_event_text(text: str) -> str:
    return text[len(text_prefix(text)) :].strip()


def speaker_score(segment: dict, event: dict, speaker_map: dict[str, tuple[str, ...]]) -> float:
    speaker = segment.get("speaker")
    expected = speaker_map.get(event["name"])
    if not speaker or not expected:
        return 0.0
    return 2.0 if any(label in speaker or speaker in label for label in expected) else -1.5


def score_match(
    segment: dict,
    event: dict,
    speaker_map: dict[str, tuple[str, ...]],
    allow_gap: bool,
    gap_tolerance: int,
) -> dict | None:
    overlap = min(segment["end"], event["end"]) - max(segment["start"], event["start"])
    gap = max(segment["start"] - event["end"], event["start"] - segment["end"], 0)
    if overlap <= 0 and (not allow_gap or gap > gap_tolerance):
        return None
    segment_cover = max(overlap, 0) / max(segment["end"] - segment["start"], 1)
    event_cover = max(overlap, 0) / max(event["end"] - event["start"], 1)
    segment_text = normalize_text(segment["text"])
    event_text = normalize_text(plain_event_text(event["text"]))
    similarity = SequenceMatcher(None, segment_text, event_text).ratio() if segment_text and event_text else 0.0
    gap_penalty = 0.0 if overlap > 0 else gap / 1000.0
    score = segment_cover + event_cover + 3.0 * similarity + speaker_score(segment, event, speaker_map) - gap_penalty
    return {
        "score": score,
        "overlap": max(overlap, 0),
        "gap": gap,
        "similarity": similarity,
        "segment_cover": segment_cover,
        "event_cover": event_cover,
    }


def assign_segments(
    segments: list[dict],
    events: list[dict],
    speaker_map: dict[str, tuple[str, ...]],
    gap_tolerance: int,
) -> tuple[dict[int, list[dict]], list[dict], dict[int, dict]]:
    assigned: dict[int, list[dict]] = defaultdict(list)
    unassigned = []
    location: dict[int, int] = {}
    scores: dict[int, dict] = {}

    for segment in segments:
        best_event = None
        best_match = None
        for event in events:
            match = score_match(segment, event, speaker_map, False, gap_tolerance)
            if match and (best_match is None or match["score"] > best_match["score"]):
                best_event, best_match = event, match
        if best_event is None:
            unassigned.append(segment)
            continue
        assigned[best_event["line_index"]].append(segment)
        location[segment["id"]] = best_event["line_index"]
        scores[segment["id"]] = best_match

    for event in events:
        if assigned.get(event["line_index"]):
            continue
        candidates = []
        for segment in segments:
            match = score_match(segment, event, speaker_map, True, gap_tolerance)
            if not match:
                continue
            current_line = location.get(segment["id"])
            if current_line is None:
                candidates.append((match["score"], segment, match))
            elif len(assigned[current_line]) > 1:
                old_score = scores[segment["id"]]["score"]
                if match["score"] >= old_score - 0.25 or speaker_score(segment, event, speaker_map) > 0:
                    candidates.append((match["score"], segment, match))
        if not candidates:
            continue
        _, segment, match = max(candidates, key=lambda item: item[0])
        old_line = location.get(segment["id"])
        if old_line is not None:
            assigned[old_line] = [item for item in assigned[old_line] if item["id"] != segment["id"]]
        else:
            unassigned = [item for item in unassigned if item["id"] != segment["id"]]
        assigned[event["line_index"]].append(segment)
        location[segment["id"]] = event["line_index"]
        scores[segment["id"]] = match

    return assigned, unassigned, scores


def learn_speaker_map(
    segments: list[dict],
    events: list[dict],
    assigned: dict[int, list[dict]],
    scores: dict[int, dict],
    gap_tolerance: int,
) -> dict[str, tuple[str, ...]]:
    votes: dict[str, Counter] = defaultdict(Counter)
    event_by_line = {event["line_index"]: event for event in events}
    for segment in segments:
        if not segment.get("speaker"):
            continue
        match = scores.get(segment["id"])
        line_index = next((line for line, items in assigned.items() if any(item["id"] == segment["id"] for item in items)), None)
        if not match or line_index is None:
            continue
        confident = match["similarity"] >= 0.25 or (match["segment_cover"] >= 0.8 and match["event_cover"] >= 0.6)
        if confident:
            votes[event_by_line[line_index]["name"]][segment["speaker"]] += 1

    learned = {}
    for name, counter in votes.items():
        total = sum(counter.values())
        label, count = counter.most_common(1)[0]
        if count >= (total + 1) // 2:
            learned[name] = (label,)
    return learned


def deduplicate_text(matches: list[dict], dedupe_gap: int) -> str:
    ordered = sorted(matches, key=lambda item: (item["start"], item["id"]))
    selected = []
    chain_end: dict[str, int] = {}
    for segment in ordered:
        key = normalize_text(segment["text"])
        previous_end = chain_end.get(key)
        if previous_end is not None and segment["start"] <= previous_end + dedupe_gap:
            chain_end[key] = max(previous_end, segment["end"])
            continue
        selected.append(segment)
        chain_end[key] = segment["end"]
    return " ".join(segment["text"] for segment in selected)


def merge_lines(
    original_lines: list[str],
    events: list[dict],
    assigned: dict[int, list[dict]],
    blank_threshold: int,
    dedupe_gap: int,
) -> tuple[list[str], int, list[int], list[int]]:
    lines = list(original_lines)
    long_event_names = {event["name"] for event in events if event["end"] - event["start"] >= 45000}
    changed = 0
    blanked = []
    unchanged = []
    for event in events:
        matches = assigned.get(event["line_index"], [])
        prefix = text_prefix(event["text"])
        parts = lines[event["line_index"]].split(",", 9)
        if not matches:
            plain = plain_event_text(event["text"])
            if event["name"] not in long_event_names and 0 < len(normalize_text(plain)) <= blank_threshold:
                parts[9] = prefix.rstrip()
                blanked.append(event["line_index"] + 1)
                changed += 1
            else:
                unchanged.append(event["line_index"] + 1)
        else:
            parts[9] = prefix + deduplicate_text(matches, dedupe_gap)
            changed += 1
        lines[event["line_index"]] = ",".join(parts)
    return lines, changed, blanked, unchanged


def validate_structure(original_lines: list[str], output_lines: list[str], events: list[dict]) -> None:
    if len(original_lines) != len(output_lines):
        raise ValueError("Output line count differs from target subtitle")
    for event in events:
        index = event["line_index"]
        before = original_lines[index].split(",", 9)
        after = output_lines[index].split(",", 9)
        if before[:9] != after[:9]:
            raise ValueError(f"Structure changed at line {index + 1}")
    for index, (before, after) in enumerate(zip(original_lines, output_lines)):
        if index not in {event["line_index"] for event in events} and before != after:
            raise ValueError(f"Non-dialogue line changed at line {index + 1}")


def parse_speaker_map(values: list[str]) -> dict[str, tuple[str, ...]]:
    result = {}
    for value in values:
        for item in value.split(","):
            if "=" not in item:
                raise ValueError(f"Invalid speaker map: {item!r}; expected NAME=LABEL")
            name, label = item.split("=", 1)
            result[name.strip()] = (canonical_speaker(label.strip()),)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace target subtitle text with reference subtitle text while preserving target timing and speakers.")
    parser.add_argument("--content", required=True, type=Path, help="Subtitle file containing the correct text")
    parser.add_argument("--timing", required=True, type=Path, help="Target ASS subtitle containing timing, styles, and speakers")
    parser.add_argument("--output", type=Path, help="Output ASS path")
    parser.add_argument("--content-format", choices=("auto", "srt", "vtt", "ass"), default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--speaker-label", action="append", default=[], help="Force a parenthetical label to be treated as a speaker; repeatable")
    parser.add_argument("--speaker-map", action="append", default=[], help="Map target speaker to reference label, e.g. S4=一弥; repeatable")
    parser.add_argument("--no-auto-speakers", action="store_true")
    parser.add_argument("--blank-threshold", type=int, default=15)
    parser.add_argument("--gap-tolerance", type=int, default=2000)
    parser.add_argument("--dedupe-gap", type=int, default=200)
    parser.add_argument("--report", type=Path, help="Write a JSON report")
    args = parser.parse_args()

    content_cues, content_encoding = load_content_cues(args.content, args.content_format)
    target_text, target_encoding = read_text(args.timing)
    original_lines, events = parse_ass_events(target_text)

    explicit_labels = {canonical_speaker(value) for value in args.speaker_label}
    speaker_labels = collect_speaker_labels(content_cues, explicit_labels) if not args.no_auto_speakers else explicit_labels
    segments = split_cues_into_segments(content_cues, speaker_labels)
    explicit_map = parse_speaker_map(args.speaker_map)

    first_assigned, _, first_scores = assign_segments(segments, events, explicit_map, args.gap_tolerance)
    learned_map = learn_speaker_map(segments, events, first_assigned, first_scores, args.gap_tolerance)
    speaker_map = {**learned_map, **explicit_map}
    assigned, unassigned, _ = assign_segments(segments, events, speaker_map, args.gap_tolerance)
    output_lines, changed, blanked, unchanged = merge_lines(original_lines, events, assigned, args.blank_threshold, args.dedupe_gap)
    validate_structure(original_lines, output_lines, events)

    output_path = args.output or args.timing.with_name(args.timing.stem + ".text-restored.ass")
    report = {
        "content": str(args.content),
        "timing": str(args.timing),
        "output": str(output_path),
        "content_encoding": content_encoding,
        "target_encoding": target_encoding,
        "content_cues": len(content_cues),
        "content_segments": len(segments),
        "target_events": len(events),
        "changed_events": changed,
        "blanked_lines": blanked,
        "unchanged_lines": unchanged,
        "unassigned_segments": [
            {
                "cue": segment["cue"],
                "id": segment["id"],
                "speaker": segment.get("speaker"),
                "text": segment["text"],
            }
            for segment in unassigned
        ],
        "learned_speaker_map": {name: list(labels) for name, labels in learned_map.items()},
        "effective_speaker_map": {name: list(labels) for name, labels in speaker_map.items()},
        "speaker_labels": sorted(speaker_labels),
    }

    if not args.dry_run:
        with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
            output_file.write("\r\n".join(output_lines) + "\r\n")
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Content cues: {len(content_cues)}; segments: {len(segments)}")
    print(f"Target events: {len(events)}; changed: {changed}; blanked: {len(blanked)}")
    print(f"Unassigned reference segments: {len(unassigned)}")
    print(f"Learned speaker map: {report['learned_speaker_map']}")
    print(f"Output: {output_path}" if not args.dry_run else "Dry run: no output written")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
