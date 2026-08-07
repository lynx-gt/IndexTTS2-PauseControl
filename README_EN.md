# IndexTTS2-PauseControl

> **中文**: [README.md](README.md)

## What is this

In IndexTTS2 speech synthesis, **pause durations are decided by the model and
cannot be controlled** — the same comma may pause for 200ms in one run and
500ms in another, with no way to specify a requirement.

This tool (a ComfyUI node pack) provides **precise pause control**: specify
pause requirements directly in the text:

```
他停下脚步[pause:800ms]深吸一口气[pause:200ms]然后推开了那扇门[pause:600ms]。
```

After synthesis, the pause after "停下脚步" is 800ms, after "深吸一口气" is
200ms, and before the period (after "那扇门") is 600ms — measured average
deviation 13ms. In-sentence and around-period pauses are specified the same
way.

The model may occasionally pause inconsistently — missing a pause where one is
expected, or pausing where there is no punctuation. Marks are not limited to
punctuation positions: a pause of a specified duration can be inserted at any
position, including places without punctuation.

No model changes, no retraining — install the nodes and use them.

## Installation

### Option 1: Full package (recommended)

1. Put this repository directory into ComfyUI's `custom_nodes/`
   (keep the directory name `IndexTTS2-PauseControl`; back up any existing
   same-name directory first — it will be overwritten)
2. Install dependencies into ComfyUI's Python environment (see `requirements.txt`)
3. Run `python install.py` (auto-installs dependencies and checks the model
   directory), or install manually per `requirements.txt`
