from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


@dataclass(frozen=True)
class TocEntry:
    level: int
    title: str
    page: int  # 1-based


def _slugify(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"&", " and ", t)
    t = re.sub(r"[^a-z0-9]+", "-", t)
    t = re.sub(r"-+", "-", t).strip("-")
    if not t:
        return "section"
    return t


def _load_outline_toc(structure_json: Path) -> list[TocEntry]:
    data = json.loads(structure_json.read_text(encoding="utf-8"))
    out: list[TocEntry] = []
    for raw in data.get("outlineToc", []):
        out.append(TocEntry(int(raw["level"]), str(raw["title"]), int(raw["page"])))
    return out


def _filter_main_report_entries(toc: list[TocEntry]) -> list[TocEntry]:
    # Keep entries up to (but not including) the appendices.
    out: list[TocEntry] = []
    for e in toc:
        if e.title.lower().startswith("appendix"):
            break
        if e.title.lower() in {"table of contents", "list of tables", "list of figures"}:
            continue
        out.append(e)
    return out


def _get_appendix_entries(toc: list[TocEntry]) -> list[TocEntry]:
    return [e for e in toc if e.title.lower().startswith("appendix")]


def _compute_ranges(entries: list[TocEntry], last_page: int) -> list[tuple[TocEntry, int]]:
    # Returns (entry, end_page_inclusive)
    out: list[tuple[TocEntry, int]] = []
    for i, e in enumerate(entries):
        next_page = entries[i + 1].page if i + 1 < len(entries) else last_page + 1
        end_page = max(e.page, next_page - 1)
        out.append((e, end_page))
    return out


def _extract_text_range(doc: fitz.Document, start_page: int, end_page: int) -> str:
    # start/end are 1-based inclusive.
    chunks: list[str] = []
    for p in range(start_page, end_page + 1):
        page = doc.load_page(p - 1)
        txt = page.get_text("text")
        # Light cleanup: normalize line endings and collapse excessive whitespace.
        txt = txt.replace("\r\n", "\n").replace("\r", "\n")
        chunks.append(txt.strip())
    combined = "\n\n".join(c for c in chunks if c)
    combined = re.sub(r"\n{3,}", "\n\n", combined)
    return combined.strip() + "\n"


