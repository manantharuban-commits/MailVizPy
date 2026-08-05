#!/usr/bin/env python
"""
doctor.py - report what this interpreter can actually do.

"pywin32 is missing" on a machine where pip clearly installed it almost always
means the extension is running a different Python than the one pip installed
into. So this prints which interpreter answered, where its packages live, and
the real error text for anything that failed to import — never a bare boolean.

Emits one JSON object on stdout.
"""

import json
import os
import sys


def probe(module_names, label):
    """Import the first name that works and report what happened to the rest."""
    attempts = []
    for name in module_names:
        try:
            module = __import__(name)
            return {
                "ok": True,
                "label": label,
                "module": name,
                "version": getattr(module, "__version__", None) or getattr(module, "version", None),
                "path": getattr(module, "__file__", None),
                "attempts": attempts,
            }
        except Exception as exc:  # noqa: BLE001 - a DLL load failure is not an ImportError
            attempts.append({"module": name, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": False, "label": label, "attempts": attempts}


def main():
    report = {
        "executable": sys.executable,
        "version": sys.version.split()[0],
        "prefix": sys.prefix,
        "in_venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "platform": sys.platform,
        "windows_store_stub": "WindowsApps" in (sys.executable or ""),
        "site_packages": [p for p in sys.path if "site-packages" in p][:3],
    }

    # pywin32 spreads across several modules and win32api is the one that fails
    # loudly when the post-install DLL copy never ran.
    report["pywin32"] = probe(["win32com.client"], "pywin32")
    report["pywin32_core"] = probe(["win32api"], "pywin32 core DLLs")
    report["pymupdf"] = probe(["pymupdf", "fitz"], "PyMuPDF")

    report["ready"] = bool(report["pywin32"]["ok"] and report["pymupdf"]["ok"])
    report["can_rasterise"] = bool(report["pymupdf"]["ok"])

    hints = []
    if report["windows_store_stub"]:
        hints.append(
            "This is the Microsoft Store build of Python. Its packages live in a "
            "sandboxed folder and COM automation is unreliable. Install Python from python.org."
        )
    if report["pymupdf"]["ok"] and not report["pywin32"]["ok"]:
        hints.append("PyMuPDF is here but pywin32 is not, so rendering will fall back to LibreOffice.")
    if not report["pywin32"]["ok"] and sys.platform == "win32":
        hints.append(f"Install into this interpreter with: \"{sys.executable}\" -m pip install pywin32 pymupdf")
    if report["pywin32"]["ok"] and not report["pywin32_core"]["ok"]:
        hints.append(
            "pywin32 imports but its DLLs did not load. Run: "
            f"\"{sys.executable}\" Scripts/pywin32_postinstall.py -install"
        )
    report["hints"] = hints

    json.dump(report, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
