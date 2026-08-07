# IndexTTS2-PauseControl

Precise pause control (`[pause:N]`) for IndexTTS2 as ComfyUI nodes.

Write `[pause:600ms]` anywhere in the text; the corresponding pause in the
generated audio is adjusted to 600ms with millisecond precision
(measured: 20 segments / 40 marks, mean |error| 13ms, max 32ms).
No whisper, no re-decoding — pure waveform-domain processing.

## Features

- **`[pause:N]` precise pauses**: extend / shrink / insert pauses at any
  punctuation — **including before/after periods**:
  - Normal marks (comma, enumeration comma): stable and precise (±20ms)
  - Mark *before* a period (`…[pause:N]。`): controls the pause right
    before the period (measured 838ms for an 800ms target)
  - Mark *after* a period (`…。[pause:N]`): controls the pause after the
    period (measured 798ms for an 800ms target, short and long texts)
  Per-mark strategy: normal/after-period use "longest core", before-period
  uses "nearest core" — mixed usage works independently
  (see "Suggested text organization")
- **No segment splitting**: the whole segment is synthesized in one pass and
  pauses are edited directly on the result — no need to split sentences and
  re-synthesize per part, **avoiding the prosody/tone artifacts that come
  with split-based approaches**
- **Waveform-domain pipeline**: marks → comma for the LLM → energy-based pause
  detection → Needleman-Wunsch global alignment (affine gap + asymmetric
  pricing + time hard-limit) → silent-core waveform editing (no re-decoding)
- **Batch generation + candidate listening + acceptance marking**: manifest
  resume, per-round candidates, one-click "accept round N" writing to manifest
- **Segmented script support**: Markdown scripts (one sentence per segment)
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
| IndexTTSBatch | `interval_silence` | Inter-segment silence ms (only between sub-segments of a multi-sentence segment) |
| IndexTTSListen | `task_dir` | Connect to batch node's task_dir output (takes priority) |
| IndexTTSListen | `accept_round` | Acceptance mark: 0=listen only; 1/2/3=mark that round accepted (written to manifest.json) |

### Suggested text organization

Split the script into **one sentence per segment** (period at segment end);
pauses between sentences default to concatenation-time control (inter-segment
silence). Where a precise period pause is needed, override it with a mark:
`句子[pause:800ms]。` (before the period) or `句子。[pause:800ms]` (after
the period) — both are precise.



## How it works (brief)

1. `[pause:N]` marks → commas → normal synthesis (model's natural pause
   duration is irrelevant to the target)
2. Energy-based pause detection (physical signal, 10ms frames; loose
   threshold for segments + strict threshold for the silent core)
3. Needleman-Wunsch alignment (affine gap, asymmetric pricing, 0.8s time
   hard-limit) maps marks to pauses, tolerating extra/missing pauses
4. Waveform editing on the silent core only (extend/shrink; insert at
   energy valleys guarded by real-silence check — refuse rather than cut speech)

Full details, parameter calibration and accuracy data:
[docs/PAUSE_CONTROL.md](docs/PAUSE_CONTROL.md).

## Known limitations

- The model may naturally insert a breath after a long pause; breaths have
  higher energy than silence and are not detected/edited (natural prosody —
  use post-processing denoise to remove if needed)
- Insertion requires a real silence at the target (energy-valley guard);
  refused when speech is continuous (rather than cutting words)
- Mark positions are estimated by character-ratio mapping; ±0.4s error on
  long sentences — covered by NW alignment + time hard-limit
- Short pauses (<250ms) measure slightly high (weak tail included), within ±30ms

## Tests

`test/` provides smoke/regression tests. They require a local GPU and the
model weights (not CI-friendly). Fixed seeds make them reproducible.

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
