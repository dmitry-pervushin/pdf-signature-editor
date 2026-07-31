from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .i18n import tr as _
from .model import Placement


class PdfEditorError(RuntimeError):
    pass


def page_sizes(pdf_path: Path) -> list[tuple[float, float]]:
    try:
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted:
            if reader.decrypt("") == 0:
                raise PdfEditorError(_("pdf_password_open"))
        sizes = []
        for page in reader.pages:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            if page.rotation % 180:
                width, height = height, width
            sizes.append((width, height))
        return sizes
    except PdfEditorError:
        raise
    except Exception as exc:
        raise PdfEditorError(_("pdf_read_failed", error=exc)) from exc


def render_page(pdf_path: Path, page_number: int, dpi: int = 130) -> Image.Image:
    executable = shutil.which("pdftoppm")
    if not executable:
        raise PdfEditorError(_("pdftoppm_missing"))

    with tempfile.TemporaryDirectory(prefix="pdf-sign-editor-") as temp_dir:
        prefix = Path(temp_dir) / "page"
        command = [
            executable,
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-singlefile",
            "-r",
            str(dpi),
            "-png",
            str(pdf_path),
            str(prefix),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfEditorError(_("preview_timeout")) from exc
        if result.returncode:
            detail = result.stderr.strip() or _("unknown_render_error")
            raise PdfEditorError(_("page_render_failed", detail=detail))
        with Image.open(prefix.with_suffix(".png")) as rendered:
            return rendered.convert("RGB")


def _text_width(text: str, font_size: float) -> float:
    # Helvetica-Oblique is used when exporting; this estimate is intentionally
    # a little generous so selection boxes remain easy to grab in the GUI.
    return max(font_size * 2.0, len(text) * font_size * 0.55)


def normalized_text_placement(
    page_index: int, x: float, y: float, text: str, font_size: float
) -> Placement:
    return Placement(
        kind="text",
        page_index=page_index,
        x=x,
        y=y,
        width=_text_width(text, font_size),
        height=font_size * 1.35,
        text=text,
        font_size=font_size,
    )


def _build_overlay(
    page_width: float,
    page_height: float,
    placements: Iterable[Placement],
) -> BytesIO:
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(page_width, page_height))
    pdf.setFillColor(Color(0.08, 0.08, 0.1, 1))

    for placement in placements:
        # GUI coordinates start at the top-left; ReportLab starts at bottom-left.
        bottom = page_height - placement.y - placement.height
        if placement.kind == "text":
            baseline = bottom + placement.height * 0.22
            pdf.setFont("Helvetica-Oblique", placement.font_size)
            pdf.drawString(placement.x, baseline, placement.text)
        elif placement.image_path:
            pdf.drawImage(
                ImageReader(str(placement.image_path)),
                placement.x,
                bottom,
                placement.width,
                placement.height,
                preserveAspectRatio=True,
                mask="auto",
            )

    pdf.save()
    stream.seek(0)
    return stream


def export_pdf(
    input_path: Path, output_path: Path, placements: Iterable[Placement]
) -> None:
    by_page: dict[int, list[Placement]] = {}
    for placement in placements:
        by_page.setdefault(placement.page_index, []).append(placement)

    try:
        reader = PdfReader(str(input_path))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise PdfEditorError(_("pdf_password_edit"))

        writer = PdfWriter()
        for page_index, page in enumerate(reader.pages):
            # Turn /Rotate into page content so GUI coordinates always match
            # the visual top-left orientation shown by Poppler.
            if page.rotation:
                page.transfer_rotation_to_content()
            page_placements = by_page.get(page_index, [])
            if page_placements:
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                overlay = PdfReader(
                    _build_overlay(width, height, page_placements)
                ).pages[0]
                page.merge_page(overlay)
            writer.add_page(page)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb") as output:
            writer.write(output)
    except PdfEditorError:
        raise
    except Exception as exc:
        raise PdfEditorError(_("pdf_save_failed", error=exc)) from exc
