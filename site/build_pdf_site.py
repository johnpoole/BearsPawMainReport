from __future__ import annotations

import argparse
import html
import os
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF


def _css_color_from_int(color: int) -> str:
    # PyMuPDF returns sRGB packed int (0xRRGGBB)
    return f"#{color & 0xFFFFFF:06x}"


def _iter_text_spans(page: fitz.Page) -> Iterable[dict]:
    # "rawdict" has more precise span data across versions.
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                yield span


def _write_index(out_dir: Path, page_count: int, start: int, end: int) -> None:
    links = []
    for page_num in range(start, end + 1):
        name = f"{page_num:04d}.html"
        links.append(f'<a href="pages/{name}">Page {page_num}</a>')

    index_html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\"/>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>
  <title>Report (pages {start}-{end})</title>
  <link rel=\"stylesheet\" href=\"assets/style.css\"/>
</head>
<body>
  <div class=\"topbar\"><div class=\"inner\">
    <strong>Report</strong>
    <span>Pages {start}–{end} (of {page_count})</span>
  </div></div>
  <div class=\"container\">
    <div class=\"index-list\">{''.join(links)}</div>
  </div>
</body>
</html>
"""
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")


def _write_page_html(
    *,
    out_pages_dir: Path,
    page_num: int,
    page_w: float,
    page_h: float,
    scale: float,
    image_rel_path: str,
    spans: list[dict],
    total_pages: int,
) -> None:
    css_w = page_w * scale
    css_h = page_h * scale

    prev_link = f"{page_num - 1:04d}.html" if page_num > 1 else None
    next_link = f"{page_num + 1:04d}.html" if page_num < total_pages else None

    nav_bits = [
        '<a href="../index.html">Index</a>',
        f"<span>Page {page_num} / {total_pages}</span>",
    ]
    if prev_link:
        nav_bits.insert(1, f'<a href="{prev_link}">Prev</a>')
    if next_link:
        nav_bits.append(f'<a href="{next_link}">Next</a>')

    span_divs: list[str] = []
    for span in spans:
        x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
        text = span.get("text", "")
        if not text:
            continue

        size = float(span.get("size", 10.0)) * scale
        color = _css_color_from_int(int(span.get("color", 0)))

        left = x0 * scale
        top = y0 * scale
        width = max((x1 - x0) * scale, 0.0)
        height = max((y1 - y0) * scale, 0.0)

        safe = html.escape(text)
        style = (
            f"left:{left:.3f}px;top:{top:.3f}px;"
            f"width:{width:.3f}px;height:{height:.3f}px;"
            f"font-size:{size:.3f}px;color:{color};"
        )
        span_divs.append(f'<span class="txt" style="{style}">{safe}</span>')

    page_html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\"/>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>
  <title>Page {page_num}</title>
  <link rel=\"stylesheet\" href=\"../assets/style.css\"/>
</head>
<body>
  <div class=\"topbar\"><div class=\"inner\">
    {' '.join(nav_bits)}
  </div></div>

  <div class=\"page-wrap\">
    <div class=\"page\" style=\"width:{css_w:.3f}px;height:{css_h:.3f}px\">
      <img class=\"bg\" alt=\"Page {page_num}\" src=\"../{image_rel_path}\" width=\"{css_w:.0f}\" height=\"{css_h:.0f}\"/>
      {''.join(span_divs)}
    </div>
  </div>
</body>
</html>
"""

    (out_pages_dir / f"{page_num:04d}.html").write_text(page_html, encoding="utf-8")


def _save_page_image(page: fitz.Page, out_path: Path, scale: float, jpg_quality: int) -> None:
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # PyMuPDF supports jpg_quality on newer versions; keep a safe fallback.
    try:
        pix.save(str(out_path), jpg_quality=jpg_quality)
    except TypeError:
        pix.save(str(out_path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a PDF into a static HTML website (no PDF viewer).")
    parser.add_argument("--pdf", required=True, help="Path to input PDF")
    parser.add_argument("--out", required=True, help="Output site directory (will write index.html, pages/, assets/)")
    parser.add_argument("--scale", type=float, default=1.5, help="Render scale (1.0=72dpi, 2.0=144dpi-ish)")
    parser.add_argument("--jpg-quality", type=int, default=70, help="JPEG quality (1-100)")
    parser.add_argument("--start", type=int, default=1, help="Start page number (1-based)")
    parser.add_argument("--end", type=int, default=0, help="End page number (1-based); 0 means last")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    out_dir = Path(args.out)
    out_pages_dir = out_dir / "pages"
    out_img_dir = out_dir / "assets" / "page-images"

    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    out_pages_dir.mkdir(parents=True, exist_ok=True)
    out_img_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count

    start = max(1, int(args.start))
    end = int(args.end) if int(args.end) > 0 else total_pages
    end = min(end, total_pages)

    if start > end:
        raise SystemExit("start must be <= end")

    # index.html links only the generated subset
    _write_index(out_dir, total_pages, start, end)

    for page_num in range(start, end + 1):
        page = doc[page_num - 1]
        page_w = float(page.rect.width)
        page_h = float(page.rect.height)

        img_name = f"{page_num:04d}.jpg"
        img_path = out_img_dir / img_name
        img_rel = f"assets/page-images/{img_name}"

        # Re-generate only if missing; keeps reruns fast.
        if not img_path.exists():
            _save_page_image(page, img_path, args.scale, args.jpg_quality)

        spans = list(_iter_text_spans(page))

        _write_page_html(
            out_pages_dir=out_pages_dir,
            page_num=page_num,
            page_w=page_w,
            page_h=page_h,
            scale=args.scale,
            image_rel_path=img_rel,
            spans=spans,
            total_pages=total_pages,
        )

        if page_num % 25 == 0:
            print(f"Generated page {page_num}/{end}")

    print(f"Done. Open {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
