"""Minimal engineering-drawing SVG writer (units: millimetres on paper)."""
from __future__ import annotations

import math
from xml.sax.saxutils import escape

STYLE = """
.bg{fill:#ffffff}
.thick{stroke:#000;stroke-width:0.5;fill:none;stroke-linejoin:round}
.med{stroke:#000;stroke-width:0.35;fill:none}
.thin{stroke:#000;stroke-width:0.18;fill:none}
.hidden{stroke:#000;stroke-width:0.25;fill:none;stroke-dasharray:2.5,1.2}
.center{stroke:#000;stroke-width:0.18;fill:none;stroke-dasharray:8,1.5,1,1.5}
.dim{stroke:#000;stroke-width:0.18;fill:none}
.cut{stroke:#c00;stroke-width:0.25;fill:none;stroke-dasharray:6,1.5,1,1.5}
.hatch{fill:url(#hatch);stroke:#000;stroke-width:0.35}
.hatchss{fill:url(#hatchss);stroke:#000;stroke-width:0.35}
.solid{fill:#000;stroke:none}
.grey{fill:#d9d9d9;stroke:#000;stroke-width:0.25}
.refr{fill:url(#dots);stroke:#000;stroke-width:0.25}
.tube{fill:none;stroke:#000;stroke-width:0.15}
.tie{fill:#000;stroke:#000;stroke-width:0.15}
text{font-family:'Arial','Helvetica',sans-serif;fill:#000}
.frame{stroke:#000;stroke-width:0.7;fill:none}
"""

DEFS = """
<defs>
 <marker id="arr" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="3" markerHeight="3"
   markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,1.5 L10,5 L0,8.5 z" fill="#000"/></marker>
 <pattern id="hatch" patternUnits="userSpaceOnUse" width="1.6" height="1.6" patternTransform="rotate(45)">
   <line x1="0" y1="0" x2="0" y2="1.6" stroke="#000" stroke-width="0.18"/></pattern>
 <pattern id="hatchss" patternUnits="userSpaceOnUse" width="1.6" height="1.6" patternTransform="rotate(-45)">
   <line x1="0" y1="0" x2="0" y2="1.6" stroke="#000" stroke-width="0.18"/>
   <line x1="0.8" y1="0" x2="0.8" y2="1.6" stroke="#000" stroke-width="0.1"/></pattern>
 <pattern id="dots" patternUnits="userSpaceOnUse" width="1.5" height="1.5">
   <circle cx="0.75" cy="0.75" r="0.22" fill="#000"/></pattern>
</defs>
"""


def f(x):
    return f"{x:.3f}".rstrip("0").rstrip(".")


