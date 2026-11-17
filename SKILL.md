---
name: subtitle-workflow
description: This skill should be used for subtitle text transfer, hidden bilingual subtitle generation, speaker-grouped preprocessing, editable speaker-map CSV export, batch speaker renaming, per-speaker splitting in ASS or TXT, and batch ffmpeg command generation from subtitle timestamps. It covers five modules: replacing accurate text into a speaker-bearing ASS timeline, reordering visible events by speaker, applying a user-edited two-column speaker map, splitting a grouped or renamed ASS into one file per speaker without renaming, and generating per-clip ffmpeg audio extraction commands. Supports SRT, VTT, and ASS content sources, ASS timing targets, hidden target-language embedding, ASS/TXT output, ffmpeg command lists, and verification.
---

# Subtitle Workflow

## Overview

This unified Skill contains five modules:

1. **Text Transfer**
   - Replace inaccurate subtitle text with accurate reference text.
   - Preserve target ASS timestamps, styles, speaker names, and override tags.
   - Two presets: two-file transfer and three-file hidden bilingual transfer.

2. **Speaker Group**
   - Reorder visible ASS events by speaker.
   - Sort each speaker's events chronologically.
   - Exclude hidden target-language events by default.
   - Output a separate preprocessing ASS file.

3. **Speaker Map and Split**
   - Export a two-column CSV with `当前说话人,新说话人`.
   - The second column starts identical to the first; edit only the second column.
   - Apply the edited map to a speaker-grouped ASS, then write one ASS file per speaker.

4. **Speaker Split**
   - Split a grouped or renamed ASS into one file per speaker without renaming.
   - Default output is ASS; optional TXT sidecars contain cleaned, timestamped plain text.
   - Use `--format ass|txt|both` to choose the output.

5. **FFmpeg Command Generation**
   - Extract `Start`/`End` from ASS dialogue events.
   - Pair each timestamp range with the supplied video name/path and a user-filled audio base name.
   - Write batch `ffmpeg` commands for FLAC extraction without executing ffmpeg.

Never overwrite input files. Always write new files.

## Module 1 — Text Transfer

### Preset A — two-file text transfer

Use when the user says one subtitle is the content reference and another is the speaker-bearing timestamp reference.

```powershell
python "<skill-dir>/scripts/transfer_subtitle_text.py" `
  --content "<content-reference>" `
  --timing "<timing-speaker-ass>" `
  --output "<new-output>.ass" `
  --report "<report.json>"
```

### Preset B — three-file hidden bilingual transfer

Use when the user says one source-language subtitle is the content reference, one source-language ASS is the timing/speaker reference, and one target-language subtitle should be hidden.

```powershell
python "<skill-dir>/scripts/bilingual_hidden_transfer.py" `
  --content "<source-content-reference>" `
  --timing "<source-timing-speaker-ass>" `
  --hidden-content "<target-language-subtitle>" `
  --hidden-styles "Default,OPCN,EDCN,Title" `
  --hidden-fallback "0:06:05.00-0:06:10.00=S4" `
  --output "<new-output>.ass" `
  --report "<report.json>"
