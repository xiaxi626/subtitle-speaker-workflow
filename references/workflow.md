# Subtitle Workflow Details

This unified Skill contains five modules: Text Transfer, Speaker Group, Speaker Map and Split, Speaker Split, and FFmpeg Command Generation.

## Module 1 — Text Transfer

### Preset A — two-file transfer

Inputs:

- Content reference: correct wording from any reliable subtitle source. May be SRT, VTT, or ASS.
- Timing target: ASS with timeline, styles, speaker names, and display tags to preserve.
- Output: a new ASS file.

CLI options:

| Option | Purpose |
|---|---|
| `--content` | Path to the correct-text subtitle. |
| `--timing` | Path to the target ASS timeline. |
| `--output` | Output ASS path. Defaults to `<timing-stem>.text-restored.ass`. |
| `--content-format` | Force `srt`, `vtt`, or `ass` parsing. |
| `--dry-run` | Match and report without writing output. |
| `--report` | Write a UTF-8 JSON report. |
| `--speaker-label` | Force a label to be treated as a speaker. Repeatable. |
| `--speaker-map` | Map target speaker to reference label, e.g. `S4=一弥`. Repeatable. |
| `--no-auto-speakers` | Disable automatic speaker-label detection. |
| `--blank-threshold` | Maximum normalized text length for clearing orphan fragments. Default `15`. |
| `--gap-tolerance` | Maximum distance in ms for filling empty target events. Default `2000`. |
| `--dedupe-gap` | Maximum gap in ms for merging rolling duplicate captions. Default `200`. |

### Preset B — three-file hidden bilingual transfer

Inputs:

- Content reference: accurate source-language text.
- Timing target: source-language ASS with timestamps and speakers.
- Hidden content: target-language subtitle to embed as hidden events.
- Output: a new ASS containing visible source-language events and hidden target-language events.

CLI options include all Preset A options that affect visible text transfer, plus:

| Option | Purpose |
|---|---|
| `--hidden-content` | Path to the target-language subtitle to hide. Required. |
| `--hidden-format` | Force `ass`, `srt`, or `vtt` parsing for hidden content. |
| `--hidden-styles` | ASS styles to include from hidden content. Comma-separated or repeatable. |
| `--hidden-exclude-styles` | ASS styles to exclude from hidden content. |
| `--hidden-fallback` | Manual speaker override: `START-END=SPEAKER`. Repeatable. |
| `--hidden-gap-tolerance` | Maximum gap in ms for mapping hidden events to visible events. Default `2000`. |

If `--hidden-styles` is omitted for ASS hidden content, the script excludes style names containing `JP`, `JA`, `JAP`, `ORIG`, or `SRC`, and styles ending in `2`. For reliable results, inspect the hidden ASS style table and pass `--hidden-styles` explicitly.

### Text Transfer matching rules

Visible text transfer:

1. Splits content cues at recognized speaker labels.
2. Assigns each content segment to the timing event with the strongest combination of time overlap and text similarity.
3. Uses learned or explicit speaker maps to disambiguate overlapping speaker events.
4. Fills unmatched short target events from nearby segments.
5. Removes rolling caption duplicates and empties short orphan fragments.
6. Long events with the same speaker name as a 45-second-or-longer event are treated as music/lyric events and are not blanked.

Hidden target-language alignment:

1. Maps each hidden event to the visible event with the highest time overlap and smallest gap.
2. Copies that visible event's `Name`, color, position, and `[S#]` prefix.
3. Prepends `{\hide}` while preserving the hidden subtitle's original text and timestamps.
4. Applies explicit fallback speaker mappings when no visible event is close enough.

## Module 2 — Speaker Group

Inputs:

- Input: a generated ASS file, typically from Text Transfer.
- Output: a new ASS file with visible events reordered by speaker.

CLI options:

