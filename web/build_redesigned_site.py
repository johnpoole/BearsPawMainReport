from __future__ import annotations

import argparse
import json
import re
from datetime import date
from datetime import datetime
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


def _compute_level1_title_ranges(toc: list[TocEntry], last_page: int) -> dict[str, tuple[int, int]]:
    """Compute (start,end) page ranges for *all* level-1 outline entries.

    We use this to ensure sections like "Executive Summary" stop before
    "Table of Contents" even if we filter TOC pages from the website nav.
    """

    level1 = [e for e in toc if e.level == 1]
    ranges = _compute_ranges(level1, last_page)
    return {e.title: (e.page, end) for e, end in ranges}


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


_STRIP_LINE_PATTERNS = [
    re.compile(r"^\s*Attachment\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*IP\d{4}-\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*ISC:\s*Unrestricted\s*$", re.IGNORECASE),
    # TOC/List headers that occasionally bleed into adjacent extracts.
    re.compile(r"^\s*TABLE\s+OF\s+CONTENTS\s*$", re.IGNORECASE),
    re.compile(r"^\s*LIST\s+OF\s+TABLES\s*$", re.IGNORECASE),
    re.compile(r"^\s*LIST\s+OF\s+FIGURES\s*$", re.IGNORECASE),
    # Common TOC column labels.
    re.compile(r"^\s*SECTION\s*$", re.IGNORECASE),
    re.compile(r"^\s*PAGE\s+NO\.?\s*$", re.IGNORECASE),
]