```

Preset B behavior:

- Visible events: source-language text from the content reference, using the timing target's timestamps and speakers.
- Hidden events: target-language text with `{\hide}`, using the hidden subtitle's own timestamps and styles.
- Hidden events receive the same `Name` and `[S#]` speaker prefix as the visible event with the strongest timestamp overlap.

### Text Transfer options

If speaker detection is wrong, rerun with:

```powershell
--speaker-label "一弥" --speaker-map "S4=一弥"
```

Only pass `--hidden-styles` when the hidden subtitle is ASS. Inspect its style lines first and include the styles that contain the target-language translation; exclude source-language, shadow-blur, and duplicate styles.

Use `--hidden-fallback` for hidden target-language lines whose timestamp has no corresponding visible source-language event. Format: `START-END=SPEAKER`.

## Module 2 — Speaker Group

Use after Text Transfer, or whenever the user asks to group subtitles by speaker.

```powershell
python "<skill-dir>/scripts/group_by_speaker.py" `
  --input "<generated-ass>" `
  --output "<grouped-output>.ass" `
  --speaker-map-csv "<speaker-map.csv>" `
  --verify `
  --report "<report.json>"
```

Speaker Group behavior:

- Excludes `{\hide}` hidden events by default.
- Groups visible events by the ASS `Name` field.
- Sorts speaker groups by first appearance time.
- Sorts events within each speaker by start time.
- Adds a comment before each speaker group.
- `--speaker-map-csv` writes a UTF-8 BOM CSV with current and new speaker names; both columns initially match.
- `--verify` checks that reordering did not add, drop, or modify dialogue content.

## Module 3 — Speaker Map and Split

Use when the speaker map CSV has been edited and the grouped ASS needs final names plus per-speaker files. Do not run the `apply` step until the user confirms the CSV has been edited; before that, stop after exporting the CSV.

```powershell
python "<skill-dir>/scripts/speaker_map.py" export `
  --input "<grouped-output>.ass" `
  --output "<speaker-map.csv>" `
  --report "<export-report.json>"
```

Edit `<speaker-map.csv>` in Excel or any text editor. Keep the first column untouched and change only the second column. The CSV is UTF-8 with BOM; an empty second column means "keep the current name".

```powershell
python "<skill-dir>/scripts/speaker_map.py" apply `
  --input "<grouped-output>.ass" `
  --map "<edited-speaker-map.csv>" `
  --output "<renamed>.ass" `
  --split-dir "<speaker-files-dir>" `
  --verify `
  --report "<apply-report.json>"
```

Speaker Map behavior:

- Edits ASS `Name` fields, `// Speaker:` comments, and leading `[S#]` text prefixes by default.
- Uses `--no-replace-text-prefix` to keep leading `[S#]` markers unchanged.
- Writes one `NN_说话人.ass` per speaker, preserving the original ASS header and styles.
- Uses `--no-split` to rename only, without creating per-speaker files.
- `--verify` checks that the dialogue count is unchanged and no speaker name is empty.
- Reports unused CSV rows, blank target rows, and per-pair replacement counts.

## Module 4 — Speaker Split

Use when the ASS is already grouped or renamed and the user only wants one file per speaker, with no CSV renaming step.

```powershell
python "<skill-dir>/scripts/speaker_map.py" split `
  --input "<grouped-or-renamed>.ass" `
  --split-dir "<speaker-files-dir>" `
  --format both `
  --verify `
  --report "<split-report.json>"
```

Speaker Split behavior:

- Does not read or require a speaker map CSV; speaker names stay exactly as they are in the input ASS.
- `--format ass` writes one `NN_说话人.ass` per speaker, preserving the ASS header and styles.
- `--format txt` writes one `NN_说话人.txt` per speaker with cleaned text and timestamps, e.g. `[0:00:12.72 --> 0:00:24.66] ...`.
- `--format both` writes both files for each speaker. Default is `ass`.
- Output filenames use first-appearance order and sanitize Windows-invalid characters.
- `--verify` checks that each ASS output contains only its own speaker and that every TXT output exists.
- Reports speaker counts, total dialogues, output file paths, and verification result.

ASS is the recommended primary format because it preserves timestamps, styles, positions, and override tags. TXT is best as a readable or LLM-friendly sidecar, not as the only master copy.

## Module 5 — FFmpeg Command Generation

Use when per-speaker ASS files are ready and the user wants batch audio-clip commands, but does not want ffmpeg executed yet.

```powershell
python "<skill-dir>/scripts/ffmpeg_commands.py" `
  --input-dir "<speaker-files-dir>" `
  --video "<input-video>" `
  --audio-name "<audio-base-name>" `
  --name-template "{audio_name}_{speaker}_{index:03d}.flac" `
  --runner-shells all `
  --max-parallel 4 `
  --verify `
  --combined "<combined-commands.txt>" `
  --report "<ffmpeg-report.json>"
```

FFmpeg Command Generation behavior:

- Reads `Start` and `End` from each visible `Dialogue:` event and converts ASS centiseconds to `HH:MM:SS.mmm`.
- Skips hidden events, empty text, and non-positive durations.
- Generates one command per event using: `-i`, `-ss`, `-to`, `-map 0:a:0`, `-vn`, `-c:a flac`, `-map_chapters -1`.
- Does not execute ffmpeg; it only writes command-list text files.
- With `--input-dir`, writes one `<ass-stem>_ffmpeg_commands.txt` per ASS plus a combined command file.
- `--runner-shells all` writes four short runners that read the command file and execute ffmpeg with bounded concurrency: `run_ffmpeg_parallel.ps1`, `run_ffmpeg_parallel.sh`, `run_ffmpeg_parallel.zsh`, and `run_ffmpeg_parallel.fish`.
- PowerShell: `powershell -ExecutionPolicy Bypass -File "<runner.ps1>" -MaxParallel 4`.
- Bash/Zsh: `bash "<runner.sh>" 4` or `zsh "<runner.zsh>" 4`.
- Fish: `fish "<runner.fish>" 4`; the first argument controls concurrency in all runners.
- On Windows, POSIX-style runners receive the command file path as `/c/...`; adjust it manually if running under WSL (`/mnt/c/...`).
- Default output location is the subtitle directory; override with `--output-dir`.
- Default filename template is `{audio_name}_{index:03d}.flac`; use `{speaker}` in the template when processing multiple speakers with a shared audio base name.
- `--audio-name` supports `{speaker}`, `{index}`, `{start}`, and `{end}`.
- `--overwrite` adds `-y` to generated commands.
- `--verify` checks that command counts and `ffmpeg` prefixes match the source dialogue counts.

## Scope and generalization

This workflow is not tied to Netflix or to one release group. Any accurate subtitle source can serve as the content reference. The timing target may come from manual timing, transcription, or diarization software, as long as its timeline roughly matches the content reference.

If the timing target has no speaker labels, Text Transfer can still replace text but cannot create speaker identities. If timelines drift substantially, correct the timing target first.

## Resources

- `README.md`: user-facing overview for all five modules.
- `scripts/transfer_subtitle_text.py`: Preset A CLI.
- `scripts/bilingual_hidden_transfer.py`: Preset B CLI.
- `scripts/group_by_speaker.py`: Speaker Group CLI.
- `scripts/speaker_map.py`: Speaker Map export/apply/split CLI.
- `scripts/ffmpeg_commands.py`: batch ffmpeg command generation CLI.
- `references/workflow.md`: detailed options, matching rules, and verification notes.