| Option | Purpose |
|---|---|
| `--input` | Generated ASS file to reorganize. Required. |
| `--output` | Output ASS path. Defaults to `<input-stem>.speaker-grouped.ass`. |
| `--include-hidden` | Keep hidden target-language events instead of excluding them. |
| `--include-empty` | Keep visible events whose text is empty after tags. |
| `--speaker-map-csv` | Write a two-column UTF-8 BOM CSV with current/new speaker names. |
| `--verify` | Check that reordering did not add, drop, or modify dialogue content. |
| `--report` | Write a UTF-8 JSON report. |

Grouping rules:

1. Only `Dialogue:` events are reordered.
2. Events whose text starts with `{\hide}` are excluded by default.
3. Visible events are grouped by the `Name` field.
4. Speaker groups are ordered by each speaker's earliest start time.
5. Within each speaker group, events are sorted by start time, then end time, then layer.
6. A `Comment:` line is inserted before each speaker group.
7. The header and style section are preserved exactly.

Verification:

- `--verify` checks that the multiset of output `Dialogue:` lines equals the multiset of input visible `Dialogue:` lines under the same include settings.
- It only checks content equality; order is allowed to change.
- It does not compare comment lines.

## Module 3 — Speaker Map and Split

### Export subcommand

Inputs:

- A speaker-grouped ASS file, typically from Module 2.
- Optional include flags matching the grouping stage.

Output:

- A two-column CSV encoded as UTF-8 with BOM.
- Header: `当前说话人,新说话人`.
- Rows are ordered by each speaker's first appearance in the grouped ASS.
- Both columns are initially identical.

CLI options:

| Option | Purpose |
|---|---|
| `--input` | Speaker-grouped ASS file. Required. |
| `--output` | Output CSV path. Defaults to `<input-stem>.speaker-map.csv`. |
| `--include-hidden` | Include hidden events when collecting speaker names. |
| `--include-empty` | Include empty visible events when collecting speaker names. |
| `--report` | Write a UTF-8 JSON report. |

### Apply subcommand

Inputs:

- The same speaker-grouped ASS.
- The edited speaker map CSV.

Outputs:

- A renamed ASS file.
- One ASS file per speaker, unless `--no-split` is used.

CLI options:

| Option | Purpose |
|---|---|
| `--input` | Speaker-grouped ASS file. Required. |
| `--map` | Edited speaker map CSV. Required. |
| `--output` | Output renamed ASS path. Defaults to `<input-stem>.renamed.ass`. |
| `--split-dir` | Directory for per-speaker ASS files. Defaults to `<output-stem>.speakers`. |
| `--no-split` | Rename only; skip per-speaker files. |
| `--no-replace-text-prefix` | Keep leading `[S#]` text markers unchanged. |
| `--verify` | Verify dialogue count and non-empty speaker names. |
| `--report` | Write a UTF-8 JSON report. |

CSV rules:

1. Recognized headers include `当前说话人/新说话人`, `原说话人/改后说话人`, `current/new`, and `old/new`.
2. A blank new name means "keep the current name".
3. New names cannot contain commas or line breaks because ASS fields are comma-separated.
4. Duplicate current names with different targets are rejected.
5. Cells are trimmed; the first column must match the ASS `Name` exactly after trimming.

Apply rules:

1. ASS `Name` fields are replaced for `Dialogue:` and `Comment:` lines.
2. Trailing `// Speaker: OLD` comments in grouped ASS are updated.
3. Leading `[S#]` text markers are updated by default when the label matches a map key.
4. Per-speaker files preserve the ASS header and all `Style:` lines.
5. Output filenames use first-appearance order, e.g. `01_S1.ass`, `02_S2.ass`.
6. Windows-invalid characters in speaker names are replaced with `_`.

## Module 4 — Speaker Split

Inputs:

- A grouped ASS from Module 2, or a renamed ASS from Module 3.
- No speaker map CSV is read and no names are changed.

Outputs:

- One file per speaker in ASS, TXT, or both.

CLI options:

| Option | Purpose |
|---|---|
| `--input` | ASS file to split. Required. |
| `--split-dir` | Output directory. Defaults to `<input-stem>.speakers`. |
| `--format` | `ass`, `txt`, or `both`. Default: `ass`. |
| `--verify` | Verify that each ASS contains only its own speaker and each TXT exists. |
| `--report` | Write a UTF-8 JSON report. |

