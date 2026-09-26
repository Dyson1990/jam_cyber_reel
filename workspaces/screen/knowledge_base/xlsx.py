"""最小 xlsx 读写（仅 stdlib，不引第三方依赖）。

写入用 inlineStr；读取兼容 Excel/WPS 重存后的 sharedStrings 与普通值，
供知识库「未过共识待人工选择」表落地与回读。
"""

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _col_index(ref: str) -> int:
    s = "".join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def write_xlsx(path: Path, rows: list[list[str]]) -> None:
    """rows: 二维字符串表，首行作表头。"""
    cells = []
    for ri, row in enumerate(rows, start=1):
        cs = []
        for ci, val in enumerate(row):
            v = _esc("" if val is None else str(val))
            cs.append(f'<c r="{_col(ci)}{ri}" t="inlineStr"><is><t xml:space="preserve">{v}</t></is></c>')
        cells.append(f'<row r="{ri}">{"".join(cs)}</row>')
    sheet_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_M}"><sheetData>{"".join(cells)}</sheetData></worksheet>'
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Types xmlns="{_CT}">'
            f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            f'</Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{_REL}">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            f'</Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{_M}" xmlns:r="{_R}">'
            f'<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
            f'</workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{_REL}">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            f'</Relationships>'
        ),
        "xl/worksheets/sheet1.xml": sheet_xml,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


def read_xlsx(path: Path) -> list[list[str]]:
    """读回二维字符串表（含表头）。按单元格列引用对齐，容忍 Excel 省略空单元格。"""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{{{_M}}}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_M}}}t")))
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    out = []
    for row in sheet.findall(f"{{{_M}}}sheetData/{{{_M}}}row"):
        vals: dict[int, str] = {}
        for c in row.findall(f"{{{_M}}}c"):
            t = c.get("t")
            if t == "inlineStr":
                txt = "".join(x.text or "" for x in c.iter(f"{{{_M}}}t"))
            elif t == "s":
                v = c.find(f"{{{_M}}}v")
                idx = int(v.text) if v is not None and v.text else 0
                txt = shared[idx] if idx < len(shared) else ""
            else:
                v = c.find(f"{{{_M}}}v")
                txt = (v.text or "") if v is not None else ""
            col = _col_index(c.get("r") or "")
            vals[col if col >= 0 else len(vals)] = txt
        if vals:
            out.append([vals.get(i, "") for i in range(max(vals) + 1)])
    return out
