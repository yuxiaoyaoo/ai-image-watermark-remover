#!/usr/bin/env python3
"""Remove hidden watermarks from AI-generated images.

Two layers are handled:

1. Metadata layer  - C2PA/JUMBF provenance manifests, EXIF, XMP, ICC, PNG
   text chunks, and bytes appended after the image end-of-file marker.
2. Pixel layer     - steganographic (invisible) watermarks embedded in the
   pixel data, disrupted by LSB noise + micro-resampling.

Usage:
    python clean_watermark.py IMG [IMG ...] [options]

    IMG may be a file path, a directory (all images inside), or a glob
    pattern. Multiple inputs are processed in one run.

Options:
    -o, --outdir DIR     Output directory (default: ./clean_out)
    -p, --prefix NAME    Output filename prefix (default: "clean")
    -s, --strength LEVEL light | medium | strong   (default: medium)
    -f, --formats LIST   Comma list of png,jpg       (default: png,jpg)
    -q, --quality N      JPEG quality for jpg output (default: 95)
        --suffix         Append "_clean" to each source basename instead of
                         numbering them (default: number them 1..N)

Strength semantics:
    light   LSB +-1 noise only. Lowest visual impact, weakest disruption.
    medium  LSB +-1 noise + 2px up/down resample round-trip. (recommended)
    strong  medium + 1px edge crop + mild unsharp mask. Best disruption,
            changes the image dimensions slightly.
"""

from __future__ import annotations

import argparse
import glob as globmod
import io
import os
import sys

try:
    import numpy as np
    from PIL import Image, ImageFilter
except ImportError as exc:  # pragma: no cover
    sys.exit(
        "Missing dependency: %s\n"
        "Install with:  pip install pillow numpy" % exc
    )

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# Bytes commonly appended after the real image data by watermarking tools.
TRAILING_MARKERS = (b"c2pa", b"C2PA", b"jumbf", b"JUMBF", b"synthid", b"SynthID")


def collect_inputs(raw_inputs: list[str]) -> list[str]:
    """Expand files, directories and glob patterns into a file list."""
    found: list[str] = []
    for item in raw_inputs:
        if os.path.isdir(item):
            for name in sorted(os.listdir(item)):
                p = os.path.join(item, name)
                if os.path.isfile(p) and os.path.splitext(p)[1].lower() in IMAGE_EXTS:
                    found.append(p)
        elif os.path.isfile(item):
            found.append(item)
        else:
            matches = sorted(globmod.glob(item))
            found.extend(m for m in matches if os.path.isfile(m))
    # de-dup, keep order
    seen: set[str] = set()
    out: list[str] = []
    for p in found:
        ap = os.path.abspath(p)
        if ap not in seen:
            seen.add(ap)
            out.append(ap)
    return out


def scan_trailers(path: str) -> list[str]:
    """Report suspicious markers present in the raw file container."""
    with open(path, "rb") as fh:
        blob = fh.read()
    hits: list[str] = []
    for marker in TRAILING_MARKERS:
        if marker in blob:
            hits.append(marker.decode("ascii"))
    # PNG: report text chunks
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        for chunk in (b"tEXt", b"iTXt", b"zTXt", b"eXIf"):
            if chunk in blob:
                hits.append("PNG:" + chunk.decode("ascii"))
    return hits


# Structural JPEG markers that carry no provenance information.
BENIGN_INFO_KEYS = {"jfif", "jfif_version", "jfif_unit", "jfif_density"}


def scan_metadata_keys(path: str) -> list[str]:
    """Report non-structural metadata blocks (EXIF/XMP/ICC/...) in a container."""
    try:
        with Image.open(path) as im:
            return sorted(set(im.info.keys()) - BENIGN_INFO_KEYS)
    except Exception:
        return []


def strip_container(path: str) -> Image.Image:
    """Decode pixels only. Container metadata is discarded entirely.

    Alpha channel (transparency) is preserved when present — flattening an
    RGBA source to RGB would composite it onto black and effectively
    "add a background".
    """
    with open(path, "rb") as fh:
        data = fh.read()
    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        return img.convert("RGBA")
    return img.convert("RGB")