ASS output rules:

1. The ASS preamble, including `Style:` lines, is copied into every speaker file.
2. `Dialogue:` and `Comment:` events are grouped by their existing `Name` field.
3. Only speakers with at least one `Dialogue:` event get a file.
4. Filenames use first-appearance order, e.g. `01_S4.ass`, `02_S6.ass`.
5. Windows-invalid characters in speaker names are replaced with `_`.

TXT output rules:

1. One `NN_speaker.txt` file is written for every speaker that gets an ASS file.
2. Each line is formatted as `[START --> END] TEXT`.
3. ASS override tags are stripped and `\N` / `\n` are flattened into ` / `.
4. TXT files use UTF-8 with BOM and CRLF line endings.

Format guidance:

- Use ASS as the master format for Aegisub, players, burn-in, and any workflow that needs timing or styling.
- Use TXT as a readable sidecar for review, copy/paste, search, or LLM input.
- Prefer `--format both` unless the next tool only accepts one format.

## Module 5 — FFmpeg Command Generation

Inputs:

- One split ASS file via `--input`, or a directory of split ASS files via `--input-dir`.
- A video path for `ffmpeg -i`.
- An optional audio base name and output filename template.

Outputs:

- One command-list text file per input ASS.
- A combined command list in `--input-dir` mode.
- A JSON report when `--report` is used.

CLI options:

| Option | Purpose |
|---|---|
| `--input` | One ASS file to convert into commands. Mutually exclusive with `--input-dir`. |
| `--input-dir` | Directory of ASS files to process. Required in batch mode. |
| `--video` | Video path used after `ffmpeg -i`. Required. |
| `--audio-name` | Audio base name. Supports `{speaker}`, `{index}`, `{start}`, `{end}`. Defaults to the ASS speaker name. |
| `--name-template` | FLAC filename template. Default `{audio_name}_{index:03d}.flac`. |
| `--output-dir` | Directory where generated FLAC files will be written. Defaults to the subtitle directory. |
| `--combined` | Combined command file path in `--input-dir` mode. |
| `--runner` | PowerShell parallel runner path. Defaults to `<output-dir>/run_ffmpeg_parallel.ps1`. |
| `--runner-shells` | `all`, `powershell`, `bash`, `zsh`, or `fish`. Default: `all`. |
| `--max-parallel` | Concurrent ffmpeg processes in runners. Default: 4. |
| `--overwrite` | Add `-y` to generated commands. |
| `--verify` | Verify command count and `ffmpeg` prefix. |
| `--report` | Write a UTF-8 JSON report. |

Generation rules:

1. Only visible `Dialogue:` events are used.
2. Hidden events, empty text, and non-positive durations are skipped.
3. ASS times such as `0:00:12.72` are converted to `00:00:12.720`.
4. Each command uses `-i`, `-ss`, `-to`, `-map 0:a:0`, `-vn`, `-c:a flac`, and `-map_chapters -1`.
5. ffmpeg is never executed by this module; it only writes command text.
6. Command files are UTF-8 with BOM and CRLF line endings.
7. `--runner-shells all` generates four bounded-concurrency runners: `run_ffmpeg_parallel.ps1`, `run_ffmpeg_parallel.sh`, `run_ffmpeg_parallel.zsh`, and `run_ffmpeg_parallel.fish`.
8. All runners read the combined command file, launch at most `--max-parallel` ffmpeg processes at once, and report failed exit codes at the end.
9. On Windows, POSIX runner command file paths are written as `/c/...`; WSL users should change them to `/mnt/c/...`.

Template placeholders:

- `{audio_name}`: resolved audio base name.
- `{speaker}`: ASS `Name` field.
- `{index}`: integer event index, usable as `{index:03d}`.
- `{start}` / `{end}`: ffmpeg time with `:` and `.` replaced by `-`.

## Report interpretation

Text Transfer reports:

