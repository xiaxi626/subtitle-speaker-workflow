from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import group_by_speaker as group
import speaker_map as speaker_map

TAG_RE = re.compile(r"\{[^{}]*\}")


def read_text(path: Path) -> str:
    return group.read_text(path)


def ass_time_to_ffmpeg(value: str) -> str:
    match = re.fullmatch(r"(\d+):(\d+):(\d+)\.(\d+)", value.strip())
    if not match:
        raise ValueError(f"Invalid ASS time: {value!r}")
    hours, minutes, seconds, centiseconds = map(int, match.groups())
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{centiseconds * 10:03d}"


def plain_text(text: str) -> str:
    return TAG_RE.sub("", text).strip()


def iter_dialogues(lines: list[str]):
    for line in lines:
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) != 10:
            continue
        if parts[9].startswith(r"{\hide}"):
            continue
        if not plain_text(parts[9]):
            continue
        if group.ass_ms(parts[1]) >= group.ass_ms(parts[2]):
            continue
        yield parts


def format_template(template: str, context: dict[str, str]) -> str:
    try:
        return template.format(**context)
    except KeyError as error:
        raise ValueError(f"Unknown placeholder {error} in template: {template!r}") from error


def build_commands(
    lines: list[str],
    video: Path,
    audio_name: str | None,
    name_template: str,
    output_dir: Path,
    overwrite: bool,
) -> tuple[list[str], dict]:
    commands: list[str] = []
    entries: list[dict] = []
    speakers: list[str] = []

    for index, parts in enumerate(iter_dialogues(lines), start=1):
        speaker = parts[4]
        if speaker not in speakers:
            speakers.append(speaker)
        start = ass_time_to_ffmpeg(parts[1])
        end = ass_time_to_ffmpeg(parts[2])
        context = {
            "speaker": speaker,
            "index": index,
            "start": start.replace(":", "-").replace(".", "-"),
            "end": end.replace(":", "-").replace(".", "-"),
        }
        base = format_template(audio_name, context) if audio_name else speaker
        context["audio_name"] = base
        filename = speaker_map.safe_filename(format_template(name_template, context))
        output_path = (output_dir / filename).resolve()
        video_path = video.resolve()
        overwrite_flag = " -y" if overwrite else ""
        command = (
            f"ffmpeg{overwrite_flag} -i \"{video_path}\" "
            f"-ss {start} -to {end} "
            f"-map 0:a:0 -vn -c:a flac -map_chapters -1 \"{output_path}\""
        )
        commands.append(command)
        entries.append({
            "speaker": speaker,
            "index": index,
            "start": start,
            "end": end,
            "output": str(output_path),
        })

    summary = {
        "speakers": speakers,
        "commands": len(commands),
        "entries": entries,
    }
    return commands, summary


