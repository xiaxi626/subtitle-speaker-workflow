# 字幕工作流

这是一个“用户级 CodeBuddy Skill + 确定性 Python 工作流”。

它整合了五个模块：

1. **字幕文本替换**
   - 两份字幕：内容参考 + 有说话人的时间戳参考
   - 三份字幕：源语言内容参考 + 源语言时间戳/说话人参考 + 目标语言隐藏参考
2. **按讲话人归类**
   - 把生成字幕中的可见部分按讲话人归类
   - 同一讲话人按时间戳排序
   - 生成单独的预处理 ASS 文件
3. **说话人映射与拆分**
   - 导出两列 CSV：当前说话人 / 新说话人
   - 只改第二列，再批量替换到归类后的 ASS
   - 按说话人拆成一个个独立 ASS 文件
4. **只按说话人拆分**
   - 不改名字，直接把已归类/已改名的 ASS 按说话人拆开
   - 默认输出 ASS，也可同时输出 TXT 文本版
   - `--format ass|txt|both` 控制输出格式
5. **批量生成 ffmpeg 命令**
   - 从每条 ASS 对话提取起止时间戳
   - 配上我们给的视频名和你填入的音频名，生成逐条 `ffmpeg` 命令
   - 只写命令清单，不执行 ffmpeg

所有处理只生成新文件，不修改输入文件。

## 直接对 CodeBuddy 说：四条一步到位指令

把下面的 `字幕A/B/C/D`、`映射表`、`输出文件夹` 换成实际路径即可。

### 指令一：三份字幕 → 隐藏双语 + 归类 + 导出说话人映射表

```text
用 subtitle-workflow 一步到位处理到说话人映射表，先不要改名拆分。

内容参考：字幕A
有说话人的时间戳参考：字幕B
将被隐藏的目标语言字幕：字幕C
输出文件夹：输出文件夹

要求：
1. 用预设 B 生成日中隐藏双语 ASS；自动检查隐藏字幕的 Style 行，只选目标语言样式，排除日文样式和 *2 模糊/描边副本。
2. 如果隐藏事件落在可见事件时间范围之外，按上下文补 --hidden-fallback。
3. 用生成的隐藏双语 ASS 做按讲话人归类，默认排除隐藏事件，并加 --verify。
4. 归类时同步导出两列 UTF-8 BOM 说话人映射 CSV，第一列当前、第二列新，两列初始完全一致。
5. 所有输出放进新建的输出文件夹；完成后停下，不要执行改名和拆分，等我改 CSV。
```

### 指令二：映射表已改好 → 批量改名 + 按说话人拆分

```text
用 subtitle-workflow 继续处理，映射表已经改好，执行改名和拆分。

按讲话人归类字幕：字幕D
已编辑的说话人映射 CSV：映射表
输出文件夹：输出文件夹

要求：
1. 按 CSV 第二列批量替换 ASS 的 Name 字段、// Speaker: 注释，以及正文开头的 [S#] 说话人标记。
2. 加 --verify，确认对话条数不变且没有空说话人名。
3. 按最终说话人拆成独立 ASS，每个说话人一个文件，放进输出文件夹下的子文件夹。
4. 报告里列出 unused_map_rows、blank_target_rows 和每个对应关系的替换条数。
```

指令二里的 `字幕D` 通常是 `输出文件夹/02_按讲话人归类.ass`，`映射表` 通常是 `输出文件夹/02_说话人映射.csv`。

### 指令三：已归类/已改名字幕 → 只按说话人拆分

```text
用 subtitle-workflow 只按说话人拆分，不改名字。

要拆分的字幕：字幕D
输出文件夹：输出文件夹

要求：
1. 读取 ASS 中现有的说话人 Name，不读取映射 CSV，也不替换任何名字。
2. 每个说话人输出一个独立 ASS，放进输出文件夹下的子文件夹。
3. 同时输出每个说话人的 TXT 文本版，内容为去样式标签后的纯文本，并保留时间戳。
4. 加 --verify，确认每个 ASS 只含自己的说话人，TXT 文件都生成成功。
```

### 指令四：说话人字幕 → 批量生成 ffmpeg 音频切条命令

```text
用 subtitle-workflow 根据说话人字幕批量生成 ffmpeg 命令，不要执行 ffmpeg。

按说话人拆分的字幕目录：字幕D目录
视频名/路径：视频名
音频名：音频名
输出文件夹：输出文件夹

要求：
1. 从每个 ASS 的每条可见 Dialogue 提取 Start 和 End，转换成 HH:MM:SS.mmm。
2. 用我们给的视频名/路径作为 -i，按参考命令生成：-ss 起点、-to 终点、-map 0:a:0、-vn、-c:a flac、-map_chapters -1。
3. 输出文件名用 "{音频名}_{说话人}_{三位序号}.flac"，FLAC 输出目录用字幕所在目录。
4. 每个说话人一个命令清单，再生成一份总清单；报告里列出命令数和输出路径。
5. 再生成 PowerShell、bash、zsh、fish 四种并行运行器，默认 4 并发，读取总清单执行；我只要文件，不要现在运行。
6. 只生成命令文本文件和运行器，不要运行 ffmpeg。
```

