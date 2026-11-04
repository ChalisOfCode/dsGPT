"""Trusted entry point executed ONLY in a checked, networkless document container."""

import base64
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def command(argv, timeout=20):
    result = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError("Document decoder rejected the input")
    return result.stdout.decode("utf-8", errors="replace")


def extract(data, extension, directory):
    source = directory / ("input." + extension)
    source.write_bytes(data)
    pages, method = [], "text"
    if extension == "pdf":
        info = command(["pdfinfo", str(source)])
        count = re.search(r"^Pages:\s*(\d+)", info, re.M)
        if not count or not 1 <= int(count[1]) <= 20:
            raise ValueError("PDFs are limited to 20 pages; split the document")
        if re.search(r"^Encrypted:\s*yes", info, re.M):
            raise ValueError("Unlock the PDF before attaching it")
        for n in range(1, int(count[1]) + 1):
            target = directory / "page.txt"
            command(
                ["pdftotext", "-f", str(n), "-l", str(n), "-enc", "UTF-8", str(source), str(target)]
            )
            text = target.read_text().strip()
            origin = "text"
            if not text:
                prefix = directory / "scan"
                command(
                    [
                        "pdftoppm",
                        "-f",
                        str(n),
                        "-l",
                        str(n),
                        "-singlefile",
                        "-scale-to",
                        "2200",
                        "-png",
                        str(source),
                        str(prefix),
                    ]
                )
                text = command(["tesseract", str(prefix) + ".png", "stdout", "-l", "eng"])
                origin = "ocr"
            pages.append({"page": n, "method": origin, "text": text.strip()})
    elif extension in {"png", "jpg", "jpeg", "webp"}:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = 16_000_000
        with Image.open(source) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Use a single PNG, JPEG or WebP image")
            if image.width * image.height > 16_000_000:
                raise ValueError("Images are limited to 16 megapixels")
            image.load()
            image.convert("RGB").save(directory / "ocr.png")
            dimensions = [image.width, image.height]
        text = command(["tesseract", str(directory / "ocr.png"), "stdout", "-l", "eng"])
        pages.append({"page": 1, "method": "ocr", "text": text.strip()})
        method = "image"
    elif extension in {"xlsx", "pptx"}:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > 512 or sum(x.file_size for x in entries) > 8_388_608:
                raise ValueError("Office package exceeds extraction limits")
            if any(x.flag_bits & 1 or x.filename.lower().endswith(".bin") for x in entries):
                raise ValueError("Encrypted or macro/embedded binary packages are unsupported")
            names = sorted(
                (
                    x.filename
                    for x in entries
                    if (
                        re.fullmatch(r"ppt/slides/slide\d+\.xml", x.filename)
                        if extension == "pptx"
                        else re.fullmatch(
                            r"xl/(sharedStrings|worksheets/sheet\d+)\.xml", x.filename
                        )
                    )
                ),
                key=lambda name: (
                    (0, 0)
                    if name == "xl/sharedStrings.xml"
                    else (1, int(re.search(r"(\d+)\.xml$", name)[1]))
                ),
            )
            shared = []
            for name in names:
                raw = archive.read(name)
                if len(raw) > 1_048_576 or re.search(rb"<!\s*(DOCTYPE|ENTITY)", raw, re.I):
                    raise ValueError("Unsupported Office XML")
                tree = ET.fromstring(raw)
                if name == "xl/sharedStrings.xml":
                    shared = ["".join(x.itertext()) for x in tree]
                    continue
                if extension == "pptx":
                    text = "\n".join(x.text or "" for x in tree.iter() if x.tag.endswith("}t"))
                else:
                    cells = []
                    for cell in tree.iter():
                        if not cell.tag.endswith("}c"):
                            continue
                        value = "".join(
                            x.text or "" for x in cell.iter() if x.tag.endswith(("}v", "}t"))
                        )
                        if cell.get("t") == "s":
                            value = shared[int(value)]
                        cells.append(cell.get("r", "") + ": " + value)
                    text = "\n".join(cells)
                pages.append({"page": len(pages) + 1, "part": name, "method": "text", "text": text})
    else:
        raise ValueError("Unsupported document format")
    text = "\n\n".join(f"[Page {p['page']}; {p['method']}]\n{p['text']}" for p in pages)
    text = "".join(c for c in text if ord(c) >= 32 or c in "\n\t\r")
    if len(text.encode()) > 65_536:
        raise ValueError("Extracted text exceeds 64 KiB; split the document")
    result = {
        "text": text,
        "pages": [{k: v for k, v in p.items() if k != "text"} for p in pages],
        "format": extension,
        "image": method == "image",
    }
    if method == "image":
        result["dimensions"] = dimensions
    return result


if __name__ == "__main__":
    os.environ["OMP_THREAD_LIMIT"] = "2"
    request = json.loads(Path("request.json").read_text())
    try:
        result = extract(
            base64.b64decode(request["original_base64"], validate=True),
            request["extension"],
            Path.cwd(),
        )
        Path("result.json").write_text(json.dumps(result))
    except Exception as exc:
        Path("result.json").write_text(json.dumps({"error": str(exc)[:300]}))
