# IndexTTS2-PauseControl


Precise pause control (`[pause:N]`) for IndexTTS2 as ComfyUI nodes.

Write `[pause:600ms]` anywhere in the text; the corresponding pause in the
generated audio is adjusted to 600ms with millisecond precision
(measured: 20 segments / 40 marks, mean |error| 13ms, max 32ms).
No whisper, no re-decoding — pure waveform-domain processing.

## Features

> **Terminology**: a **segment** is a sentence-final-punctuation split unit
> (official `split_sentences` output, code variable `segments`); a **script
> entry** is one `# 片段 N` item of the Markdown script (one batch unit, one
> wav; one entry may contain multiple segments — pauses between them are
> inter-segment silence).

- **`[pause:N]` precise pauses**: extend / shrink / insert pauses at any
  punctuation — **in-sentence and around periods, uniformly supported**:
  - In-sentence marks (comma, enumeration comma): waveform-domain editing
    in-segment (±20ms)
  - Mark *before* a period (`…[pause:N]。`): segment-tail pause — edited
    in-segment when hit, otherwise automatically falls back to inter-segment
    control
  - Mark *after* a period (`…。[pause:N]`): segment-head pause — directly
    controlled by inter-segment silence
  - Segment-tail fallback: on a miss, the target duration is realized via
    inter-segment silence; for the **last segment** it is appended at the
    audio tail
- **Period = segment boundary**: segmentation splits at sentence-final
  punctuation (no short-sentence merging) — every period pause is an
  inter-segment silence: uniform `interval_silence` (default 400ms) when
  unmarked, exact duration when marked
- **Quote scenarios supported**: `period + quote` (`…。'`) segment tails are
  controlled too (inter-segment fallback, no need to avoid quotes)
- **No in-sentence splitting**: comma/period marks inside a sentence are
  edited in the waveform domain — no re-synthesis, no sentence splitting,
  avoiding in-sentence prosody/tone artifacts
- **Waveform-domain pipeline**: marks → comma for the LLM → energy-based pause
  detection → Needleman-Wunsch global alignment (affine gap + asymmetric
  pricing + time hard-limit) → silent-core waveform editing (no re-decoding)
- **Batch generation + candidate listening + acceptance marking**: manifest
  resume, per-round candidates, one-click "accept round N" writing to manifest
- **Markdown script support**: script entries (one sentence per entry)
  or plain multi-line text

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

> Note: the patch is file-overwrite based, not a git diff, because official
> code versions drift. The WebUI (Gradio) integration steps are described but
> **not verified in production** — this project's production environment is ComfyUI.

## Usage

### [pause:N] syntax

```
他停下脚步[pause:800ms]深吸一口气[pause:200ms]然后推开了那扇门。
他停下来[pause:1.5s]深吸一口气。
```

Accepted forms: `[pause:600ms]` / `[pause:600]` / `[pause:1.5s]` / `[pause:0.8s]`
(`[wait:]` and `[stop:]` prefixes are also accepted). Marks are replaced by a
**full-width Chinese comma (，)** before synthesis.

**Around periods** (segment-boundary pauses, most stable):

```
他深吸一口气[pause:800ms]。然后推开了门。    ← before the period (segment tail)
他深吸一口气。[pause:800ms]然后推开了门。    ← after the period (segment head)
```

Period pauses are inter-segment silence: `interval_silence` (default 400ms)
when unmarked, exact mark duration when marked. **Quote scenarios**
(`…。'`) are supported too — no need to avoid them.

**Duration range**: recommended **150ms – 5s**. Lower bound ≈100ms (energy
detection minimum; <150ms measures slightly high including weak tails);
no hard upper bound (silence insertion in the waveform domain — 1s/2s/5s all
work; >5s is rarely useful).

**Chinese and English both work**: marks are always replaced with a Chinese
comma; English sentences are verified to work precisely as well (800ms target
→ 778ms measured) — the model treats the comma as a pause marker regardless
of language.

### ComfyUI workflow

```
IndexTTSLoader → IndexTTSSingle(pause_mode=on) → PreviewAudio
IndexTTSLoader → IndexTTSBatch(pause_mode=on) → IndexTTSListen(listen/accept) → PreviewAudio×3
```

Example workflows: `workflows/` (set `spk_ref` to your own reference audio).

### Effect comparison (bilingual)

`examples/audio/` contains 4 comparison clips (same seed, same voice; the only
difference is the `[pause:]` marks):

| File | Text | Measured pauses |
|------|------|-----------------|
| `zh_plain.wav` | 他停下脚步，深吸一口气，然后推开了那扇门。 | 469/499/359ms (natural, irregular) |
| `zh_pause.wav` | 他停下脚步[pause:800ms]深吸一口气[pause:200ms]… | **798ms / 190ms (precise)** |
| `en_plain.wav` | He stopped and took a deep breath. | 80/309ms (natural) |
| `en_pause.wav` | He stopped[pause:800ms]and took a deep breath. | **798ms (precise)** |

