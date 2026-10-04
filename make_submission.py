"""Pack the PA2 submission: python make_submission.py <學號>

Produces <學號>.zip with the layout required by the TA:
    <學號>/report.pdf, 1.txt, dictionary.txt, pa2.py, output/ (empty), data/ (empty)
Run `python pa2.py` first and put report.pdf next to this script.
"""

import os
import sys
import zipfile

REQUIRED = {
    "pa2.py": "pa2.py",
    "report.pdf": "report.pdf",
    "dictionary.txt": os.path.join("output", "dictionary.txt"),
    "1.txt": os.path.join("output", "1.txt"),
}


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python make_submission.py <student_id>")
    sid = sys.argv[1]
    missing = [src for src in REQUIRED.values() if not os.path.isfile(src)]
    if missing:
        raise SystemExit(f"missing files: {', '.join(missing)}")

    with zipfile.ZipFile(f"{sid}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for name, src in REQUIRED.items():
            z.write(src, f"{sid}/{name}")
        for empty in ("output/", "data/"):
            z.writestr(f"{sid}/{empty}", "")
    print(f"{sid}.zip created")
    with zipfile.ZipFile(f"{sid}.zip") as z:
        for name in z.namelist():
            print("  " + name)


if __name__ == "__main__":
    main()
