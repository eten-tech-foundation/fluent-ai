# Source-TTS capacity: how many verses at once, and how long may one be?

**Deploying the whole feature?** Start with
[`source-tts-operations.md`](https://github.com/eten-tech-foundation/fluent-web/blob/main/docs/features/source-tts/source-tts-operations.md)
in fluent-web — the checklist, the open decisions, and how to prove the artifact store is actually
serving. This file is the sizing half of that.

**Who this is for:** whoever deploys fluent-ai and knows the container's real memory limit. It answers
one question — _what do I set, to support what?_ — and it is the single place the sizing evidence
lives. **It deliberately does not state the current values.** Those are in
[`src/app/config.py`](../../../src/app/config.py) and [`.env.example`](../../../.env.example); a number repeated
in two places drifts.

## TL;DR

- This guide sizes fluent-ai's speech-generation memory. The supported text length and per-clip byte ceiling move together; the total buffer budget divided by that ceiling determines worst-case concurrent admission slots.
- A survey of 11.2 million verses shows the coverage trade-off. Refusing overlong text at `generate` costs nothing; accepting a clip that exceeds its byte ceiling wastes a paid generation.
- Current settings live in `src/app/config.py` and `.env.example`. Choose a budget against the deployed container's real memory limit, including room for the service and compression tail.
- The bytes-per-character estimate comes from English speech and should be remeasured for other scripts. Byte-counted admission and encoder packaging alternatives remain future work or deployment choices.

## There is really only one dial

Three settings look independent and are not:

```
TTS_MAX_TEXT_LENGTH   characters accepted at generate, before anything is spent
TTS_MAX_CLIP_BYTES    one clip's byte ceiling  = one admission slot's reservation
TTS_MAX_BUFFERED_BYTES the whole RAM budget for in-flight generations

admission slots = ⌊ TTS_MAX_BUFFERED_BYTES / TTS_MAX_CLIP_BYTES ⌋
```

They are bound together by one inequality, which the service checks at boot and warns about:

```
TTS_MAX_TEXT_LENGTH × (PCM bytes per character) ≤ TTS_MAX_CLIP_BYTES
```

**Break it in the wrong direction and you convert a free failure into a paid one.** If the text limit
admits text whose audio would outgrow the clip ceiling, that text is accepted, hashed, given a
sidecar, sent to the provider, billed, synthesized for minutes — and _then_ killed mid-stream. The
same text under a consistent pair is refused at the door for nothing. So raising the text limit
always means raising the ceiling with it, and raising the ceiling always costs slots.

Hence: one dial, **how long a verse do we support**, and everything else follows from it.

## What the corpus actually contains

Measured 2026-08-16 over the eBible corpus — **1,005 translations, 11,227,230 verses** — counting
Unicode codepoints, the same way the service counts. Protestant canon only, and excluding
range-merges (translations that put `GEN 27:1-40` in the `27:1` slot); both filters matter, since the
unfiltered maximum is 10,063 and misleading. Reproduce by counting Unicode codepoints in the
Protestant-canon eBible corpus after excluding merged verse ranges.

| | characters |
| --- | ---: |
| median | 139 |
| p99 | 430 |
| p99.9 | 642 |
| p99.99 | 929 |
| p99.999 | 1,549 |
| **longest verse anywhere** | **6,504** |

The maximum is real, not a data artifact: `1KI 12:24` in Septuagint-based English translations
(`eng-englxxup`, `eng-eng-Brenton`, `eng-eng-lxx2012`) carries the LXX's long addition as a single
verse, with 12:23 and 12:25 either side at ordinary length. In the WEB the same verse is 246
characters. **A translator using one of those Bibles could legitimately press play on it.**

At the measured speech rate this is also near the provider's own limit: 6,504 characters is roughly
542 seconds of audio, about 83% of Gemini's ~655-second output cap. There is no headroom above the
longest real verse to be had — the provider runs out at about the same place Scripture does.

## The knob table

Ceiling is the text limit × ~4,000 PCM bytes per character; slots assume a 256 MiB budget. "Refused"
counts verses out of 11,227,230 that this limit would reject at `generate` — free and immediate, with
`TTS_TEXT_TOO_LONG`, never a billed failure.

| text limit | clip ceiling | slots @256 MiB | verses refused | |
| ---: | ---: | ---: | ---: | --- |
| 1,000 | 4.0 MB | 67 | 776 | 1 in 14,468 |
| 1,500 | 6.0 MB | 44 | 126 | 1 in 89,105 |
| 2,000 | 8.0 MB | 33 | 45 | 1 in 249,494 |
| 2,500 | 10.0 MB | 26 | 20 | 1 in 561,361 |
| 3,000 | 12.0 MB | 22 | 17 | 1 in 660,425 |
| 4,000 | 16.0 MB | 16 | 12 | 1 in 935,602 |
| 5,000 | 20.0 MB | 13 | 8 | 1 in 1,403,403 |
| 5,500 | 22.0 MB | 12 | 5 | 1 in 2,245,446 |
| **6,600** | **26.4 MB** | **10** | **0** | covers every measured verse |

The curve has a knee. Below ~1,500 characters refusals climb steeply; above ~3,000 each additional
slot-cost buys very few verses. Every verse above 3,000 characters is a Septuagint mega-addition in a
handful of English study Bibles.

## To support every verse in the corpus

Zero refusals needs a **26.4 MB** clip ceiling (text limit 6,600). Slots then depend only on how much
RAM you give the budget:

```
TTS_MAX_BUFFERED_BYTES = desired slots × 26.4 MB
container memory       ≈ budget × 1.5   (ffmpeg subprocess, interpreter, fragmentation)
                                        + the service's own baseline
```

| want | set budget to | container wants about |
| ---: | ---: | ---: |
| 8 slots | 212 MB | 320 MB + baseline |
| 16 slots | 423 MB | 640 MB + baseline |
| 24 slots | 634 MB | 950 MB + baseline |
| 32 slots | 845 MB | 1.3 GB + baseline |

**This is the knob to turn first.** Slots scale 1:1 with the budget at any ceiling, so if the
container has memory to spare, buying capacity with RAM costs nothing in coverage — whereas buying it
by lowering the ceiling costs verses. Squeeze the ceiling only when memory is genuinely tight.

## Two things that would change these numbers

- **The bytes-per-character rate (~4,000) was measured on one English clip.** Characters are not
  equally spoken across scripts: a Han character carries far more audio than a Latin one, and an
  abugida sits in between. The rate matters only where it converts the text limit into a ceiling, and
  the binding verses here happen to be English — but a deployment whose corpus is mostly non-Latin
  should re-measure before trusting the ceiling column. One synthesized clip per script family is
  enough, and costs about $0.001 each.
- **Worst-case reservation is why slots are scarce at all.** Each admission reserves the _full_
  ceiling before a byte arrives, while the median verse needs about 0.5 MB — roughly a 30× over-
  reservation. Byte-counting admission (designed, deliberately unbuilt; the design and its
  correctness argument are in `services/tts/generation.py`) would let real usage drive concurrency
  instead, at which point this table's slot column becomes a floor rather than a limit.

## If a verse is refused

`TTS_TEXT_TOO_LONG` at `generate` means the text was longer than the limit — nothing was spent, and
raising `TTS_MAX_TEXT_LENGTH` (with the ceiling, per the inequality above) is the fix.

`TTS_CLIP_TOO_LONG` mid-generation means audio outgrew the ceiling **while being billed**. With a
consistent pair this should be unreachable, so seeing it means either the bytes-per-character rate is
wrong for this corpus's script, or the provider is emitting audio nobody asked for. It is the alarm
attached to the assumption most likely to be wrong; keep the two codes distinct.

## What the compression tail costs on top

The numbers above account for the **generation heap** — the raw PCM a clip occupies while it is being
synthesized and streamed. The compression tail adds a second, smaller consumer that the container's
memory limit has to cover as well:

- **One ffmpeg subprocess per encode**, bounded by `TTS_FFMPEG_CONCURRENCY` (default **1**, which is
  why the addition is small and flat). A verse-sized encode runs far faster than realtime, so
  serializing them costs almost nothing; raise it only if compression is ever observed to be the
  bottleneck.
- **A transient copy of the finished clip.** The tail hands the encoder a `bytes` copy of the buffer
  and receives the compressed container back, so a clip briefly exists three times over: the live
  buffer (still being read by any attached listener), the copy on the pipe, and the encoded result.
  The encoded result is roughly a tenth of the PCM and the copy is released as soon as the encode
  returns, so the peak addition is about **one clip's PCM per concurrent encode** — not one per
  admission slot.

None of this is charged against `TTS_MAX_BUFFERED_BYTES`, which counts generation buffers only. It is
part of what §8.4's "roughly ×1.5 headroom over the budget" is for, and one more reason the container
limit, still to be confirmed for deployment, is the number worth getting.

## Where the encoder comes from

**On a developer machine, the wheel.** `imageio-ffmpeg` carries a static ffmpeg binary, so a `uv
sync` is the whole setup. **In the container, `apk`.** That wheel publishes macOS, manylinux2014 and
Windows builds and **no musl wheel**, so on this service's `python:3.14-alpine3.24` base uv installs
its 25 KB sdist, whose bundled-binaries directory is empty and whose `get_ffmpeg_exe()` raises. The
Dockerfiles therefore install `ffmpeg=8.1.2-r0` themselves, and `resolve_ffmpeg_binary()` prefers the
wheel, then `PATH`, then a bare name that fails at the first encode. `TTS_FFMPEG_BINARY` overrides
all three.

That was found by running the image, not by reading (2026-08-16). Before the fix, the
raise escaped `TtsService.__init__` and took every TTS route down; now a missing encoder degrades
only the tail.

**What a deployment with no working encoder costs, once it survives:** audio still streams and every
listener hears the whole verse, but nothing is ever uploaded — so no `302` is reachable and **every
listen re-bills the provider**. Durability, not correctness, and expensive.

Two properties of the packaging are still the team's to weigh: Alpine's ffmpeg
adds about **129 MB uncompressed** (the full libav video stack, for a 404 KB audio-only CLI) and is
GPL, as is the wheel's binary (`--enable-gpl --enable-version3`). Invoking either as a subprocess
rather than linking it is the ordinary way to use ffmpeg without the GPL reaching this service's own
source, but the image does then distribute GPL software. The likely answer is the shared
`transcode-mcp` container instead, and the swap is one class in `services/tts/compression.py` —
which is why the encoder sits behind a two-method seam rather than being called inline.