如果当前会话没有识别到该 Skill，重新打开一个会话即可。

## 模块 1：字幕文本替换

### 预设 A：两份字幕

适用于你这样说时：

> 提供一份字幕作为内容参考，一份作为有说话人的时间戳参考。

```powershell
python "C:\Users\asswsw\.codebuddy\skills\subtitle-workflow\scripts\transfer_subtitle_text.py" `
  --content "内容参考.srt" `
  --timing "时间戳说话人.ass" `
  --output "成品.ass" `
  --report "report.json"
```

### 预设 B：三份字幕，隐藏目标语言

适用于你这样说时：

> 提供一份源语言字幕作为内容参考，一份作为有说话人的时间戳源语言字幕参考，再提供一份将被隐藏处理的目标语言字幕参考。

```powershell
python "C:\Users\asswsw\.codebuddy\skills\subtitle-workflow\scripts\bilingual_hidden_transfer.py" `
  --content "源语言内容参考.srt" `
  --timing "源语言时间戳说话人.ass" `
  --hidden-content "目标语言字幕.ass" `
  --hidden-styles "Default,OPCN,EDCN,Title" `
  --hidden-fallback "0:06:05.00-0:06:10.00=S4" `
  --output "日中隐藏双语.ass" `
  --report "report.json"
```

预设 B 输出：

- 可见事件：源语言内容参考的文字，使用时戳参考 ASS 的时间戳和讲话人。
- 隐藏事件：目标语言翻译，保留其原本时间戳和样式，并加 `{\hide}`。
- 隐藏事件的 `Name` 和 `[S#]` 讲话人标记会按时间戳对齐到对应可见事件。

## 模块 2：按讲话人归类

适用于你这样说时：

> 把这个字幕按说话人归类，生成预处理文件。

```powershell
python "C:\Users\asswsw\.codebuddy\skills\subtitle-workflow\scripts\group_by_speaker.py" `
  --input "生成字幕.ass" `
  --output "按讲话人归类.ass" `
  --speaker-map-csv "说话人映射.csv" `
  --verify `
  --report "report.json"
```

输出行为：

- 默认排除隐藏的目标语言事件。
- 按讲话人 `Name` 分组。
- 同一讲话人内按时间戳升序。
- 每组前加注释标记。
- `--speaker-map-csv` 同步导出两列映射表，第一列是当前说话人，第二列初始完全相同。
- `--verify` 校验重排后内容与输入可见内容一致。

## 模块 3：说话人映射与拆分

适用于你这样说时：

> 我已经改好了说话人对应表，把归类字幕里的说话人批量换掉，然后每个人单独出一个文件。

如果归类阶段没有加 `--speaker-map-csv`，可以随时补导出：

```powershell
python "C:\Users\asswsw\.codebuddy\skills\subtitle-workflow\scripts\speaker_map.py" export `
  --input "按讲话人归类.ass" `
  --output "说话人映射.csv" `
  --report "export-report.json"
```

`说话人映射.csv` 是 UTF-8 BOM 编码，可直接用 Excel 打开：

| 当前说话人 | 新说话人 |
|---|---|
| S1 | S1 |
| S2 | S2 |

只修改第二列。第二列留空表示保留原说话人。CSV 还没改好时，流程停在这里，不要执行下面的 apply 命令；确认改好后执行：

```powershell
python "C:\Users\asswsw\.codebuddy\skills\subtitle-workflow\scripts\speaker_map.py" apply `
  --input "按讲话人归类.ass" `
  --map "说话人映射.csv" `
  --output "按讲话人归类.改名后.ass" `
  --split-dir "按说话人拆分" `
  --verify `
  --report "apply-report.json"
```

输出行为：

- 替换 ASS 的 `Name` 字段、`// Speaker:` 注释，以及开头的 `[S#]` 说话人标记。
- 如不想改 `[S#]` 标记，加 `--no-replace-text-prefix`。
- 如只想改名不拆文件，加 `--no-split`。
- 每个说话人输出一个 `NN_说话人.ass`，保留原 ASS 头部和样式。
- 报告里会列出未用到的映射行、空的新名字行，以及每个对应关系的替换条数。

## 模块 4：只按说话人拆分

适用于你这样说时：

> 这个字幕不用改名字，直接按说话人拆成一个人一个文件。

```powershell
python "C:\Users\asswsw\.codebuddy\skills\subtitle-workflow\scripts\speaker_map.py" split `
  --input "按讲话人归类.ass" `
  --split-dir "按说话人拆分" `
  --format both `
  --verify `
  --report "split-report.json"
```

输出行为：

- 不读取映射 CSV，也不修改任何说话人名字。
- `--format ass`：每个说话人一个 `NN_说话人.ass`，保留 ASS 头部、样式、时间轴和特效标签。
- `--format txt`：每个说话人一个 `NN_说话人.txt`，内容为去样式标签后的纯文本，带时间戳，例如 `[0:00:12.72 --> 0:00:24.66] 文本`。
- `--format both`：同时输出 ASS 和 TXT；默认值是 `ass`。
- 文件名按说话人首次出现顺序编号，并自动替换 Windows 不允许的字符。
- `--verify` 检查每个 ASS 只含自己的说话人，且每个 TXT 都存在。

格式建议：**ASS 作为主文件**，TXT 作为阅读/复制给 AI 的辅助文件。ASS 保留时间轴、样式、位置和特效标签；TXT 更轻，但会丢失这些结构信息，不适合作为唯一母版。

## 模块 5：批量生成 ffmpeg 命令

适用于你这样说时：

> 根据这些说话人字幕的时间戳，生成批量 ffmpeg 命令，但先不要执行。

```powershell
python "C:\Users\asswsw\.codebuddy\skills\subtitle-workflow\scripts\ffmpeg_commands.py" `
  --input-dir "按说话人拆分" `
  --video "输入视频.mkv" `
  --audio-name "GOSICK_E01" `
  --name-template "{audio_name}_{speaker}_{index:03d}.flac" `
  --runner-shells all `
  --max-parallel 4 `
  --verify `
  --combined "按说话人拆分\ffmpeg_commands_all.txt" `
  --report "ffmpeg-report.json"
```

输出行为：

- 从每条可见 `Dialogue:` 提取 `Start` 和 `End`，转换成 `HH:MM:SS.mmm`。
- 生成命令格式：
  `ffmpeg -i "输入视频" -ss 起点 -to 终点 -map 0:a:0 -vn -c:a flac -map_chapters -1 "输出.flac"`
- 默认把 FLAC 输出路径设为字幕所在目录，即说话人拆分目录。
- 每个 ASS 生成一个 `<文件名>_ffmpeg_commands.txt`，并可用 `--combined` 生成总清单。
- 目录模式下会生成四种并行运行器，不用把 165 行命令复制进窗口：
  - PowerShell：`run_ffmpeg_parallel.ps1`
  - bash：`run_ffmpeg_parallel.sh`
  - zsh：`run_ffmpeg_parallel.zsh`
  - fish：`run_ffmpeg_parallel.fish`
- 运行方式：
  - PowerShell：`powershell -ExecutionPolicy Bypass -File "按说话人拆分\run_ffmpeg_parallel.ps1" -MaxParallel 4`
  - bash：`bash "按说话人拆分/run_ffmpeg_parallel.sh" 4`
  - zsh：`zsh "按说话人拆分/run_ffmpeg_parallel.zsh" 4`
  - fish：`fish "按说话人拆分/run_ffmpeg_parallel.fish" 4`
- 第一个参数就是并发数，默认是 4；机器强可以调大，卡就调小。
- Windows 下 POSIX 运行器里的命令文件路径会写成 `/c/...`；如果你用 WSL，需要手动改成 `/mnt/c/...`。
- 不执行 ffmpeg，只生成命令文本和运行器；真正执行由你决定。
- `--audio-name` 支持 `{speaker}`、`{index}`、`{start}`、`{end}` 占位符。
- `--name-template` 默认 `{audio_name}_{index:03d}.flac`；处理多个说话人时建议像示例这样加入 `{speaker}` 避免重名。
- `--overwrite` 会在命令中加 `-y`。
- `--verify` 校验命令条数与原字幕对话条数一致。

## 何时需要手动干预

- 报告中 `learned_speaker_map` 明显错误：使用 `--speaker-map "S4=一弥"`。
- 内容参考中的讲话人没有被自动识别：使用 `--speaker-label "一弥"`。
- 隐藏字幕有条目落在可见事件时间范围之外：使用 `--hidden-fallback`。
- 隐藏字幕提取了错误样式：调整 `--hidden-styles` 或 `--hidden-exclude-styles`。
- 归类后想确认没有丢内容：使用 `--verify`。
- 映射 CSV 中某些新名字没生效：检查报告的 `unused_map_rows`，确认第一列与原 `Name` 完全一致。
- 不想让字幕正文里的 `[S#]` 一起改：改名时使用 `--no-replace-text-prefix`。
- 输出文件名有冲突或含特殊字符：脚本会自动加序号并替换 Windows 不允许的字符。
- 后续要导入 Aegisub、播放器或剪辑软件：用 ASS；要给 AI 阅读或做纯文本检索：用 TXT，最好两者都留。
- ffmpeg 命令清单不会自动执行；先抽查视频路径、时间点和输出文件名，再批量运行。

详细参数和排障说明见 `references/workflow.md`。
