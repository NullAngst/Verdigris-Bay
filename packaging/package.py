#!/usr/bin/env python3
"""Bundle a built executable with its docs into a release archive.

Usage: python packaging/package.py <platform-label>
Expects PyInstaller output in dist/. Writes release/verdigris-bay-<label>.zip
on Windows, .tar.gz elsewhere. Used by the GitHub workflow; runs locally too.
"""
import os
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    label = sys.argv[1]
    exe_name = "verdigris-bay.exe" if os.name == "nt" else "verdigris-bay"
    exe = ROOT / "dist" / exe_name
    if not exe.exists():
        print(f"missing {exe}; run PyInstaller first")
        return 1

    stage = ROOT / "release" / f"verdigris-bay-{label}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    shutil.copy2(exe, stage / exe_name)
    for doc in ("README.md", "HOW_TO_PLAY.html", "LICENSE"):
        if (ROOT / doc).exists():
            shutil.copy2(ROOT / doc, stage / doc)
            (stage / doc).chmod(0o644)

    if sys.platform.startswith("linux"):
        shutil.copy2(ROOT / "assets" / "icon-256.png", stage / "verdigris-bay.png")
        shutil.copy2(ROOT / "packaging" / "verdigris-bay.desktop", stage)
        shutil.copy2(ROOT / "packaging" / "install-linux.sh", stage)
        (stage / "install-linux.sh").chmod(0o755)
    (stage / exe_name).chmod(0o755)

    out_dir = ROOT / "release"
    if os.name == "nt":
        archive = out_dir / f"verdigris-bay-{label}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in stage.rglob("*"):
                zf.write(p, p.relative_to(stage.parent))
    else:
        # tar keeps the executable bit; zip on Unix often loses it.
        archive = out_dir / f"verdigris-bay-{label}.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(stage, arcname=stage.name)

    print(archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