- `learned_speaker_map`: learned target-speaker to reference-label mapping.
- `unassigned_segments`: reference segments without a timing event.
- `blanked_lines`: short orphan recognition fragments cleared.
- `unchanged_lines`: timing events that keep their original text.
- `changed_events`: timing events whose text was replaced or cleared.

Preset B reports also include:

- `visible_dialogues`, `hidden_dialogues`, `mapped_hidden_dialogues`.
- `unmapped_hidden_dialogues`, `fallback_uses`, `hidden_speaker_distribution`.

Speaker Group reports:

- `visible_grouped_events`: number of events written.
- `excluded_events`: hidden or empty events excluded.
- `speaker_distribution`: count per speaker.
- `speaker_map_csv`: path to the exported mapping CSV, when requested.
- `verify`: `passed` or `failed`, only when `--verify` is used.

Speaker Map export reports:

- `speakers`: speaker names in first-appearance order.
- `grouped_events`: number of visible events used for collection.
- `excluded_events`: hidden or empty events skipped.

Speaker Map apply reports:

- `mapped_rows`: number of usable CSV rows.
- `blank_target_rows`: speakers whose new name was blank and therefore kept.
- `unused_map_rows`: CSV speakers not found in the input ASS.
- `replaced_text_prefix`: whether leading `[S#]` markers were replaced.
- `renamed_dialogues`: number of dialogue events whose `Name` changed.
- `renamed_comments`: number of comment events whose `Name` changed.
- `pair_counts`: per `from`/`to` dialogue counts.
- `dialogue_counts_before` / `dialogue_counts_after`: speaker distribution before and after replacement.
- `split_files`: mapping from final speaker name to per-speaker ASS path.
- `verify`: `passed` or `failed`, only when `--verify` is used.

Speaker Split reports:

- `input`: source ASS path.
- `split_dir`: output directory.
- `format`: `ass`, `txt`, or `both`.
- `speakers`: speaker names in first-appearance order.
- `dialogue_counts`: dialogue count per speaker.
- `total_dialogues`: total dialogue events split.
- `ass_files`: mapping from speaker name to ASS output path.
- `txt_files`: mapping from speaker name to TXT output path.
- `verify`: `passed` or `failed`, only when `--verify` is used.

FFmpeg Command Generation reports:

- `video`: resolved input video path.
- `inputs`: ASS files processed.
- `audio_name`: requested audio base name, or `null`.
- `name_template`: FLAC filename template.
- `output_dir`: directory for generated FLAC files.
- `total_commands`: total generated commands.
- `command_files`: mapping from ASS input path to command file path.
- `combined_command_file`: combined command file path in directory mode.
- `runner_file`: generated PowerShell runner path.
- `runner_files`: mapping from shell name to generated runner path.
- `runner_shells`: requested runner selection.
- `max_parallel`: configured concurrency for the runners.
- `per_input`: per-file speaker list, command count, and timestamp/output entries.
- `verify`: `passed` or `failed`, only when `--verify` is used.

## Verification checklist

1. Visible event count equals the timing target's Dialogue count in Text Transfer.
2. Hidden event count equals the selected hidden subtitle events in Preset B.
3. Every hidden event starts with `{\hide}` in Preset B.
4. Every hidden event's `Name` equals its `[S#]` text prefix in Preset B.
5. Speaker Group output dialogue count equals input visible dialogue count.
6. No hidden events appear in Speaker Group output by default.
7. Speaker Map CSV has exactly two columns and identical values in both columns before editing.
8. Speaker Map apply report shows `verify: passed` and no unexpected `unused_map_rows`.
9. Renamed ASS has the same dialogue count as the grouped ASS input.
10. Each per-speaker ASS contains only that speaker's dialogue events.
11. Speaker Split output names match the input ASS names; no CSV is applied.
12. Each TXT sidecar contains timestamped plain text with no ASS override tags.
13. FFmpeg command count equals the number of visible dialogue events in the source ASS files.
14. Each generated command uses the expected video path, timestamp range, audio stream map, FLAC codec, and output path.
15. Each generated parallel runner points to the intended combined command file and is syntactically valid for its shell.
16. Output is UTF-8 with BOM and uses CRLF line endings.
