"""Print docs/apresentacao/slides.html to CyberGuard_Apresentacao_Final.pdf (16:9, 1280 x 720 px).

    python docs/apresentacao/build_pdf.py            # uses Chrome or Edge in headless mode
    set CHROME=C:\\path\\to\\chrome.exe               # optional: explicit browser

No network access and no new dependencies: the deck is self-contained and uses local
Windows fonts (Bahnschrift, Segoe UI), which the PDF embeds. If pypdf is installed,
the page count and the page size are checked after printing.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "slides.html"
OUTPUT = HERE / "CyberGuard_Apresentacao_Final.pdf"
EXPECTED_PAGES = 16
CANDIDATES = [
    os.environ.get("CHROME", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]


def browser() -> str:
    for path in CANDIDATES:
        if path and Path(path).is_file():
            return path
    raise SystemExit("FAIL: Chrome/Edge not found; set CHROME to the browser executable")


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"FAIL: {SOURCE} missing")
    with tempfile.TemporaryDirectory(prefix="cyberguard-pdf-") as profile:
        result = subprocess.run([
            browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
            f"--user-data-dir={profile}", "--virtual-time-budget=5000",
            f"--print-to-pdf={OUTPUT}", SOURCE.as_uri(),
        ], capture_output=True, text=True, timeout=180)
    if result.returncode != 0 or not OUTPUT.is_file():
        raise SystemExit(f"FAIL: browser exited with {result.returncode}")
    print(f"PASS: wrote {OUTPUT.relative_to(HERE.parents[1])} ({OUTPUT.stat().st_size / 1024:.0f} KiB)")
    try:
        from pypdf import PdfReader
    except ImportError:
        print("SKIP: pypdf not installed; page count and size not checked")
        return
    pages = PdfReader(OUTPUT).pages
    sizes = {(round(float(p.mediabox.width)), round(float(p.mediabox.height))) for p in pages}
    ok = len(pages) == EXPECTED_PAGES and sizes == {(960, 540)}
    print(f"{'PASS' if ok else 'FAIL'}: {len(pages)} pages (expected {EXPECTED_PAGES}); page size {sizes} pt (expected 960 x 540 = 16:9)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