Reference voice: a third-party collected voice (not the author's own voice).
Regenerate with your own reference via
`examples/make_compare_demo.py --model-dir <models> --spk-ref <ref audio>`.

**Waveform comparison** (click a waveform to download and listen):

| Chinese | English |
|---------|---------|
| [![zh_plain waveform](examples/audio/zh_plain.png)](examples/audio/zh_plain.wav)<br>zh_plain (no pause) | [![en_plain waveform](examples/audio/en_plain.png)](examples/audio/en_plain.wav)<br>en_plain (no pause) |
| [![zh_pause waveform](examples/audio/zh_pause.png)](examples/audio/zh_pause.wav)<br>zh_pause (with pause) | [![en_pause waveform](examples/audio/en_pause.png)](examples/audio/en_pause.wav)<br>en_pause (with pause) |

### Node parameters

| Node | Parameter | Description |
|------|-----------|-------------|
| IndexTTSSingle | `pause_mode` | Enable `[pause:N]` precise pause control |
| IndexTTSSingle | `detect_cfm_steps` | **Deprecated** (no effect in waveform version), kept for compatibility |
| IndexTTSBatch | `pause_mode` | Enable for batch; skips legacy whisper post-processing |
| IndexTTSBatch | `rounds` | Candidate rounds per segment |
| IndexTTSBatch | `interval_silence` | Inter-segment silence ms (period pauses = this value after period-based segmentation, default 400) |
| IndexTTSListen | `task_dir` | Connect to batch node's task_dir output (takes priority) |
| IndexTTSListen | `accept_round` | Acceptance mark: 0=listen only; 1/2/3=mark that round accepted (written to manifest.json) |

### Suggested text organization

- Split the script into **one sentence per entry**; period pauses are
  uniformly controlled by inter-segment silence (`interval_silence`)
- For a precise period pause, write a mark: `句子[pause:800ms]。` (before the
  period) or `句子。[pause:800ms]` (after the period) — both are precise
- In-sentence pauses (commas) use `[pause:N]` directly, edited in-segment
- Long multi-mark sentences (>40 chars): if an individual mark misses due to
  model pause fluctuation, change the seed or pick from the round candidates
  (with rounds=3 there is usually a fully-hit candidate)

## How it works (brief)

1. **Segmentation**: split at sentence-final punctuation (period = segment
   boundary, no short-sentence merging; in-sentence stays intact for prosody)
2. **Mark classification**: in-sentence marks → in-segment processing;
   before/after-period marks → segment-boundary processing
3. **In-segment**: marks → commas → synthesis → energy-based pause detection
   (physical signal, 10ms frames) → Needleman-Wunsch alignment (affine gap,
   asymmetric pricing, 0.8s time hard-limit) → silent-core extend/shrink/insert
   (no re-decoding)
4. **Segment boundary**: tail mark hit → skip inter-segment silence (no
   stacking); miss → realize target via inter-segment silence; last segment
   miss → append silence at the audio tail
5. **Concatenation**: inter-segment silence = `interval_silence` (default
   400ms); gaps covered by marks use the mark duration

Full details, parameter calibration and accuracy data:
[docs/PAUSE_CONTROL.md](docs/PAUSE_CONTROL.md).

## Known limitations

- **Long single sentences with many marks**: positions are estimated by
  character-ratio; on long sentences (>40 chars) the error may exceed the
  match limit (0.8s) and an individual mark may miss — change the seed or
  pick from round candidates
- **No pause at a segment tail**: on a miss the target is still realized via
  inter-segment silence / tail append, but the pause lands at the period
  rather than right after the marked word — correct to the ear, slightly
  off-position
- The model may naturally insert a breath after a long pause; breaths have
  higher energy than silence and are not detected/edited (natural prosody —
  use post-processing denoise to remove if needed)
- Insertion requires a real silence at the target (energy-valley guard);
  refused when speech is continuous (rather than cutting words)
- Short pauses (<250ms) measure slightly high (weak tail included), within ±30ms

## Tests

`test/` provides three layers:

```bash
python test/unit_test.py    # core-function unit tests (no GPU/model, CI runs automatically, 30+ asserts)
python test/smoke_test.py --model-dir <models> --spk-ref <ref audio>   # bilingual smoke
python test/regression_test.py --model-dir <models> --spk-ref <ref audio>  # 5-segment regression
```

`unit_test.py` covers mark parsing / pause detection / NW alignment / waveform
editing (incl. edge cases: empty audio, short silence, no pauses, coordinate
regression) — verifies the core logic without a model; smoke/regression need
GPU + model weights (fixed seeds, reproducible). Released build: smoke zh/en
PASS; regression 5 segments average deviation 5ms.

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