def _extract_images_for_range(
    *,
    doc: fitz.Document,
    start_page: int,
    end_page: int,
    out_dir: Path,
    section_slug: str,
    min_pixels: int = 120_000,
    max_images: int = 30,
) -> list[dict]:
    """Extract embedded raster images from a page range.

    Returns a list of dicts with: src (relative), caption.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[dict] = []
    seen_xrefs: set[int] = set()

    img_count = 0
    for p in range(start_page, end_page + 1):
        page = doc.load_page(p - 1)
        images = page.get_images(full=True)
        for idx, info in enumerate(images):
            xref = int(info[0])
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                img = doc.extract_image(xref)
            except Exception:
                continue

            width = int(img.get("width") or 0)
            height = int(img.get("height") or 0)
            if width * height < min_pixels:
                continue

            ext = (img.get("ext") or "png").lower()
            if ext not in {"png", "jpg", "jpeg"}:
                # Keep the scope tight; skip uncommon formats.
                continue

            img_bytes = img.get("image")
            if not img_bytes:
                continue

            filename = f"{section_slug}-p{p:03d}-{idx:02d}-x{xref}.{ext}"
            (out_dir / filename).write_bytes(img_bytes)

            extracted.append(
                {
                    "src": f"assets/figures/{filename}",
                    "caption": f"Extracted figure (source page {p})",
                }
            )

            img_count += 1
            if img_count >= max_images:
                return extracted

    return extracted


def _text_to_html_paragraphs(text: str) -> str:
    # Minimal text → HTML: split on blank lines, preserve line breaks within paragraphs.
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    html_paras: list[str] = []
    for p in paras:
        safe = (
            p.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        safe = safe.replace("\n", "<br/>")
        html_paras.append(f"<p>{safe}</p>")
    return "\n".join(html_paras)


def _render_shell(*, title: str, nav_html: str, body_html: str, rel_prefix: str) -> str:
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\"/>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>
  <title>{title}</title>
  <link rel=\"stylesheet\" href=\"{rel_prefix}assets/style.css\"/>
</head>
<body>
  <div class=\"shell\">
    <nav class=\"nav\">
      <div class=\"brand\">BearsPaw Main Report</div>
      <small>Redesigned web presentation</small>
      {nav_html}
    </nav>
    <main class=\"main\"><div class=\"content\">
      {body_html}
    </div></main>
  </div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a redesigned static website from the report PDF.")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--structure", required=True, help="Path to report-structure.json")
    parser.add_argument("--out", required=True, help="Output folder (web/) containing pages/ and assets/")
    parser.add_argument("--max-pages", type=int, default=0, help="Optional cap to reduce extraction time")
    # Intentionally no option to link/copy the source PDF into the website output.
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    out_dir = Path(args.out)
    pages_dir = out_dir / "pages"
    content_dir = out_dir / "content"
    assets_dir = out_dir / "assets"
    figures_dir = assets_dir / "figures"

    out_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    content_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    toc = _load_outline_toc(Path(args.structure))
    doc = fitz.open(pdf_path)
    last_page = doc.page_count
    if args.max_pages and args.max_pages > 0:
        last_page = min(last_page, args.max_pages)

    main_entries = _filter_main_report_entries(toc)
    appendix_entries = _get_appendix_entries(toc)

    # Build nav using level-1 headings as primary pages.
    level1 = [e for e in main_entries if e.level == 1]

    # Explicit mapping from report outline to website pages.
    page_defs = [
        ("overview", "Overview", ["Executive Summary"]),
        ("incident-repairs", "Incident & Repairs", ["3 Field Observations"]),
        ("system-background", "System Background", ["1 Introduction", "2 Bearspaw South Feedermain"]),
        ("analyses", "Analyses", [
            "4 Pump Operations Summary",
            "5 Finite Element Analysis & Limit State Design",
            "6 Electromagnetic Inspection Results",
            "7 Stray Current Assessment",
            "8 Environmental Investigation",
            "9 Metallurgical Analysis",
            "10 Mortar and Concrete Analysis",
            "11 Live Load Assessment",
        ]),
        ("findings", "Findings", ["12 Summary of Observations"]),
        ("probable-cause", "Probable Cause", ["13 Probable Cause"]),
        ("appendices", "Appendices", ["Appendices"]),
    ]

    # Precompute ranges for level-1 entries (and closure) to allow extraction by section title.
    ranges = {e.title: (e.page, end) for e, end in _compute_ranges(level1, last_page)}

    def nav_html(active_slug: str, *, in_pages_dir: bool) -> str:
        items = []
        for slug, label, _ in page_defs:
            if slug == "overview":
                href = "../index.html" if in_pages_dir else "index.html"
            else:
                href = f"{slug}.html" if in_pages_dir else f"pages/{slug}.html"
            prefix = "→ " if slug == active_slug else ""
            items.append(f'<li>{prefix}<a href="{href}">{label}</a></li>')
        return "<ul>" + "\n".join(items) + "</ul>"

    # Write content extracts for each named section we’ll include.
    def extract_sections(section_titles: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for t in section_titles:
            if t == "Appendices":
                continue
            if t not in ranges:
                continue
            start, end = ranges[t]
            out[t] = _extract_text_range(doc, start, min(end, last_page))
        return out

    # Build pages.
    for slug, label, section_titles in page_defs:
        in_pages_dir = slug != "overview"
        if slug == "appendices":
            appendix_list = "\n".join(
                f"<li>{e.title} (starts p{e.page})</li>" for e in appendix_entries
            )

            body = f"""
