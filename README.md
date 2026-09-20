# AI Image Watermark Remover

Remove **hidden watermarks** from AI-generated images — C2PA provenance manifests, EXIF/XMP/ICC metadata, PNG text chunks, and pixel-level steganographic marks (SynthID-class).

一次调用完成两层清理：容器元数据彻底剥离 + 像素级隐写水印扰动。

## What it does

| Layer | Content | How it's handled |
|-------|---------|------------------|
| Container / metadata | C2PA (JUMBF) provenance manifests, EXIF, XMP, ICC profiles, PNG `tEXt`/`iTXt`/`zTXt` chunks, trailing appended bytes | Pixels are decoded, the entire container is discarded, output is re-wrapped from scratch |
| Pixel | Steganographic (invisible) watermarks embedded in the pixel data | ±1 LSB noise + sub-pixel resample round-trip + optional edge crop & high-pass |

**Not covered:** visible overlay watermarks (corner logos, translucent text). Those need cropping or inpainting, not this tool.

## Requirements

```bash
pip install pillow numpy
```

Python 3.8+.

## Usage

```bash
# single image
python scripts/clean_watermark.py photo.jpg -o ./clean_out

# batch: several files, a directory, or a glob — one call handles all
python scripts/clean_watermark.py img1.jpg img2.jpg img3.jpg -o ./out --suffix
python scripts/clean_watermark.py ./downloads -o ./out -s strong
```

### Options

| Flag | Description |
|------|-------------|
| `-o, --outdir DIR` | Output directory (default `clean_out`) |
| `-p, --prefix NAME` | Output filename prefix (default `clean`) |
| `-s, --strength` | `light` \| `medium` (default) \| `strong` |
| `-f, --formats` | Comma list of `png,jpg` (default both) |
| `-q, --quality` | JPEG quality (default `95`) |
| `--suffix` | Name outputs `<original>_clean` instead of `clean_1..N` |

### Strength levels

- **light** — LSB ±1 noise only. Lowest visual impact, weakest disruption.
- **medium** — *(default)* noise + 2px up/down resample round-trip. Visually indistinguishable, dimensions unchanged.
- **strong** — adds a 1px edge crop and a mild unsharp mask. Strongest disruption, more pixel change.

### Built-in verification

Every run self-checks and reports what it found and what survived:

```
  source        : photo.jpg
  size          : (1024, 1536)
  found in src  : meta:icc_profile
  residual out  : none
  wrote         : photo_clean.png, photo_clean.jpg
```

`residual out: none` means the container layer is fully clean.

## Use as a WorkBuddy skill

This repo is also a ready-to-use [WorkBuddy](https://www.workbuddy.cn) skill. Drop it into your skills directory:

```bash
git clone https://github.com/yuxiaoyaoo/ai-image-watermark-remover.git \
  ~/.workbuddy/skills/ai-image-watermark-remover
```

The agent then picks it up automatically when you ask to strip hidden watermarks from an image.

## Limitations

Be clear about what this actually guarantees:

1. **The metadata layer is removed completely.** C2PA/JUMBF, EXIF, XMP and ICC blocks are dropped and the result is verifiable by a binary scan.
2. **The pixel layer is disrupted, not provably erased.** Mainstream steganographic watermarks (SynthID-class) are designed to survive noise and re-encoding. The default pipeline measurably degrades detectability but does **not** claim 100% failure against professional detectors. If you need stronger treatment, use `-s strong`, or add cropping + sharpening + a second lossy re-encode.
3. Note for WorkBuddy clipboard workflows: when an image is pasted into the chat it is re-saved as JPEG, and the C2PA manifest is already lost at that step — the source file usually carries only `icc_profile`. A `c2pa` binary grep returning nothing is expected, not a bug.

## License

No license file is included. All rights reserved by the author unless a license is added.
