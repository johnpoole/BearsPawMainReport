# Requirements & design plan — BearsPaw Main Report website

Date: 2026-01-04

## 1) Understanding / goal

You are **not** asking for a PDF viewer or a page-by-page export.

You want a **new website layout** that **presents the information contained in the PDF** as a structured, readable web experience.

That means:
- Content is reorganized into web pages (overview → details → evidence/appendices)
- Text becomes real HTML (searchable, copyable, accessible)
- Figures/tables become web images/components with captions
- Users navigate by topic/section, not by “page 1/596”

## 2) Source document structure (grounded in PDF outline)

Extracted from the PDF outline (table of contents) in [site/report-structure.md](site/report-structure.md):

### Main report sections
- Executive Summary
- 1 Introduction
  - 1.1 Scope of Work
  - 1.2 Background
  - 1.3 Investigation Summary
- 2 Bearspaw South Feedermain
  - 2.1 Description
  - 2.2 Design / Fabrication Details
  - 2.3 Pressure Rating
  - 2.4 AWWA Standards
- 3 Field Observations
  - 3.1 June 5, 2024 Rupture
  - 3.2 Phase 1 Repairs
- 4 Pump Operations Summary
- 5 Finite Element Analysis & Limit State Design
- 6 Electromagnetic Inspection Results
- 7 Stray Current Assessment
- 8 Environmental Investigation
  - 8.1 Soil Sample Assessment
  - 8.2 Geo-Environmental Assessment
- 9 Metallurgical Analysis
- 10 Mortar and Concrete Analysis
- 11 Live Load Assessment
- 12 Summary of Observations
- 13 Probable Cause
- Closure

### Appendices
- Appendix A — Bearspaw South Feedermain Break Initial Investigation (Associated Engineering)
- Appendix B — Pure Technologies Electromagnetic Inspection Results
- Appendix C — Corrosion Assessment of Initial Break (Corrpro)
- Appendix D — Forensic Investigation (Thurber Engineering)
- Appendix E — 2024 Soil Samples (City of Calgary)
- Appendix F — Geo-Environmental Review (Associated Engineering)
- Appendix G — Prestressing Wire & Steel Cylinder Testing (Pure Technologies)
- Appendix H — Concrete Assessment (Tetra Tech)

## 3) Audience & primary use cases

### Audiences
- Internal engineering/ops stakeholders needing fast understanding and traceability
- External stakeholders needing a clear narrative summary + evidence links

### Top tasks
- Understand what happened (rupture), timeline, and impact
- See the investigation summary and conclusions quickly
- Drill into supporting analyses (FEA, EM inspection, stray current, environmental, metallurgical, concrete)
- Locate source evidence (appendices) by topic

## 4) Information architecture (IA)

### Top-level navigation
- Overview
- Incident & Repairs
- System Background
- Analyses
- Findings
- Probable Cause
- Appendices

### Page map (site structure)
1. **Overview (Home)**
   - Executive Summary (as the page hero content)
   - Key findings highlights (bullets)
   - Quick links to: Probable Cause, Summary of Observations, Incident & Repairs, Analyses

2. **Incident & Repairs**
   - 3.1 June 5, 2024 Rupture
   - 3.2 Phase 1 Repairs
   - Embedded media: photos/figures from Field Observations with captions
   - Timeline component (simple, linear)

3. **System Background**
   - 1.2 Background
   - 2 Bearspaw South Feedermain
   - Specs and standards (2.2–2.4)
   - Tables rendered as HTML where possible (diameters, ratings, materials)

4. **Analyses (Hub page)**
   - Cards/links to each analysis area:
     - Pump Operations Summary
     - Finite Element Analysis & Limit State Design
     - Electromagnetic Inspection Results
     - Stray Current Assessment
     - Environmental Investigation (Soil + Geo-environmental)
     - Metallurgical Analysis
     - Mortar and Concrete Analysis
     - Live Load Assessment

5. **Analysis detail pages (one per section)**
   Each page follows the same template:
   - Purpose / what was assessed
   - Methods (bulleted)
   - Key results (callouts)
   - Figures & tables (gallery / inline)
   - “So what?” implications (short)
   - References: links into relevant appendix sections

6. **Findings**
   - 12 Summary of Observations
   - Clear grouping by theme (operations, structural, corrosion, environment, materials)

7. **Probable Cause**
   - 13 Probable Cause
   - Supporting evidence list linking back to analysis pages and appendices

8. **Appendices (library)**
   - Appendix list with:
     - short description
     - tags (e.g., EM inspection, corrosion, environment)
     - deep links to sections inside each appendix (optional phase)

## 5) Content transformation rules (PDF → web)

### Text
- Convert narrative text into semantic HTML (`h1/h2/h3`, `p`, `ul/ol`, `blockquote` where relevant)
- Maintain technical wording; do not paraphrase unless explicitly requested
- Preserve traceability: every web section includes “Source” links (appendix/page references)

### Figures
- Extract figure images and captions
- Present figures inline near the relevant narrative
- Provide click-to-open full resolution (new tab) and accessible `alt` text

### Tables
- Prefer real HTML tables for readability and copy/paste
- If a table is too complex, render as image with downloadable CSV (optional phase)

### Cross-references
- Convert “See Section X / Appendix Y” into actual hyperlinks

## 6) UX / layout design plan

### Layout principles
- Single-column reading width for narrative content
- Consistent section templates (especially for analysis pages)
- Strong hierarchy: title → summary → details → evidence

### Key templates
1. **Overview template**
   - Hero: report title + short subtitle
   - Executive summary content
   - “Key conclusions” callout
   - Navigation tiles

2. **Section page template**
   - Sticky local table-of-contents (right rail on desktop; collapsible on mobile)
   - “At a glance” summary block
   - Main content
   - Figures/tables
   - Sources / references block

3. **Appendix library template**
   - List of appendices
   - Each appendix page: summary + downloadable original appendix PDF (optional) + extracted key sections

### Accessibility requirements
- Keyboard navigable
- Semantic headings
- Sufficient contrast
- Images have `alt` text; figures have captions

## 7) Functional requirements

### Must have (MVP)
- A homepage/overview derived from Executive Summary
- A page for each main section (Intro, System, Field Observations, each Analysis section, Findings, Probable Cause)
- Basic navigation across pages
- Figures displayed with captions
- Appendix library page with links to each appendix

### Should have
- Search across site text
- Per-page mini-TOC
- Consistent “Sources” block per page

### Nice to have (explicitly not required unless you ask)
- Full-text search index (lunr/elastic)
- Interactive charts/tables
- Deep-linking into appendix sub-sections

## 8) Content production workflow (how we’ll build it)

1. Extract section text for each TOC section.
2. Identify and extract figures/tables per section.
3. Write web copy by restructuring into the templates above (without changing technical meaning).
4. Generate a static site (simple HTML or a framework if you prefer).

## 9) Open questions (only if you want to answer)

1. Should the public-facing site include the appendices verbatim, or only curated excerpts with a downloadable original?
2. Do you want a “stakeholder summary” tone (more narrative) or “engineering dossier” tone (more technical, dense)?
3. Any branding constraints (City of Calgary / corporate styles), or keep it neutral?