<h1>{label}</h1>
<p class=\"meta\">Evidence library from the report.</p>
<div class=\"callout\">
  <p>This site organizes the report content; appendices remain the primary evidence source.</p>
</div>
<h2>Appendix list</h2>
<ul>
{appendix_list}
</ul>
"""
            html_out = _render_shell(
                title=f"{label} — BearsPaw Main Report",
                nav_html=nav_html(slug, in_pages_dir=in_pages_dir),
                body_html=body,
                rel_prefix="../",
            )
            (pages_dir / f"{slug}.html").write_text(html_out, encoding="utf-8")
            continue

        extracts = extract_sections(section_titles)
        # Persist raw extracts for traceability.
        for title, txt in extracts.items():
            (content_dir / f"{_slugify(title)}.txt").write_text(txt, encoding="utf-8")

        # Render body.
        body_bits = [f"<h1>{label}</h1>"]
        body_bits.append("<p class=\"meta\">Content extracted from the report and organized for web reading.</p>")

        # Extract some figures from the relevant page ranges and show as a gallery.
        # For the hub pages (Analyses/System Background/Incident) we extract from the combined ranges.
        figure_items: list[dict] = []
        for t in section_titles:
            if t == "Appendices":
                continue
            if t not in ranges:
                continue
            start, end = ranges[t]
            if start > last_page:
                continue
            end = min(end, last_page)
            figure_items.extend(
                _extract_images_for_range(
                    doc=doc,
                    start_page=start,
                    end_page=end,
                    out_dir=figures_dir,
                    section_slug=_slugify(t),
                    min_pixels=160_000,
                    max_images=10 if slug == "overview" else 20,
                )
            )
            if len(figure_items) >= 20:
                break

        if slug == "overview":
            es = extracts.get("Executive Summary", "")
            body_bits.append("<div class=\"callout\"><h2>Executive Summary</h2>")
            body_bits.append(_text_to_html_paragraphs(es[:12000] if es else ""))
            body_bits.append("</div>")
            if figure_items:
                body_bits.append("<h2>Figures (extracted)</h2>")
                gallery = "\n".join(
                    f"<figure><a target=\"_blank\" href=\"{fi['src']}\"><img src=\"{fi['src']}\" alt=\"{fi['caption']}\"/></a><figcaption>{fi['caption']}</figcaption></figure>"
                    for fi in figure_items[:8]
                )
                body_bits.append(f"<div class=\"gallery\">{gallery}</div>")
            body_bits.append("<h2>Quick links</h2>")
            body_bits.append("<div class=\"pills\">" + "".join(
                f"<span class=\"pill\">{lbl}</span>" for _, lbl, _ in page_defs if lbl != "Overview"
            ) + "</div>")
        else:
            if figure_items:
                body_bits.append("<div class=\"callout\"><h2>Figures (extracted)</h2>")
                gallery = "\n".join(
                    f"<figure><a target=\"_blank\" href=\"../{fi['src']}\"><img src=\"../{fi['src']}\" alt=\"{fi['caption']}\"/></a><figcaption>{fi['caption']}</figcaption></figure>"
                    for fi in figure_items[:12]
                )
                body_bits.append(f"<div class=\"gallery\">{gallery}</div></div>")
            for t in section_titles:
                txt = extracts.get(t, "")
                if not txt:
                    continue
                body_bits.append(f"<h2>{t}</h2>")
                body_bits.append(_text_to_html_paragraphs(txt))

        html_out = _render_shell(
            title=f"{label} — BearsPaw Main Report",
            nav_html=nav_html(slug, in_pages_dir=in_pages_dir),
            body_html="\n".join(body_bits),
            rel_prefix="../" if in_pages_dir else "",
        )

        if slug == "overview":
            (out_dir / "index.html").write_text(html_out, encoding="utf-8")
        else:
            (pages_dir / f"{slug}.html").write_text(html_out, encoding="utf-8")

    print(f"Built redesigned site: {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