class SVG:
    def __init__(self, w: float, h: float, title: str = ""):
        self.w, self.h, self.title, self.el = w, h, title, []

    # primitives ------------------------------------------------------------------------------
    def line(self, x1, y1, x2, y2, cls="thin", extra=""):
        self.el.append(f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" class="{cls}" {extra}/>')

    def rect(self, x, y, w, h, cls="thin", extra=""):
        if w < 0:
            x, w = x + w, -w
        if h < 0:
            y, h = y + h, -h
        self.el.append(f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" class="{cls}" {extra}/>')

    def circle(self, cx, cy, r, cls="thin", extra=""):
        self.el.append(f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}" class="{cls}" {extra}/>')

    def path(self, d, cls="thin", extra=""):
        self.el.append(f'<path d="{d}" class="{cls}" {extra}/>')

    def poly(self, pts, cls="thin", close=True):
        d = "M" + " L".join(f"{f(x)},{f(y)}" for x, y in pts) + (" Z" if close else "")
        self.path(d, cls)

    def text(self, x, y, s, size=3.5, anchor="start", weight="normal", rotate=0, extra=""):
        tr = f' transform="rotate({f(rotate)} {f(x)} {f(y)})"' if rotate else ""
        self.el.append(f'<text x="{f(x)}" y="{f(y)}" font-size="{f(size)}" text-anchor="{anchor}" '
                       f'font-weight="{weight}"{tr} {extra}>{escape(str(s))}</text>')

    def raw(self, s):
        self.el.append(s)

    # dimensioning ------------------------------------------------------------------------------
    def dim_h(self, x1, x2, y, label, y1=None, y2=None, size=3.0, gap=1.0, over=1.5, above=True):
        for x, yr in ((x1, y1), (x2, y2)):
            if yr is not None:
                s = 1 if y > yr else -1
                self.line(x, yr + s * gap, x, y + s * over, "dim")
        self.line(x1, y, x2, y, "dim", 'marker-start="url(#arr)" marker-end="url(#arr)"')
        ty = y - 1.0 if above else y + size + 0.5
        self.text((x1 + x2) / 2, ty, label, size, "middle")

    def dim_v(self, x, y1, y2, label, x1=None, x2=None, size=3.0, gap=1.0, over=1.5, left=True):
        for y, xr in ((y1, x1), (y2, x2)):
            if xr is not None:
                s = 1 if x > xr else -1
                self.line(xr + s * gap, y, x + s * over, y, "dim")
        self.line(x, y1, x, y2, "dim", 'marker-start="url(#arr)" marker-end="url(#arr)"')
        tx = x - 1.0 if left else x + size + 0.5
        self.text(tx, (y1 + y2) / 2, label, size, "middle", rotate=-90)

    def balloon(self, x, y, label, tx, ty, r=3.2, size=3.0):
        ang = math.atan2(y - ty, x - tx)
        self.line(x, y, tx + r * math.cos(ang), ty + r * math.sin(ang), "thin")
        self.circle(tx, ty, r, "med")
        self.text(tx, ty + size * 0.35, label, size, "middle", "bold")

    def leader(self, x, y, tx, ty, label, size=2.8, anchor="start"):
        self.line(x, y, tx, ty, "thin", 'marker-start="url(#arr)"')
        dx = 12 if anchor == "start" else -12
        self.line(tx, ty, tx + dx, ty, "thin")
        self.text(tx + (dx + (1 if dx > 0 else -1)), ty + size * 0.35, label, size, anchor)

    # tables ------------------------------------------------------------------------------------
    def table(self, x, y, col_w, rows, row_h=5.0, size=2.6, header=None, title=None, bold_first=False):
        """rows: list of lists of str. Returns bottom y."""
        cy = y
        W = sum(col_w)
        if title:
            self.rect(x, cy, W, row_h + 1, "med", 'style="fill:#e6e6e6"')
            self.text(x + W / 2, cy + row_h * 0.75 + 0.3, title, size + 0.6, "middle", "bold")
            cy += row_h + 1
        all_rows = ([header] if header else []) + rows
        for i, row in enumerate(all_rows):
            is_h = header is not None and i == 0
            self.rect(x, cy, W, row_h, "thin", 'style="fill:#f2f2f2"' if is_h else "")
            cx = x
            for j, (cw, cell) in enumerate(zip(col_w, row)):
                if j:
                    self.line(cx, cy, cx, cy + row_h, "thin")
                wt = "bold" if is_h or (bold_first and j == 0) else "normal"
                self.text(cx + 1.2, cy + row_h * 0.7, cell, size, "start", wt)
                cx += cw
            cy += row_h
        self.rect(x, y, W, cy - y, "med")
        return cy

    # sheet ---------------------------------------------------------------------------------------
    def frame(self, margin_left=20, margin=10):
        self.rect(margin_left, margin, self.w - margin_left - margin, self.h - 2 * margin, "frame")
        return margin_left, margin, self.w - margin, self.h - margin

    def title_block(self, x2, y2, fields: dict, w=180, h=56):
        x, y = x2 - w, y2 - h
        self.rect(x, y, w, h, "frame")
        rows = [
            ("PROJECT", fields.get("project", "")),
            ("TITLE", fields.get("title", "")),
            ("", fields.get("title2", "")),
            ("EQUIPMENT", fields.get("equipment", "")),
        ]
        ry = y
        for k, v in rows:
            self.line(x, ry, x + w, ry, "thin")
            self.text(x + 1.5, ry + 2.6, k, 2.0)
            self.text(x + 22, ry + 5.0, v, 3.2 if k != "" else 3.2, "start", "bold" if k in ("TITLE", "") else "normal")
            ry += 7
        self.line(x + 20, y, x + 20, ry, "thin")
        cells = [("DWG No.", fields.get("dwg", "")), ("REV", fields.get("rev", "0")),
                 ("SCALE", fields.get("scale", "")), ("SIZE", fields.get("size", "")),
                 ("DATE", fields.get("date", "")), ("UNITS", "mm"),
                 ("DESIGN CODE", fields.get("code", "")), ("SHEET", fields.get("sheet", ""))]
        cw = w / 4
        for i, (k, v) in enumerate(cells):
            cx = x + (i % 4) * cw
            cy = ry + (i // 4) * 10
            self.rect(cx, cy, cw, 10, "thin")
            self.text(cx + 1.2, cy + 2.6, k, 2.0)
            self.text(cx + 1.5, cy + 7.5, v, 2.9, "start", "bold")
        self.text(x + 1.5, y2 - 1.5, fields.get("footer", ""), 2.0)
        # third-angle projection symbol
        px, py = x - 22, y2 - 10
        self.text(px - 2, py - 7, "3rd ANGLE", 2.0)
        self.poly([(px, py - 3), (px + 7, py - 4.5), (px + 7, py + 4.5), (px, py + 3)], "med")
        self.circle(px + 14, py, 4.5, "med")
        self.circle(px + 14, py, 2.2, "med")
        return y

    def save(self, path):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{f(self.w)}mm" height="{f(self.h)}mm" '
                f'viewBox="0 0 {f(self.w)} {f(self.h)}">\n<title>{escape(self.title)}</title>\n'
                f'<style>{STYLE}</style>\n{DEFS}\n<rect class="bg" x="0" y="0" width="{f(self.w)}" height="{f(self.h)}"/>\n')
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(head + "\n".join(self.el) + "\n</svg>\n")
