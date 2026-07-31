from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from pdf_editor.model import Placement, ViewTransform, size_from_bottom_right
from pdf_editor.pdf_ops import export_pdf, normalized_text_placement


def test_view_transform_roundtrip() -> None:
    transform = ViewTransform(600, 800, 20, 30, 0.75)
    canvas_point = transform.pdf_to_canvas(123.5, 456.25)
    pdf_point = transform.canvas_to_pdf(*canvas_point)
    assert pdf_point == (123.5, 456.25)


def test_image_resize_preserves_aspect_ratio_and_page_bounds() -> None:
    placement = Placement("image", 0, 100, 200, 160, 40)
    width, height = size_from_bottom_right(placement, 420, 280, 595, 842)
    assert (width, height) == (320, 80)

    width, height = size_from_bottom_right(placement, 1000, 1000, 300, 260)
    assert (width, height) == (200, 50)


def test_export_keeps_pages_and_adds_content(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    signature = tmp_path / "signature.png"

    image = Image.new("RGBA", (180, 60), (255, 255, 255, 0))
    for x in range(15, 165):
        y = 25 + int(10 * __import__("math").sin(x / 12))
        image.putpixel((x, y), (18, 43, 85, 255))
    image.save(signature)

    pdf = canvas.Canvas(str(source), pagesize=(595, 842))
    pdf.drawString(60, 780, "Document test")
    pdf.showPage()
    pdf.drawString(60, 780, "Deuxieme page")
    pdf.save()

    text = normalized_text_placement(0, 90, 610, "Lu et approuvé", 16)
    sign = Placement("image", 0, 90, 660, 150, 50, image_path=signature)
    export_pdf(source, output, [text, sign])

    reader = PdfReader(str(output))
    assert len(reader.pages) == 2
    assert "Lu et approuvé" in (reader.pages[0].extract_text() or "")
    assert "Deuxieme page" in (reader.pages[1].extract_text() or "")
