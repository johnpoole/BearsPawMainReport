from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz  # PyMuPDF

# Reuse the TOC loader and slugify from the site generator.
from build_redesigned_site import _load_outline_toc, _compute_level1_title_ranges, _slugify  # type: ignore


def _norm_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def extract_level1_to_files(*, pdf: Path, structure: Path, out_dir: Path, max_pages: int = 0) -> Path:
    toc = _load_outline_toc(structure)

    doc = fitz.open(pdf)
    last_page = doc.page_count
    if max_pages and max_pages > 0:
        last_page = min(last_page, max_pages)

    ranges = _compute_level1_title_ranges(toc, last_page)

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "pdf": str(pdf.name),
        "pageCount": doc.page_count,
        "extractedPageCap": last_page,
        "entries": [],
    }

    # Only level-1 entries, in order, excluding TOC/list pages.
    level1 = [e for e in toc if e.level == 1]

    for e in level1:
        title = e.title
        if title.lower() in {"table of contents", "list of tables", "list of figures"}:
            continue

        start, end = ranges[title]
        if start > last_page:
            continue
        end = min(end, last_page)

        slug = _slugify(title)
        filename = f"p{start:03d}-{slug}.txt"
        out_path = out_dir / filename

        with out_path.open("w", encoding="utf-8") as f:
            f.write(f"{title}\n")
            f.write(f"PAGES {start}-{end}\n\n")
            for p in range(start, end + 1):
                page = doc.load_page(p - 1)
                txt = _norm_newlines(page.get_text("text")).strip()
                if not txt:
                    continue
                f.write(f"\n[PAGE {p}]\n")
                f.write(txt)
                f.write("\n")

        manifest["entries"].append(
            {
                "title": title,
                "slug": slug,
                "startPage": start,
                "endPage": end,
                "file": filename,
            }
        )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main() -> int:
    ap = argparse.ArgumentParser(description="One-time full-text extraction of all level-1 sections (including appendices).")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--structure", required=True)
    ap.add_argument("--out", default="content_full")
    ap.add_argument("--max-pages", type=int, default=0, help="Optional cap for quicker runs")
    args = ap.parse_args()

    manifest = extract_level1_to_files(
        pdf=Path(args.pdf),
        structure=Path(args.structure),
        out_dir=Path(args.out),
        max_pages=args.max_pages,
    )
    print(f"Wrote manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
