# -*- coding: utf-8 -*-
"""Render a filing page (or a crop) to PNG so a read can be CONFIRMED BY EYE (§57b rung 10).

The extractor proposes; this is how a verdict gets confirmed before anyone acts on it. Crop args
are 0-1 page fractions, same convention as scripts/_wf_crop.py.
Run: python3 render.py <pdf-basename-or-path> <page> [y0 y1] [out.png]
"""
import os, sys
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
PDFDIR = os.path.join(HERE, "_pdf")
SHOT = os.path.join(HERE, "_shots")


def render(pdf, page, y0=0.0, y1=1.0, out=None, zoom=3.0):
    path = pdf if os.path.exists(pdf) else os.path.join(PDFDIR, pdf)
    if not path.endswith(".pdf"):
        path += ".pdf"
    doc = fitz.open(path)
    pg = doc[page]
    r = pg.rect
    clip = fitz.Rect(r.x0, r.y0 + (r.y1 - r.y0) * y0, r.x1, r.y0 + (r.y1 - r.y0) * y1)
    pm = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    os.makedirs(SHOT, exist_ok=True)
    out = out or os.path.join(SHOT, "%s_p%d_%.2f-%.2f.png"
                              % (os.path.basename(path)[:12], page, y0, y1))
    pm.save(out)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    y0, y1 = (float(a[2]), float(a[3])) if len(a) >= 4 else (0.0, 1.0)
    print(render(a[0], int(a[1]), y0, y1, a[4] if len(a) > 4 else None))
