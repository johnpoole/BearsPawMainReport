from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


TOC_LINE_RE = re.compile(r"^(?P<title>.+?)\s+(?P<page>\d{1,4})\s*$")
SECTION_PREFIX_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s+\S+")


@dataclass(frozen=True)
class TocEntry:
    level: int
    title: str
    page: int


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" \t\r\n\u00a0")


def _extract_outline_toc(doc: fitz.Document) -> list[TocEntry]:
    toc = doc.get_toc(simple=True)
    out: list[TocEntry] = []
    for level, title, page in toc:
        title = _clean_line(str(title))
        if title:
            out.append(TocEntry(int(level), title, int(page)))
    return out


def _find_toc_pages_by_text(doc: fitz.Document, search_max_pages: int) -> list[int]:
    targets = ["table of contents", "contents"]
    found: list[int] = []
    for i in range(min(search_max_pages, doc.page_count)):
        txt = doc.load_page(i).get_text("text").lower()
        if any(t in txt for t in targets):
            found.append(i)
    return found


def _parse_toc_like_lines(text: str) -> list[dict]:
    lines = [_clean_line(l) for l in text.splitlines()]
    entries: list[dict] = []
    for line in lines:
        if len(line) < 6:
            continue
        m = TOC_LINE_RE.match(line)
        if not m:
            continue
        title = _clean_line(m.group("title").rstrip(".·"))
        page = int(m.group("page"))
        if not title or title.isdigit():
            continue
        # Avoid obvious false positives like "Figure 1 12" if desired, but keep for now.
        entries.append({"title": title, "page": page})
    return entries


def _extract_big_text_candidates(doc: fitz.Document, page_max: int) -> list[dict]:
    # Heuristic: on each page, treat spans bigger than median+3 as headings.
    candidates: list[dict] = []

    for page_index in range(min(page_max, doc.page_count)):
        page = doc.load_page(page_index)
        raw = page.get_text("rawdict")
        sizes: list[float] = []
        spans: list[dict] = []

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = _clean_line(span.get("text", ""))
                    if not text:
                        continue
                    size = float(span.get("size", 0.0))
                    sizes.append(size)
                    spans.append({"text": text, "size": size})

        if not sizes:
            continue

        sizes_sorted = sorted(sizes)
        median = sizes_sorted[len(sizes_sorted) // 2]
        threshold = median + 3.0

        # Keep unique headings per page, preserving order.
        seen = set()
        for span in spans:
            if span["size"] < threshold:
                continue
            text = span["text"]
            if len(text) < 4:
                continue
            if text in seen:
                continue
            seen.add(text)
            candidates.append({
                "page": page_index + 1,
                "text": text,
                "size": span["size"],
            })

    return candidates


def _summarize_section_numbering(doc: fitz.Document, page_max: int) -> dict:
    # Pull common section prefixes like 1, 1.1, 2.3.4
    counter: Counter[str] = Counter()
    examples: dict[str, str] = {}

    for page_index in range(min(page_max, doc.page_count)):
        txt = doc.load_page(page_index).get_text("text")
        for raw_line in txt.splitlines():
            line = _clean_line(raw_line)
            if not line:
                continue
            m = SECTION_PREFIX_RE.match(line)
            if not m:
                continue
            num = m.group("num")
            counter[num] += 1
            examples.setdefault(num, line[:140])

    top = counter.most_common(50)
    return {
        "topPrefixes": [{"prefix": k, "count": v, "example": examples.get(k, "")} for k, v in top],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract structure cues (TOC/headings) from a PDF.")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--search-max-pages", type=int, default=40)
    parser.add_argument("--sample-pages", type=int, default=60)
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    doc = fitz.open(pdf_path)

    outline_toc = _extract_outline_toc(doc)
    toc_pages = _find_toc_pages_by_text(doc, args.search_max_pages)

    toc_like_entries: list[dict] = []
    for idx in toc_pages[:3]:
        txt = doc.load_page(idx).get_text("text")
        toc_like_entries.extend(_parse_toc_like_lines(txt))

    big_text = _extract_big_text_candidates(doc, args.sample_pages)
    section_nums = _summarize_section_numbering(doc, args.sample_pages)

    result = {
        "pdf": str(pdf_path),
        "pageCount": doc.page_count,
        "metadata": {k: v for k, v in (doc.metadata or {}).items() if v},
        "outlineToc": [e.__dict__ for e in outline_toc],
        "tocPagesByText": [p + 1 for p in toc_pages],
        "tocLikeEntriesFromTocPages": toc_like_entries,
        "bigTextCandidates": big_text,
        "sectionNumbering": section_nums,
    }

    Path(args.out_json).write_text(json.dumps(result, indent=2), encoding="utf-8")

    md_lines: list[str] = []
    md_lines.append(f"# Extracted structure summary\n")
    md_lines.append(f"- PDF: {pdf_path.name}")
    md_lines.append(f"- Pages: {doc.page_count}")
    if result["metadata"]:
        md_lines.append(f"- Metadata: {result['metadata']}")

    md_lines.append("\n## Outline TOC (if present)\n")
    if outline_toc:
        for e in outline_toc[:120]:
            indent = "  " * (e.level - 1)
            md_lines.append(f"- {indent}p{e.page}: {e.title}")
    else:
        md_lines.append("- (No PDF outline TOC found)")

    md_lines.append("\n## TOC pages detected by text\n")
    if toc_pages:
        md_lines.append("- " + ", ".join(str(p + 1) for p in toc_pages[:10]) + (" ..." if len(toc_pages) > 10 else ""))
    else:
        md_lines.append("- (No TOC page detected in first scan window)")

    md_lines.append("\n## TOC-like entries parsed from detected TOC pages\n")
    if toc_like_entries:
        for e in toc_like_entries[:80]:
            md_lines.append(f"- p{e['page']}: {e['title']}")
    else:
        md_lines.append("- (No TOC-like lines parsed)")

    md_lines.append("\n## Big-text candidates (heading heuristic)\n")
    if big_text:
        for c in big_text[:80]:
            md_lines.append(f"- p{c['page']} (size {c['size']:.1f}): {c['text']}")
    else:
        md_lines.append("- (No big-text candidates found)")

    md_lines.append("\n## Section numbering prefixes (first sample pages)\n")
    prefixes = result["sectionNumbering"].get("topPrefixes", [])
    if prefixes:
        for item in prefixes[:30]:
            md_lines.append(f"- {item['prefix']} (x{item['count']}): {item['example']}")
    else:
        md_lines.append("- (No section numbering patterns detected)")

    Path(args.out_md).write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Wrote {args.out_json} and {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
