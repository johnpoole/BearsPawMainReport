# Redesigned report website

This folder contains a **redesigned** static website that presents the report content in web-friendly sections (not a PDF viewer and not a page-by-page export).

## Build

From the repo root:

```powershell
& "C:/Users/jdpoo/Documents/GitHub/BearsPawMainReport/.venv/Scripts/python.exe" "web/build_redesigned_site.py" --pdf "Bearspaw South Feeder Main Investigation Report - IP2024-1237.pdf" --structure "site/report-structure.json" --out "web"
```

## Preview locally

```powershell
Set-Location web
& "C:/Users/jdpoo/Documents/GitHub/BearsPawMainReport/.venv/Scripts/python.exe" -m http.server 8001
```

Then open:
- http://localhost:8001/
