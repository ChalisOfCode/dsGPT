"""Small deterministic OOXML specimens for engine tests, not delivered documents."""

import io
import zipfile

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
C = "http://schemas.openxmlformats.org/package/2006/content-types"


def packed(parts):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return out.getvalue()


def workbook(*, errors=False, cached="999", unsafe=False):
    extra = (
        ('<c r="B5"><f>1/0</f><v>999</v></c><c r="B6"><f>DSGPT_UNSUPPORTED(1)</f><v>999</v></c>')
        if errors
        else ""
    )
    parts = {
        "[Content_Types].xml": f'<Types xmlns="{C}"><Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" '
        'ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": f'<Relationships xmlns="{P}">'
        f'<Relationship Id="rId1" Type="{R}/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets>'
        '<sheet name="Values" sheetId="1" r:id="rId1"/>'
        '<sheet name="Other" sheetId="2" r:id="rId2"/></sheets>'
        '<calcPr calcMode="manual" fullCalcOnLoad="0"/></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{P}">'
        f'<Relationship Id="rId1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{R}/worksheet" Target="worksheets/sheet2.xml"/>'
        "</Relationships>",
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{S}"><sheetData>'
        '<row r="1"><c r="A1"><v>7</v></c>'
        f'<c r="B1"><f>A1*3</f><v>{cached}</v></c></row>'
        f'<row r="2"><c r="B2"><f>B1+Other!A1</f><v>{cached}</v></c></row>'
        '<row r="3"><c r="B3" t="str"><f>"你好"&amp;" world"</f><v>WRONG</v></c></row>'
        f'<row r="4"><c r="B4"><f>DATE(2024,1,2)</f><v>{cached}</v></c></row>'
        + (
            f'<row r="5">{extra[: extra.index("<c r=", 1)]}</row>'
            f'<row r="6">{extra[extra.index("<c r=", 1) :]}</row>'
            if extra
            else ""
        )
        + "</sheetData></worksheet>",
        "xl/worksheets/sheet2.xml": f'<worksheet xmlns="{S}"><sheetData>'
        '<row r="1"><c r="A1"><v>2</v></c></row></sheetData></worksheet>',
    }
    if unsafe:
        parts["xl/connections.xml"] = "<connections/>"
    return packed(parts)


def _document():
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    return packed(
        {
            "[Content_Types].xml": f'<Types xmlns="{C}"><Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.document.main+xml"/></Types>',
            "_rels/.rels": f'<Relationships xmlns="{P}"><Relationship Id="rId1" '
            f'Type="{R}/officeDocument" Target="word/document.xml"/></Relationships>',
            "word/document.xml": f'<w:document xmlns:w="{w}"><w:body>'
            "<w:p><w:r><w:t>Independent rendering check</w:t></w:r></w:p>"
            '<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/></w:tblPr>'
            '<w:tblGrid><w:gridCol w:w="4500"/><w:gridCol w:w="4500"/></w:tblGrid>'
            "<w:tr><w:tc><w:p><w:r><w:t>Table label</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>42</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
            '<w:p><w:r><w:br w:type="page"/><w:t>Second page preserved</w:t></w:r></w:p>'
            '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
            "</w:sectPr></w:body></w:document>",
        }
    )


def slides():
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    parts = {
        "[Content_Types].xml": f'<Types xmlns="{C}"><Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.presentationml.presentation.main+xml"/>'
        + "".join(
            f'<Override PartName="/ppt/slides/slide{i}.xml" '
            'ContentType="application/vnd.openxmlformats-'
            'officedocument.presentationml.slide+xml"/>'
            for i in (1, 2)
        )
        + "</Types>",
        "_rels/.rels": f'<Relationships xmlns="{P}"><Relationship Id="rId1" '
        f'Type="{R}/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
        "ppt/presentation.xml": f'<p:presentation xmlns:p="{p}" xmlns:a="{a}" xmlns:r="{R}">'
        '<p:sldIdLst><p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst>'
        '<p:sldSz cx="9144000" cy="5143500"/><p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>",
        "ppt/_rels/presentation.xml.rels": f'<Relationships xmlns="{P}">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="{R}/slide" Target="slides/slide{i}.xml"/>'
            for i in (1, 2)
        )
        + "</Relationships>",
    }
    for number in (1, 2):
        x = 500000 if number == 1 else 8500000
        parts[f"ppt/slides/slide{number}.xml"] = (
            f'<p:sld xmlns:p="{p}" xmlns:a="{a}" xmlns:r="{R}"><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Known text"/><p:cNvSpPr txBox="1"/>'
            "<p:nvPr/></p:nvSpPr><p:spPr>"
            f'<a:xfrm><a:off x="{x}" y="500000"/><a:ext cx="4000000" cy="1000000"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="2400"/>'
            f"<a:t>Slide {number}: independent layout check</a:t></a:r></a:p></p:txBody>"
            "</p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
        )
    return packed(parts)


def document():
    """Two-page Writer specimen with a table, header/footer and a blue square image."""
    import struct
    import zlib

    def chunk(kind, data):
        return (
            struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", 32, 32, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\x18\x65\xc0" * 32) * 32))
        + chunk(b"IEND", b"")
    )
    with zipfile.ZipFile(io.BytesIO(_document())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    body = parts["word/document.xml"].decode().replace("<w:body>", f'<w:body xmlns:r="{R}">')
    body = body.replace(
        "<w:sectPr>",
        '<w:sectPr><w:headerReference w:type="default" r:id="head"/>'
        '<w:footerReference w:type="default" r:id="foot"/>',
    )
    image = (
        "<w:p><w:r><w:drawing>"
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        '<wp:extent cx="457200" cy="457200"/><wp:docPr id="1" name="Blue square"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="1" name="Blue square"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="image"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="457200" cy="457200"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )
    parts["word/document.xml"] = body.replace("<w:tbl>", image + "<w:tbl>")
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    for kind, text in (("header", "Controlled document header"), ("footer", "Controlled footer")):
        tag = "hdr" if kind == "header" else "ftr"
        parts[f"word/{kind}.xml"] = (
            f'<w:{tag} xmlns:w="{w}"><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:{tag}>'
        )
    parts["word/media/square.png"] = png
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{P}">'
        f'<Relationship Id="head" Type="{R}/header" Target="header.xml"/>'
        f'<Relationship Id="foot" Type="{R}/footer" Target="footer.xml"/>'
        f'<Relationship Id="image" Type="{R}/image" Target="media/square.png"/></Relationships>'
    )
    types = (
        parts["[Content_Types].xml"]
        .decode()
        .replace(
            "</Types>",
            '<Default Extension="png" ContentType="image/png"/>'
            '<Override PartName="/word/header.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.header+xml"/>'
            '<Override PartName="/word/footer.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.footer+xml"/></Types>',
        )
    )
    parts["[Content_Types].xml"] = types
    return packed(parts)
