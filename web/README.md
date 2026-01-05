# Redesigned report website

This folder contains a **redesigned** static website that presents the report content in web-friendly sections (not a PDF viewer and not a page-by-page export).

## Build

From the repo root:

```powershell
./web/build.ps1 -PdfPath "C:\\path\\to\\your\\report.pdf"
```

The PDF is intentionally not committed to git. You can keep it anywhere on disk and pass its path to the build script.

## Preview locally

```powershell
./web/serve-8000.ps1
```

Then open:
- http://localhost:8000/

## One-step rebuild + preview

```powershell
./web/build-and-serve.ps1 -PdfPath "C:\\path\\to\\your\\report.pdf"
```
