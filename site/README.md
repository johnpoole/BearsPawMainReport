# BearsPawMainReport website

This folder contains a static HTML website generated from the PDF.

## Generate

From the repo root:

```powershell
C:/Users/jdpoo/Documents/GitHub/BearsPawMainReport/.venv/Scripts/python.exe site/build_pdf_site.py --pdf "Bearspaw South Feeder Main Investigation Report - IP2024-1237.pdf" --out site --scale 1.5 --start 1 --end 20
```

- Increase `--end` up to the full page count (596) when you're ready.

## Preview locally

```powershell
cd site
C:/Users/jdpoo/Documents/GitHub/BearsPawMainReport/.venv/Scripts/python.exe -m http.server 8000
```

Then open:
- http://localhost:8000/

## Notes

- This is **not** a PDF viewer. Each PDF page becomes its own HTML file with a rendered background image plus selectable text overlay.
- Generating all 596 pages can take time and will create many files.