def _clean_extracted_text(text: str) -> str:
    out_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if any(p.match(line) for p in _STRIP_LINE_PATTERNS):
            continue
        out_lines.append(line)
    cleaned = "\n".join(out_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def _get_range_for_title(
    *,
    ranges_all_level1: dict[str, tuple[int, int]],
    title: str,
    last_page: int,
) -> tuple[int, int] | None:
    """Return a safe (start,end) range for a title.

    Some PDFs have multiple outline entries pointing at the same physical PDF
    page (notably "Executive Summary" → TOC page). For the landing page we
    prefer content immediately before the TOC if that happens.
    """

    if title not in ranges_all_level1:
        return None

    start, end = ranges_all_level1[title]

    if title == "Executive Summary":
        toc_start = ranges_all_level1.get("Table of Contents", (0, 0))[0]
        if toc_start:
            if start >= toc_start and toc_start - 1 >= 1:
                start = toc_start - 1
            if toc_start - 1 >= 1:
                end = min(end, toc_start - 1)

    start = max(1, min(start, last_page))
    end = max(start, min(end, last_page))
    return start, end


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
    # Minimal text → HTML with basic bullet list support.
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    html_blocks: list[str] = []
    for p in paras:
        lines = [l.strip() for l in p.splitlines() if l.strip()]
        bullet_lines = [l for l in lines if l.startswith("•")]

        if bullet_lines and len(bullet_lines) >= max(2, len(lines) // 2):
            items = [f"<li>{esc(l.lstrip('•').strip())}</li>" for l in bullet_lines]
            html_blocks.append("<ul>" + "".join(items) + "</ul>")
            non_bullets = [l for l in lines if not l.startswith("•")]
            if non_bullets:
                html_blocks.append(f"<p>{esc(' '.join(non_bullets))}</p>")
            continue

        escaped = esc(p).replace("\n", "<br/>")
        html_blocks.append(f"<p>{escaped}</p>")

    return "\n".join(html_blocks)


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
    parser.add_argument("--out", default=".", help="Output folder (repo root recommended).")
    parser.add_argument("--max-pages", type=int, default=0, help="Optional cap to reduce extraction time")
    parser.add_argument(
        "--timeline-events",
        default="data/timeline-events.json",
        help="Path to curated timeline events JSON (list of objects). The timeline page always uses this file (no auto date extraction).",
    )
    parser.add_argument(
        "--entities",
        default="data/entities.json",
        help="Path to curated people/orgs graph JSON with {nodes:[], links:[]}. This page is curated (no auto extraction).",
    )
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

    # Copy source stylesheet into the output (so the site can be generated into repo root).
    script_dir = Path(__file__).resolve().parent
    source_css = script_dir / "assets" / "style.css"
    if source_css.exists():
        (assets_dir / "style.css").write_text(source_css.read_text(encoding="utf-8"), encoding="utf-8")

    toc = _load_outline_toc(Path(args.structure))
    doc = fitz.open(pdf_path)
    last_page = doc.page_count
    if args.max_pages and args.max_pages > 0:
        last_page = min(last_page, args.max_pages)

    main_entries = _filter_main_report_entries(toc)
    appendix_entries = _get_appendix_entries(toc)

    # Explicit mapping from report outline to website pages.
    page_defs = [
        ("overview", "Overview", ["Executive Summary"]),
        ("timeline", "Timeline", ["Timeline"]),
        ("people-orgs", "People & Orgs", ["People & Orgs"]),
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

    # Use *full* level-1 outline (including TOC/lists) for accurate boundaries.
    ranges_all_level1 = _compute_level1_title_ranges(toc, last_page)

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
            rng = _get_range_for_title(ranges_all_level1=ranges_all_level1, title=t, last_page=last_page)
            if not rng:
                continue
            start, end = rng
            out[t] = _clean_extracted_text(_extract_text_range(doc, start, end))
        return out

    # Build pages.
    for slug, label, section_titles in page_defs:
        in_pages_dir = slug != "overview"

        if slug == "timeline":
            timeline_path = Path(args.timeline_events)
            if not timeline_path.exists():
                raise SystemExit(
                    f"Missing curated timeline events JSON: {timeline_path}. "
                    "Create it (data/timeline-events.json) or pass --timeline-events <path>."
                )

            events_obj = json.loads(timeline_path.read_text(encoding="utf-8"))
            if not isinstance(events_obj, list):
                raise SystemExit("Timeline events JSON must be a list of objects")

            # Minimal normalization: ensure required keys exist.
            norm: list[dict] = []
            for e in events_obj:
                if not isinstance(e, dict):
                    continue
                if not (e.get("date") or e.get("when")):
                    continue
                when = e.get("when")
                if not when and e.get("date"):
                    try:
                        dt = date.fromisoformat(str(e["date"]))
                        when = dt.strftime("%b %d, %Y")
                    except Exception:
                        when = str(e.get("date"))
                norm.append(
                    {
                        "date": str(e.get("date") or ""),
                        "when": str(when or ""),
                        "title": str(e.get("title") or when or ""),
                        "description": str(e.get("description") or ""),
                        "sourceSection": str(e.get("sourceSection") or "Report"),
                        "sourcePage": int(e.get("sourcePage") or 0),
                    }
                )

            # Sort by ISO date when available; otherwise keep file order.
            if all((n.get("date") or "").count("-") == 2 for n in norm):
                norm.sort(key=lambda x: x.get("date") or "")

            events = norm
            events_json = json.dumps(events, ensure_ascii=False)

            body = f"""
<h1>{label}</h1>
<p class=\"meta\">Curated key dated moments from the report, displayed as an interactive timeline.</p>

<div class=\"callout\">
    <div id=\"timeline\" class=\"timeline\"></div>
    <div id=\"timeline-tooltip\" class=\"timeline-tooltip\" style=\"display:none\"></div>
</div>

<script src=\"https://d3js.org/d3.v7.min.js\"></script>
<script>
    const events = {events_json};

    (function renderTimeline() {{
        const root = document.getElementById('timeline');
        const tooltip = document.getElementById('timeline-tooltip');
        if (!root || !window.d3) return;

        const data = (events || []).slice();

        if (!data.length) {{
            root.innerHTML = '<p>No dated events found in the processed page range.</p>';
            return;
        }}

        const margin = {{top: 18, right: 18, bottom: 18, left: 26}};
        const rowH = 44;
        const width = Math.max(720, root.clientWidth || 720);
        const height = margin.top + margin.bottom + (rowH * (data.length - 1)) + 20;

        root.innerHTML = '';
        const svg = d3.select(root)
            .append('svg')
            .attr('viewBox', `0 0 ${{width}} ${{height}}`)
            .style('width', '100%')
            .style('height', 'auto');

        const lineX = margin.left + 12;
        const y = (i) => margin.top + (i * rowH);

        svg.append('line')
            .attr('x1', lineX)
            .attr('x2', lineX)
            .attr('y1', y(0))
            .attr('y2', y(data.length - 1))
            .attr('class', 'timeline-axis');

        const g = svg.append('g');
        const nodes = g.selectAll('g.node')
            .data(data)
            .enter()
            .append('g')
            .attr('class', 'node')
            .attr('transform', (d, i) => `translate(0,${{y(i)}})`);

        nodes.append('circle')
            .attr('cx', lineX)
            .attr('cy', 0)
            .attr('r', 6)
            .attr('class', 'timeline-dot')
            .on('mouseenter', (evt, d) => {{
                tooltip.style.display = 'block';
                tooltip.innerHTML = `<strong>${{d.when}}</strong><br/>${{d.description}}<br/><span class=\"muted\">${{d.sourceSection}} (p${{d.sourcePage}})</span>`;
            }})
            .on('mousemove', (evt) => {{
                tooltip.style.left = (evt.pageX + 12) + 'px';
                tooltip.style.top = (evt.pageY + 12) + 'px';
            }})
            .on('mouseleave', () => {{
                tooltip.style.display = 'none';
            }});

        nodes.append('text')
            .attr('x', lineX + 16)
            .attr('y', -4)
            .attr('class', 'timeline-label')
            .text(d => d.title);

        nodes.append('text')
            .attr('x', lineX + 16)
            .attr('y', 14)
            .attr('class', 'timeline-when')
            .text(d => d.when);
    }})();
</script>
            """

            html_out = _render_shell(
                title=f"{label} — BearsPaw Main Report",
                nav_html=nav_html(slug, in_pages_dir=True),
                body_html=body,
                rel_prefix="../",
            )
            (pages_dir / f"{slug}.html").write_text(html_out, encoding="utf-8")
            continue

        if slug == "people-orgs":
            entities_path = Path(args.entities)
            if not entities_path.exists():
                raise SystemExit(
                    f"Missing curated entities JSON: {entities_path}. "
                    "Create it (data/entities.json) or pass --entities <path>."
                )

            entities_obj = json.loads(entities_path.read_text(encoding="utf-8"))
            if not isinstance(entities_obj, dict):
                raise SystemExit("Entities JSON must be an object with keys: nodes, links")
            nodes_obj = entities_obj.get("nodes")
            links_obj = entities_obj.get("links")
            if not isinstance(nodes_obj, list) or not isinstance(links_obj, list):
                raise SystemExit("Entities JSON must contain 'nodes' (list) and 'links' (list)")

            # Minimal normalization.
            nodes: list[dict] = []
            for n in nodes_obj:
                if not isinstance(n, dict):
                    continue
                nid = str(n.get("id") or "").strip()
                if not nid:
                    continue
                ntype = str(n.get("type") or "org").strip().lower()
                if ntype not in {"person", "org"}:
                    ntype = "org"
                name = str(n.get("name") or nid).strip()
                role = str(n.get("role") or "").strip()
                nodes.append({"id": nid, "type": ntype, "name": name, "role": role})

            node_ids = {n["id"] for n in nodes}
            links: list[dict] = []
            for l in links_obj:
                if not isinstance(l, dict):
                    continue
                src = str(l.get("source") or "").strip()
                tgt = str(l.get("target") or "").strip()
                if not src or not tgt:
                    continue
                if src not in node_ids or tgt not in node_ids:
                    continue
                rel = str(l.get("relation") or "related to").strip()
                links.append({"source": src, "target": tgt, "relation": rel})

            entities_json = json.dumps({"nodes": nodes, "links": links}, ensure_ascii=False)

            # Simple list for accessibility / quick scanning.
            rows = []
            for n in sorted(nodes, key=lambda x: (x.get("type") or "", x.get("name") or "")):
                kind = "Person" if n.get("type") == "person" else "Organization"
                rows.append(
                    f"<tr><td>{kind}</td><td>{n.get('name')}</td><td class=\"muted\">{n.get('role')}</td></tr>"
                )
            table_html = (
                "<table class=\"entity-table\"><thead><tr>"
                "<th>Type</th><th>Name</th><th>Role</th></tr></thead><tbody>"
                + "".join(rows)
                + "</tbody></table>"
            )

            body = f"""
<h1>{label}</h1>
<p class=\"meta\">Curated list of people and organizations mentioned in the report, plus how they relate.</p>

<div class=\"callout\">
    <div id=\"entity-graph\" class=\"entity-graph\"></div>
    <div id=\"entity-tooltip\" class=\"entity-tooltip\" style=\"display:none\"></div>
</div>

<h2>Entities</h2>
{table_html}

<script src=\"https://d3js.org/d3.v7.min.js\"></script>
<script>
    const graphData = {entities_json};

    (function renderEntityGraph() {{
        const root = document.getElementById('entity-graph');
        const tooltip = document.getElementById('entity-tooltip');
        if (!root || !window.d3) return;

        const nodes = (graphData.nodes || []).map(d => Object.assign({{}}, d));
        const links = (graphData.links || []).map(d => Object.assign({{}}, d));
        if (!nodes.length) {{
            root.innerHTML = '<p>No curated entities found.</p>';
            return;
        }}

        root.innerHTML = '';
        const w = Math.max(720, root.clientWidth || 720);
        const h = 520;

        const svg = d3.select(root)
            .append('svg')
            .attr('viewBox', `0 0 ${{w}} ${{h}}`)
            .style('width', '100%')
            .style('height', 'auto');

        const link = svg.append('g')
            .attr('class', 'entity-links')
            .selectAll('line')
            .data(links)
            .enter()
            .append('line')
            .attr('class', 'entity-link');

        const node = svg.append('g')
            .attr('class', 'entity-nodes')
            .selectAll('g')
            .data(nodes)
            .enter()
            .append('g')
            .attr('class', 'entity-node')
            .call(d3.drag()
                .on('start', (event, d) => {{
                    if (!event.active) sim.alphaTarget(0.25).restart();
                    d.fx = d.x;
                    d.fy = d.y;
                }})
                .on('drag', (event, d) => {{
                    d.fx = event.x;
                    d.fy = event.y;
                }})
                .on('end', (event, d) => {{
                    if (!event.active) sim.alphaTarget(0);
                    d.fx = null;
                    d.fy = null;
                }})
            );

        node.append('circle')
            .attr('r', d => d.type === 'person' ? 7 : 9)
            .attr('class', d => d.type === 'person' ? 'entity-dot entity-dot-person' : 'entity-dot entity-dot-org')
            .on('mouseenter', (evt, d) => {{
                if (!tooltip) return;
                const role = d.role ? `<br/><span class=\"muted\">${{d.role}}</span>` : '';
                tooltip.style.display = 'block';
                tooltip.innerHTML = `<strong>${{d.name}}</strong>${{role}}`;
            }})
            .on('mousemove', (evt) => {{
                if (!tooltip) return;
                tooltip.style.left = (evt.pageX + 12) + 'px';
                tooltip.style.top = (evt.pageY + 12) + 'px';
            }})
            .on('mouseleave', () => {{
                if (!tooltip) return;
                tooltip.style.display = 'none';
            }});

        node.append('text')
            .attr('class', 'entity-label')
            .attr('x', 12)
            .attr('y', 4)
            .text(d => d.name);

        const sim = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(d => d.id).distance(110))
            .force('charge', d3.forceManyBody().strength(-240))
            .force('center', d3.forceCenter(w / 2, h / 2))
            .force('collide', d3.forceCollide().radius(d => d.type === 'person' ? 24 : 28));

        const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
        const nodePad = (d) => d.type === 'person' ? 26 : 30; // includes dot + label offset buffer

        sim.on('tick', () => {{
            // Keep nodes inside the visible area.
            nodes.forEach((d) => {{
                const pad = nodePad(d);
                d.x = clamp(d.x, pad, w - pad);
                d.y = clamp(d.y, pad, h - pad);
            }});

            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);

            node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
        }});
    }})();
</script>
            """

            html_out = _render_shell(
                title=f"{label} — BearsPaw Main Report",
                nav_html=nav_html(slug, in_pages_dir=True),
                body_html=body,
                rel_prefix="../",
            )
            (pages_dir / f"{slug}.html").write_text(html_out, encoding="utf-8")
            continue

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
            rng = _get_range_for_title(ranges_all_level1=ranges_all_level1, title=t, last_page=last_page)
            if not rng:
                continue
            start, end = rng
            if start > last_page:
                continue
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
                (
                    f"<a class=\"pill\" href=\"pages/{slug2}.html\">{lbl}</a>"
                    if slug2 != "overview" else ""
                )
                for slug2, lbl, _ in page_defs
                if lbl != "Overview"
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