4. Download the IndexTTS2 model weights to `ComfyUI/models/index_tts/`
   (weights are NOT part of this repo — see official
   [index-tts/index-tts](https://github.com/index-tts/index-tts))
5. Restart ComfyUI

> Also installable via **ComfyUI-Manager** (search `IndexTTS2-PauseControl`).
>
> ⚠️ Run as a **directory** (under `custom_nodes/`). **Do NOT `pip install .`** — this
> project shares the package name `indextts` with the official package; pip
> installation would overwrite the official inference code.

### Option 2: Patch (for users who already have official indextts code)

See `patch/修改说明.md` (Chinese) — copy the modified files from `patch/modified/`
over your official files, add `patch/新增文件/pause_control.py` to
`indextts/utils/`, then pass `pause_mode=True` to `IndexTTS2.infer(...)`.

> The patch is file-overwrite based, not a git diff, because official code
> versions drift. The WebUI (Gradio) integration steps are described but
> **not verified in production** — this project's production environment is ComfyUI.

## Quick start

### 1. Write marks

Write `[pause:duration]` where you want a pause:

```
他停下脚步[pause:800ms]深吸一口气[pause:200ms]然后推开了那扇门。
他停下来[pause:1.5s]深吸一口气。
```

Accepted forms: `[pause:600ms]` / `[pause:600]` / `[pause:1.5s]` / `[pause:0.8s]`
(`[wait:]` and `[stop:]` prefixes are also accepted). Marks are replaced by an
ordinary comma during synthesis — the model never reads out "pause".

### 2. Generate

Wire the workflow in ComfyUI (examples in `workflows/`):

```
IndexTTSLoader → IndexTTSSingle (turn pause_mode on) → PreviewAudio
```

After importing an example workflow, set `spk_ref` to your own reference audio.

### 3. Listen to the comparison

`examples/audio/` contains 4 clips (same voice, same seed; the only difference
is the marks):

| File | Text | Measured pauses |
|------|------|-----------------|
| `zh_plain.wav` | 他停下脚步，深吸一口气，然后推开了那扇门。 | 469/499/359ms (natural, irregular) |
| `zh_pause.wav` | 他停下脚步[pause:800ms]深吸一口气[pause:200ms]… | **798ms / 190ms (precise)** |
| `en_plain.wav` | He stopped and took a deep breath. | 80/309ms (natural) |
| `en_pause.wav` | He stopped[pause:800ms]and took a deep breath. | **798ms (precise)** |

**Waveform comparison** (click a waveform to download and listen):

| Chinese | English |
|---------|---------|
| [![zh_plain waveform](examples/audio/zh_plain.png)](examples/audio/zh_plain.wav)<br>zh_plain (no pause) | [![en_plain waveform](examples/audio/en_plain.png)](examples/audio/en_plain.wav)<br>en_plain (no pause) |
| [![zh_pause waveform](examples/audio/zh_pause.png)](examples/audio/zh_pause.wav)<br>zh_pause (with pause) | [![en_pause waveform](examples/audio/en_pause.png)](examples/audio/en_pause.wav)<br>en_pause (with pause) |

Reference voice: a third-party collected voice (not the author's own voice).
Regenerate with your own reference via
`examples/make_compare_demo.py --model-dir <models> --spk-ref <ref audio>`.

### More about marks

**Around periods** (most stable; both forms are precise):

```
他深吸一口气[pause:800ms]。然后推开了门。    ← before the period
他深吸一口气。[pause:800ms]然后推开了门。    ← after the period
```

**Duration range**: recommended **150ms – 5s** (lower bound ≈100ms; no hard
upper bound — 1s/2s/5s all work).

**Chinese and English both work**: English is verified precise too (800ms
target → 778ms measured).

## Feature overview

**Core — precise pause control**:

- **In-sentence pauses** (commas): precise, ±20ms
- **Around periods**: both before-period and after-period forms work; even if
  the model produces no natural pause there, the target duration is realized
  via inter-sentence silence — **the duration is reached whether or not the
  model pauses**
- **Quote scenarios**: `period + quote` (`…。'`) is controllable too — no need
  to avoid quotes
- **Uniform period pauses**: without marks, every period pause is the same
  `interval_silence` (default 400ms). With the official default of 200ms the
  inter-sentence pause is shorter than the model's natural in-sentence comma
  pauses (~300ms), so periods would pause less than commas — an unnatural
  inversion; 400ms matches the natural period pause better. Set the overall
  rhythm first, then override individual periods with marks

**Production workflow capabilities** (for long-form content):

- **Batch generation**: Markdown script or multi-line text; resumable
- **Candidate rounds**: N candidates per entry (rounds); listen per round
- **Acceptance marking**: one-click "round N accepted" (written to manifest
  for downstream concatenation)
- **Seed reproducibility**: a fixed seed reproduces the exact same audio;
  random runs record the actual seed automatically
- **SRT subtitles**: generated from accepted rounds and real wav durations
- **Pause fixing**: adjust/remove a pause on existing audio by index or time
- **VRAM release**: unload the model before switching to video workflows

## Advanced usage

### Batch generation + candidate listening + acceptance

Workflow:

```
IndexTTSLoader → IndexTTSBatch (pause_mode on, rounds=3) → IndexTTSListen → PreviewAudio×3
```

- `IndexTTSBatch` generates from a Markdown script (`segments_md` = file path)
  or multi-line `text`
- Each entry gets `rounds` candidates (`001_1.wav`, `001_2.wav`, `001_3.wav`)
- `IndexTTSListen` picks an entry, listens to the 3 candidates; `accept_round`
  = 1/2/3 marks "round N accepted" (written to manifest.json for downstream
  concatenation / subtitles)

### Markdown script format

`segments_md` accepts a Markdown script file:

```markdown
---
story: My story
voice_ref: references/my-voice/main.wav
emotion_base: references/movie-dubbing
emotions: [calm, tense]
speaking_speed: 1.0
max_text_tokens_per_segment: 120
---

# 片段 001 [narrator / calm]
<!-- 标题: 标准同样严苛 -->
标准同样严苛[pause:800ms]不多一分。

<!-- 处理后: 标准同样严苛[pause:800ms]不多一分。 -->
```

- **YAML header** (optional): story / voice_ref / emotion_base / emotions /
  speaking_speed / max_text_tokens_per_segment
- **Entry title**: `# 片段 N [role / emotion]` — the emotion is used for
  emotion-reference selection ("random per directory" strategy)
- **Body**: the text to synthesize, `[pause:N]` kept as-is; if
  `<!-- 处理后: ... -->` is present, its content takes priority
- **One sentence per entry is recommended** (period pauses uniformly
  controlled by inter-sentence silence)
- Without a script file, write plain text in the `text` field (one line =
  one entry)

### Batch output

`IndexTTSBatch` produces a **task directory** (`output/{tag}_{timestamp}/`,
or a custom `output_dir`):

```
output/batch_20260807_120000/
├── 001_1.wav        entry 1, round 1 candidate
├── 001_1.wav.seed   seed of that round (reproducible with fixed seed)
├── 001_2.wav / 001_2.wav.seed
├── 001_3.wav / 001_3.wav.seed
├── 002_1.wav …      three round candidates of entry 2
└── manifest.json    task params + per-entry/round seed, duration, acceptance
                     marks (resume basis)
```

- Naming: `{entry:03d}_{round}.wav` (`001_1` = entry 1, round 1)
- Re-running the same task directory resumes (finished rounds skipped;
  parameter changes trigger a full re-run)

### Node parameters

| Node | Parameter | Description |
|------|-----------|-------------|
| IndexTTSSingle | `pause_mode` | Enable `[pause:N]` precise pause control |
| IndexTTSSingle | `detect_cfm_steps` | Deprecated (no effect), kept for compatibility |
| IndexTTSBatch | `pause_mode` | Enable for batch; skips legacy post-processing |
| IndexTTSBatch | `rounds` | Candidate rounds per entry |
| IndexTTSBatch | `interval_silence` | Period pause ms when unmarked (default 400) |
| IndexTTSListen | `task_dir` | Connect to batch node's task_dir output (takes priority) |
| IndexTTSListen | `accept_round` | Acceptance: 0=listen only; 1/2/3=mark that round accepted (written to manifest.json) |
| IndexTTSUnload | `model` | Release model VRAM (after TTS, before video workflows) |
| IndexTTSFix | `marks` | Pause fix: `2:800, 3:0` (index:target-ms, 0=delete) or `7.53:500` (time:target-ms) |
| IndexTTSSrt | `chosen` | Finalization: `1,2,1,3` (round per entry); single `3` = all round 3; empty = all round 1 |

### Suggested text organization

- **One sentence per entry**; period pauses default to the uniform
  `interval_silence`, override individual periods with marks
- In-sentence pauses: write `[pause:N]` directly
- Long multi-mark sentences (>40 chars): an individual mark may miss due to
  model pause fluctuation — change the seed or pick from the round candidates
  (with rounds=3 there is usually a fully-hit candidate)

## How it works (brief)

For those interested; not needed for daily use:

1. **Segmentation**: text is split at sentence-final punctuation (period =
   segment boundary; in-sentence stays intact for prosody)
2. **Mark classification**: in-sentence marks → in-segment processing;
   before/after-period marks → segment-boundary processing
3. **In-segment**: marks → commas → normal synthesis → pauses are located by
   energy detection (physical signal, no ASR) → marks are globally aligned to
   pauses (tolerating extra/missing pauses) → only the "silent core" of each
   pause is extended/shrunk/inserted (speech untouched, no re-decoding)
4. **Segment boundary**: tail mark hit → skip inter-sentence silence (no
   stacking); miss → realize the target via inter-sentence silence; last
   segment miss → append silence at the audio tail
5. **Concatenation**: inter-sentence silence = `interval_silence` (default
   400ms); gaps covered by marks use the mark duration

> **Terminology**: a **segment** is a sentence-final-punctuation split unit
> (official `split_sentences` output); a **script entry** is one `# 片段 N`
> item of the Markdown script (one entry may contain multiple segments).

Full details, parameter calibration and accuracy data:
[docs/PAUSE_CONTROL.md](docs/PAUSE_CONTROL.md). Terminology-to-code
mapping and the data flow: [docs/CODE_WALKTHROUGH.md](docs/CODE_WALKTHROUGH.md).

## Known limitations

- **Long single sentences with many marks**: positions are estimated by
  character-ratio; on long sentences (>40 chars) the error may exceed the
  match limit and an individual mark may miss — change the seed or pick from
  round candidates
- **No pause at a segment tail**: the target is still realized via
  inter-sentence silence / tail append (duration reached), but the pause
  lands at the period rather than right after the marked word — correct to
  the ear, slightly off-position
- **Breath after a long pause**: natural model behavior (may inhale); breaths
  are not silence and are not edited — denoise the segment if you mind
- **Insertion needs real silence**: no insertion into continuous speech
  (refuse rather than cut words)

## Tests

`test/` provides three layers:

```bash
python test/unit_test.py    # core-function unit tests (no GPU/model, CI runs automatically)
python test/smoke_test.py --model-dir <models> --spk-ref <ref audio>   # bilingual smoke
python test/regression_test.py --model-dir <models> --spk-ref <ref audio>  # 5-entry regression
```

Released build: smoke zh/en PASS; regression 5 entries average deviation 5ms.

## Acknowledgements

- **[bilibili IndexTTS2 team](https://github.com/index-tts/index-tts)**: model and
  inference code (`indextts/` in this project is modified from their open-source release)
- **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)**: node framework
- **[NVIDIA BigVGAN](https://github.com/NVIDIA/bigvgan)** and
  **[Amphion MaskGCT](https://github.com/amphion-ai/amphion)**: inference components
- Sequence alignment: Needleman & Wunsch (1970), Gotoh (1982)
  (see [docs/PAUSE_CONTROL.md](docs/PAUSE_CONTROL.md) §8)
- Reference voice of the example clips: a third-party collected voice

> Acknowledgements do not imply endorsement by the teams above; modifications
> to the original model are unrelated to the original right-holder
> (see `THIRD_PARTY_NOTICES.md`).

## License

- Original parts of this project (ComfyUI nodes, pause scheme, docs): MIT
  License (see `LICENSE`)
- `indextts/` inference code: derived from bilibili IndexTTS2, governed by the
  **bilibili Model Use License Agreement** (commercial use requires
  authorization from bilibili for qualifying organizations, etc.) — see
  `LICENSE.bilibili.txt` and `THIRD_PARTY_NOTICES.md`