def write_commands(path: Path, commands: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        output_file.write("\r\n".join(commands) + "\r\n")


def verify_commands(path: Path, summary: dict) -> bool:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return len(lines) == summary["commands"] and all(line.startswith("ffmpeg ") for line in lines)


RUNNER_FILENAMES = {
    "powershell": "run_ffmpeg_parallel.ps1",
    "bash": "run_ffmpeg_parallel.sh",
    "zsh": "run_ffmpeg_parallel.zsh",
    "fish": "run_ffmpeg_parallel.fish",
}


def to_shell_path(path: Path) -> str:
    text = str(path).replace("\\", "/")
    match = re.match(r"^([A-Za-z]):/(.*)$", text)
    if match:
        return f"/{match.group(1).lower()}/{match.group(2)}"
    return text


def shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def write_runner(path: Path, command_file: Path, max_parallel: int, shell: str = "powershell") -> None:
    max_parallel = max(1, int(max_parallel))

    if shell == "powershell":
        command_literal = str(command_file).replace("'", "''")
        content = (
            "param(\n"
            f"    [int]$MaxParallel = {max_parallel}\n"
            ")\n\n"
            f"$CommandFile = '{command_literal}'\n"
            "$commands = @(Get-Content -LiteralPath $CommandFile -Encoding UTF8 | Where-Object { $_.Trim() })\n"
            "$running = @()\n\n"
            "foreach ($cmd in $commands) {\n"
            "    while (@($running | Where-Object { -not $_.HasExited }).Count -ge $MaxParallel) {\n"
            "        Start-Sleep -Milliseconds 200\n"
            "    }\n"
            "    $arguments = '/d /s /c \"' + $cmd + '\"'\n"
            "    $running += Start-Process -FilePath $env:ComSpec -ArgumentList $arguments -PassThru -NoNewWindow\n"
            "}\n\n"
            "$running | Wait-Process\n"
            "$failed = @($running | Where-Object { $_.ExitCode -ne 0 })\n"
            "Write-Host ('Commands: {0}; failed: {1}' -f $commands.Count, $failed.Count)\n"
            "if ($failed.Count -gt 0) { exit 1 }\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as output_file:
            output_file.write(content)
        return

    command_literal = shell_single_quote(to_shell_path(command_file))

    if shell == "bash":
        content = (
            "#!/usr/bin/env bash\n"
            f"COMMAND_FILE={command_literal}\n"
            f'MAX_PARALLEL="${{1:-{max_parallel}}}"\n'
            "total=0\n"
            "failed=0\n"
            "pids=()\n\n"
            "while IFS= read -r cmd || [ -n \"$cmd\" ]; do\n"
            "    [ -z \"$cmd\" ] && continue\n"
            "    while [ \"$(jobs -rp | wc -l)\" -ge \"$MAX_PARALLEL\" ]; do\n"
            "        sleep 0.2\n"
            "    done\n"
            "    bash -c \"$cmd\" &\n"
            "    pids+=(\"$!\")\n"
            "    total=$((total + 1))\n"
            "done < \"$COMMAND_FILE\"\n\n"
            "for pid in \"${pids[@]}\"; do\n"
            "    if ! wait \"$pid\"; then\n"
            "        failed=$((failed + 1))\n"
            "    fi\n"
            "done\n"
            "echo \"Commands: $total; failed: $failed\"\n"
            "[ \"$failed\" -eq 0 ]\n"
        )
    elif shell == "zsh":
        content = (
            "#!/usr/bin/env zsh\n"
            f"COMMAND_FILE={command_literal}\n"
            f"MAX_PARALLEL=${{1:-{max_parallel}}}\n"
            "total=0\n"
            "failed=0\n"
            "typeset -a pids\n\n"
            "while IFS= read -r cmd || [[ -n \"$cmd\" ]]; do\n"
            "    [[ -z \"$cmd\" ]] && continue\n"
            "    while (( $(jobs -rp | wc -l) >= MAX_PARALLEL )); do\n"
            "        sleep 0.2\n"
            "    done\n"
            "    zsh -c \"$cmd\" &\n"
            "    pids+=($!)\n"
            "    (( total++ ))\n"
            "done < \"$COMMAND_FILE\"\n\n"
            "for pid in $pids; do\n"
            "    wait $pid || (( failed++ ))\n"
            "done\n"
            "print \"Commands: $total; failed: $failed\"\n"
            "(( failed == 0 ))\n"
        )
    elif shell == "fish":
        fish_literal = "'" + to_shell_path(command_file).replace("'", "\\'") + "'"
        content = (
            "#!/usr/bin/env fish\n"
            f"set COMMAND_FILE {fish_literal}\n"
            f"set MAX_PARALLEL {max_parallel}\n"
            "if test (count $argv) -gt 0\n"
            "    set MAX_PARALLEL $argv[1]\n"
            "end\n"
            "set total 0\n"
            "set failed 0\n"
            "set pids\n\n"
            "for cmd in (cat \"$COMMAND_FILE\")\n"
            "    if test -z \"$cmd\"\n"
            "        continue\n"
            "    end\n"
            "    while test (count (jobs -p)) -ge $MAX_PARALLEL\n"
            "        sleep 0.2\n"
            "    end\n"
            "    fish -c \"$cmd\" &\n"
            "    set pids $pids (jobs -p | tail -n 1)\n"
            "    set total (math $total + 1)\n"
            "end\n\n"
            "for pid in $pids\n"
            "    wait $pid\n"
            "    if test $status -ne 0\n"
            "        set failed (math $failed + 1)\n"
            "    end\n"
            "end\n"
            "echo \"Commands: $total; failed: $failed\"\n"
            "if test $failed -gt 0\n"
            "    exit 1\n"
            "end\n"
        )
    else:
        raise ValueError(f"Unsupported runner shell: {shell}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        output_file.write(content)


def write_runners(output_dir: Path, command_file: Path, shells: list[str], max_parallel: int, powershell_path: Path | None) -> dict[str, str]:
    written: dict[str, str] = {}
    for shell in shells:
        path = powershell_path if shell == "powershell" and powershell_path else output_dir / RUNNER_FILENAMES[shell]
        write_runner(path, command_file, max_parallel, shell)
        written[shell] = str(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate batch ffmpeg commands from ASS subtitle timestamps.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="One split ASS file")
    source.add_argument("--input-dir", type=Path, help="Directory of split ASS files")
    parser.add_argument("--video", required=True, type=Path, help="Input video path for ffmpeg -i")
    parser.add_argument("--audio-name", help="Audio base name; supports {speaker}, {index}, {start}, {end}")
    parser.add_argument("--name-template", default="{audio_name}_{index:03d}.flac", help="Output filename template")
    parser.add_argument("--output-dir", type=Path, help="Directory where generated FLAC files will go")
    parser.add_argument("--combined", type=Path, help="Combined command file path in --input-dir mode")
    parser.add_argument("--runner", type=Path, help="PowerShell parallel runner path")
    parser.add_argument("--runner-shells", choices=("all", "powershell", "bash", "zsh", "fish"), default="all", help="Which parallel runners to generate; default: all")
    parser.add_argument("--max-parallel", type=int, default=4, help="Concurrent ffmpeg processes in runners; default: 4")
    parser.add_argument("--overwrite", action="store_true", help="Add -y to generated ffmpeg commands")
    parser.add_argument("--verify", action="store_true", help="Verify command count and ffmpeg prefix")
    parser.add_argument("--report", type=Path, help="Write a UTF-8 JSON report")
    args = parser.parse_args()

    if not args.video.is_file():
        raise ValueError(f"Video file not found: {args.video}")

    if args.input:
        inputs = [args.input]
        default_output_dir = args.input.parent
    else:
        inputs = sorted(args.input_dir.glob("*.ass"))
        if not inputs:
            raise ValueError(f"No ASS files found in {args.input_dir}")
        default_output_dir = args.input_dir

    output_dir = (args.output_dir or default_output_dir).resolve()
    command_files: dict[str, str] = {}
    per_input: dict[str, dict] = {}
    all_commands: list[str] = []
    total_commands = 0

    for input_path in inputs:
        lines = read_text(input_path).splitlines()
        commands, summary = build_commands(
            lines,
            args.video,
            args.audio_name,
            args.name_template,
            output_dir,
            args.overwrite,
        )
        command_path = output_dir / f"{input_path.stem}_ffmpeg_commands.txt"
        write_commands(command_path, commands)
        command_files[str(input_path)] = str(command_path)
        per_input[str(input_path)] = {
            "command_file": str(command_path),
            "commands": summary["commands"],
            "speakers": summary["speakers"],
            "entries": summary["entries"],
        }
        all_commands.extend(commands)
        total_commands += summary["commands"]

    combined_path: Path | None = None
    if args.input_dir:
        combined_path = args.combined or output_dir / "ffmpeg_commands_all.txt"
        write_commands(combined_path, all_commands)

    runner_paths: dict[str, str] = {}
    if args.runner or args.input_dir or args.runner_shells != "powershell":
        shells = (
            list(RUNNER_FILENAMES)
            if args.runner_shells == "all"
            else [args.runner_shells]
        )
        runner_target = combined_path or Path(next(iter(command_files.values())))
        runner_paths = write_runners(output_dir, runner_target, shells, args.max_parallel, args.runner)
    runner_path = Path(runner_paths["powershell"]) if "powershell" in runner_paths else None

    verified = None
    if args.verify:
        verified = all(
            verify_commands(Path(data["command_file"]), {"commands": data["commands"]})
            for data in per_input.values()
        )
        if combined_path:
            verified = verified and len(
                combined_path.read_text(encoding="utf-8-sig").splitlines()
            ) == total_commands

    report = {
        "video": str(args.video.resolve()),
        "inputs": [str(path) for path in inputs],
        "audio_name": args.audio_name,
        "name_template": args.name_template,
        "output_dir": str(output_dir),
        "total_commands": total_commands,
        "command_files": command_files,
        "combined_command_file": str(combined_path) if combined_path else None,
        "runner_file": str(runner_path) if runner_path else None,
        "runner_files": runner_paths,
        "runner_shells": args.runner_shells,
        "max_parallel": args.max_parallel,
        "per_input": per_input,
        "verify": "passed" if verified else ("failed" if verified is False else None),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Inputs: {len(inputs)}")
    print(f"Commands generated: {total_commands}")
    if combined_path:
        print(f"Combined command file: {combined_path}")
    for shell, path in runner_paths.items():
        print(f"Parallel runner ({shell}): {path}")
    if args.verify:
        print(f"Verify: {'passed' if verified else 'failed'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