def disrupt_pixels(img: Image.Image, strength: str, seed: int = 42) -> Image.Image:
    """Apply imperceptible pixel-domain changes that break stego watermarks."""
    mode = img.mode  # "RGB" or "RGBA"

    if strength == "light":
        arr = np.asarray(img, dtype=np.int16)
        noise = np.random.default_rng(seed).integers(-1, 2, size=arr.shape)
        return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8), mode)

    # medium / strong: noise first
    out = disrupt_pixels(img, "light", seed)

    # sub-pixel resample round-trip breaks frequency-domain alignment
    # (RGBA: resample RGB and alpha channels together — PIL handles this)
    w, h = out.size
    out = (
        out.resize((w + 2, h + 2), Image.LANCZOS)
        .resize((w, h), Image.LANCZOS)
    )

    if strength == "strong":
        # 1px edge crop + re-expand, plus a mild high-pass touch-up
        cw, ch = max(1, w - 2), max(1, h - 2)
        out = out.crop((1, 1, 1 + cw, 1 + ch)).resize((w, h), Image.LANCZOS)
        if mode == "RGB":
            out = out.filter(ImageFilter.UnsharpMask(radius=1.0, percent=40, threshold=3))
        else:
            r, g, b, a = out.split()
            rgb = Image.merge("RGB", (r, g, b)).filter(
                ImageFilter.UnsharpMask(radius=1.0, percent=40, threshold=3)
            )
            out = Image.merge("RGBA", (*rgb.split(), a))

    return out


def clean_one(
    src: str,
    out_base: str,
    outdir: str,
    strength: str,
    formats: list[str],
    quality: int,
) -> list[str]:
    """Clean a single image. Returns the list of written files."""
    before = scan_trailers(src) + ["meta:" + k for k in scan_metadata_keys(src)]
    img = strip_container(src)
    cleaned = disrupt_pixels(img, strength)
    written: list[str] = []

    for fmt in formats:
        if fmt == "png":
            path = os.path.join(outdir, out_base + ".png")
            # No exif=, no pnginfo= -> PIL writes a bare container.
            cleaned.save(path, "PNG", optimize=True)
        elif fmt in ("jpg", "jpeg"):
            path = os.path.join(outdir, out_base + ".jpg")
            if cleaned.mode == "RGBA":
                # JPEG has no alpha: composite onto white instead of black.
                bg = Image.new("RGB", cleaned.size, (255, 255, 255))
                bg.paste(cleaned, mask=cleaned.split()[-1])
                bg.save(path, "JPEG", quality=quality, subsampling=0, optimize=True)
            else:
                cleaned.save(path, "JPEG", quality=quality, subsampling=0, optimize=True)
        else:
            raise ValueError("unsupported format: %s" % fmt)
        written.append(path)

    # verification
    after_hits: list[str] = []
    for p in written:
        after_hits.extend(scan_trailers(p))
        after_hits.extend("meta:" + k for k in scan_metadata_keys(p))

    print("  source        : %s" % os.path.basename(src))
    print("  size          : %s" % (cleaned.size,))
    print("  found in src  : %s" % (", ".join(before) if before else "none"))
    print("  residual out  : %s" % (", ".join(after_hits) if after_hits else "none"))
    print("  wrote         : %s" % ", ".join(os.path.basename(p) for p in written))
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove hidden watermarks from AI images.")
    ap.add_argument("inputs", nargs="+", help="files, directories or glob patterns")
    ap.add_argument("-o", "--outdir", default="clean_out", help="output directory")
    ap.add_argument("-p", "--prefix", default="clean", help="output filename prefix")
    ap.add_argument(
        "-s", "--strength", choices=("light", "medium", "strong"), default="medium"
    )
    ap.add_argument("-f", "--formats", default="png,jpg")
    ap.add_argument("-q", "--quality", type=int, default=95)
    ap.add_argument("--suffix", action="store_true", help="use '<name>_clean' basenames")
    args = ap.parse_args()

    files = collect_inputs(args.inputs)
    if not files:
        print("No input images found.", file=sys.stderr)
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]

    print("Cleaning %d image(s) with strength=%s\n" % (len(files), args.strength))
    written_all: list[str] = []
    for idx, src in enumerate(files, start=1):
        stem = os.path.splitext(os.path.basename(src))[0]
        out_base = (
            "%s_clean" % stem if args.suffix else "%s_%d" % (args.prefix, idx)
        )
        written_all.extend(
            clean_one(src, out_base, args.outdir, args.strength, formats, args.quality)
        )
        print()

    print("Done. %d file(s) written to %s" % (len(written_all), os.path.abspath(args.outdir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
