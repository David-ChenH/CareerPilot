from textwrap import wrap


def build_simple_pdf(title: str, sections: list[tuple[str, list[str]]]) -> bytes:
    lines = [title, ""]
    for heading, items in sections:
        lines.append(heading)
        lines.extend(f"- {item}" for item in items if item)
        lines.append("")

    pages = _paginate(lines)
    page_objects: list[tuple[int, int, bytes, bytes]] = []
    next_object_id = 4
    for page_lines in pages:
        content_id = next_object_id
        page_id = next_object_id + 1
        next_object_id += 2
        content = _page_stream(page_lines)
        stream = f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        page_objects.append((content_id, page_id, stream, page))

    objects: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (
            2,
            f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for _, page_id, _, _ in page_objects)}] /Count {len(page_objects)} >>".encode(),
        ),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    for content_id, page_id, stream, page in page_objects:
        objects.append((content_id, stream))
        objects.append((page_id, page))

    objects.sort(key=lambda item: item[0])
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (len(objects) + 1)
    for object_id, obj in objects:
        offsets[object_id] = len(output)
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for object_id in range(1, len(objects) + 1):
        output.extend(f"{offsets[object_id]:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        )
        .encode()
    )
    return bytes(output)


def _paginate(lines: list[str]) -> list[list[str]]:
    wrapped = []
    for line in lines:
        if not line:
            wrapped.append("")
        else:
            wrapped.extend(wrap(line, width=88) or [""])
    return [wrapped[index : index + 42] for index in range(0, len(wrapped), 42)] or [[]]


def _page_stream(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 11 Tf", "50 742 Td", "14 TL"]
    for line in lines:
        commands.append(f"({_escape(line)}) Tj")
        commands.append("T*")
    commands.append("ET")
    return "\n".join(commands).encode("latin-1", errors="replace")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
