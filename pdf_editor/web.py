from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
import uuid
from io import BytesIO
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge

from .digital_signing import (
    DigitalSigningError,
    create_self_signed_pkcs12,
    sign_pdf_with_pkcs12,
)
from .model import Placement
from .pdf_ops import PdfEditorError, export_pdf, page_sizes, render_page

MAX_UPLOAD = 50 * 1024 * 1024
DOCUMENT_TTL = 24 * 60 * 60


def create_app(document_root: Path | None = None) -> Flask:
    app = Flask(__name__, static_folder="web_static", static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
    root = Path(document_root or os.environ.get("PDF_EDITOR_TMP", "/tmp/pdf-signature-editor"))
    root.mkdir(parents=True, exist_ok=True)

    def document_dir(document_id: str) -> Path:
        try:
            clean_id = str(uuid.UUID(document_id))
        except ValueError:
            abort(404)
        directory = root / clean_id
        if not (directory / "document.pdf").is_file():
            abort(404)
        directory.touch()
        return directory

    def cleanup() -> None:
        threshold = time.time() - DOCUMENT_TTL
        for directory in root.iterdir():
            try:
                if directory.is_dir() and directory.stat().st_mtime < threshold:
                    shutil.rmtree(directory, ignore_errors=True)
            except FileNotFoundError:
                pass

    @app.before_request
    def cleanup_expired_documents():
        if request.path.startswith("/api/"):
            cleanup()

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return jsonify(error="Файл слишком большой (максимум 50 МБ)."), 413

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/api/documents")
    def upload_document():
        upload = request.files.get("file")
        if upload is None:
            return jsonify(error="Выберите PDF-файл."), 400
        directory = root / str(uuid.uuid4())
        directory.mkdir()
        path = directory / "document.pdf"
        try:
            upload.save(path)
            with path.open("rb") as source:
                if source.read(5) != b"%PDF-":
                    raise PdfEditorError("Файл не является PDF.")
            sizes = page_sizes(path)
            if not sizes:
                raise PdfEditorError("В PDF нет страниц.")
        except (PdfEditorError, OSError) as exc:
            shutil.rmtree(directory, ignore_errors=True)
            return jsonify(error=str(exc)), 400
        return jsonify(id=directory.name, pages=[{"width": w, "height": h} for w, h in sizes])

    @app.get("/api/documents/<document_id>/pages/<int:page_number>/preview")
    def preview(document_id: str, page_number: int):
        directory = document_dir(document_id)
        try:
            sizes = page_sizes(directory / "document.pdf")
            if not 1 <= page_number <= len(sizes):
                abort(404)
            image = render_page(directory / "document.pdf", page_number, dpi=110)
            output = BytesIO()
            image.save(output, format="PNG")
            output.seek(0)
            return send_file(output, mimetype="image/png", max_age=0)
        except PdfEditorError as exc:
            return jsonify(error=str(exc)), 422

    @app.post("/api/documents/<document_id>/assets")
    def upload_asset(document_id: str):
        directory = document_dir(document_id)
        upload = request.files.get("file")
        if upload is None:
            return jsonify(error="Выберите изображение."), 400
        try:
            with Image.open(upload.stream) as image:
                if image.format not in ("PNG", "JPEG"):
                    return jsonify(error="Нужен PNG или JPG."), 400
                if image.width * image.height > 25_000_000:
                    return jsonify(error="Изображение слишком большое."), 400
                image.load()
                converted = image.convert("RGBA")
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
            return jsonify(error="Нужен PNG или JPG."), 400
        asset_id = str(uuid.uuid4())
        converted.save(directory / f"{asset_id}.png", format="PNG")
        return jsonify(id=asset_id, width=converted.width, height=converted.height)

    @app.get("/api/documents/<document_id>/assets/<asset_id>")
    def get_asset(document_id: str, asset_id: str):
        directory = document_dir(document_id)
        try:
            clean_id = str(uuid.UUID(asset_id))
        except ValueError:
            abort(404)
        path = directory / f"{clean_id}.png"
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)

    def parse_placements(raw: str, directory: Path, sizes: list[tuple[float, float]]) -> list[Placement]:
        try:
            items = json.loads(raw)
            if not isinstance(items, list) or len(items) > 500:
                raise ValueError("Некорректный список элементов.")
            placements = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("Некорректный элемент.")
                page = item["page_index"]
                if type(page) is not int or not 0 <= page < len(sizes):
                    raise ValueError("Некорректная страница.")
                values = [float(item[key]) for key in ("x", "y", "width", "height")]
                x, y, width, height = values
                page_width, page_height = sizes[page]
                if not all(map(math.isfinite, values)) or width <= 0 or height <= 0:
                    raise ValueError("Некорректные размеры элемента.")
                if x < 0 or y < 0 or x + width > page_width + 0.1 or y + height > page_height + 0.1:
                    raise ValueError("Элемент выходит за пределы страницы.")
                if item.get("kind") == "image":
                    asset_id = str(uuid.UUID(item["asset_id"]))
                    image_path = directory / f"{asset_id}.png"
                    if not image_path.is_file():
                        raise ValueError("Изображение не найдено.")
                    placements.append(Placement("image", page, x, y, width, height, image_path=image_path))
                elif item.get("kind") == "text":
                    value = item["text"]
                    font_size = float(item["font_size"])
                    if not isinstance(value, str) or len(value) > 500 or not math.isfinite(font_size) or not 6 <= font_size <= 96:
                        raise ValueError("Некорректный текст.")
                    placements.append(Placement("text", page, x, y, width, height, text=value, font_size=font_size))
                else:
                    raise ValueError("Неизвестный тип элемента.")
            return placements
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(str(exc) or "Некорректные элементы.") from exc

    @app.post("/api/documents/<document_id>/export")
    def export(document_id: str):
        directory = document_dir(document_id)
        try:
            sizes = page_sizes(directory / "document.pdf")
            placements = parse_placements(request.form.get("placements", ""), directory, sizes)
            certificate = request.files.get("certificate")
            with tempfile.TemporaryDirectory(prefix="pdf-editor-export-") as temporary:
                temp = Path(temporary)
                unsigned = temp / "unsigned.pdf"
                export_pdf(directory / "document.pdf", unsigned, placements)
                output = unsigned
                if certificate:
                    password = request.form.get("password", "")
                    if not password:
                        raise ValueError("Введите пароль сертификата.")
                    certificate_path = temp / "certificate.p12"
                    certificate.save(certificate_path)
                    output = temp / "signed.pdf"
                    sign_pdf_with_pkcs12(unsigned, output, certificate_path, password)
                data = BytesIO(output.read_bytes())
            filename = "signed-document.pdf" if certificate else "edited-document.pdf"
            return send_file(data, mimetype="application/pdf", as_attachment=True,
                             download_name=filename, max_age=0)
        except (ValueError, PdfEditorError, DigitalSigningError) as exc:
            return jsonify(error=str(exc)), 400

    @app.post("/api/certificates")
    def create_certificate():
        data = request.get_json(silent=True) or {}
        try:
            with tempfile.TemporaryDirectory(prefix="pdf-editor-cert-") as temporary:
                path = Path(temporary) / "certificate.p12"
                create_self_signed_pkcs12(path, str(data.get("name", "")),
                                          str(data.get("email", "")), str(data.get("password", "")))
                content = BytesIO(path.read_bytes())
            return send_file(content, mimetype="application/x-pkcs12", as_attachment=True,
                             download_name="personal-signing-certificate.p12", max_age=0)
        except DigitalSigningError as exc:
            return jsonify(error=str(exc)), 400

    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


app = create_app()
