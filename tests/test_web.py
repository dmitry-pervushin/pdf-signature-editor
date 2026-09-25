import json
from io import BytesIO

from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from pdf_editor.digital_signing import has_embedded_signature
from pdf_editor.web import create_app


def sample_pdf():
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(300, 400))
    pdf.drawString(20, 370, "Original document")
    pdf.save()
    stream.seek(0)
    return stream


def test_web_upload_preview_and_export(tmp_path):
    client = create_app(tmp_path).test_client()
    response = client.post("/api/documents", data={"file": (sample_pdf(), "sample.pdf")})
    assert response.status_code == 200
    document_id = response.json["id"]
    assert response.json["pages"] == [{"width": 300.0, "height": 400.0}]

    preview = client.get(f"/api/documents/{document_id}/pages/1/preview")
    assert preview.status_code == 200
    assert preview.data.startswith(b"\x89PNG")

    image = BytesIO()
    Image.new("RGBA", (100, 40), (12, 50, 90, 255)).save(image, "PNG")
    image.seek(0)
    asset = client.post(f"/api/documents/{document_id}/assets", data={"file": (image, "signature.png")})
    assert asset.status_code == 200
    assert client.get(f"/api/documents/{document_id}/assets/{asset.json['id']}").status_code == 200

    placements = [
        {"kind": "image", "page_index": 0, "x": 20, "y": 200, "width": 100, "height": 40, "asset_id": asset.json["id"]},
        {"kind": "text", "page_index": 0, "x": 20, "y": 260, "width": 120, "height": 22, "text": "Approved", "font_size": 16},
    ]
    result = client.post(f"/api/documents/{document_id}/export", data={"placements": json.dumps(placements)})
    assert result.status_code == 200
    reader = PdfReader(BytesIO(result.data))
    assert len(reader.pages) == 1
    assert "Original document" in reader.pages[0].extract_text()
    assert "Approved" in reader.pages[0].extract_text()


def test_web_rejects_invalid_placements_and_files(tmp_path):
    client = create_app(tmp_path).test_client()
    assert client.post("/api/documents", data={"file": (BytesIO(b"bad"), "bad.pdf")}).status_code == 400
    document_id = client.post("/api/documents", data={"file": (sample_pdf(), "sample.pdf")}).json["id"]
    assert client.post(f"/api/documents/{document_id}/assets", data={"file": (BytesIO(b"bad"), "bad.png")}).status_code == 400
    invalid = [{"kind": "text", "page_index": 0, "x": 299, "y": 10, "width": 20, "height": 20, "text": "Oops", "font_size": 12}]
    assert client.post(f"/api/documents/{document_id}/export", data={"placements": json.dumps(invalid)}).status_code == 400
    assert client.get("/api/documents/not-a-uuid/pages/1/preview").status_code == 404


def test_web_creates_certificate_and_signs_export(tmp_path):
    client = create_app(tmp_path / "documents").test_client()
    document_id = client.post("/api/documents", data={"file": (sample_pdf(), "sample.pdf")}).json["id"]
    certificate = client.post("/api/certificates", json={
        "name": "Test Signer", "email": "signer@example.test", "password": "test password",
    })
    assert certificate.status_code == 200
    result = client.post(f"/api/documents/{document_id}/export", data={
        "placements": "[]",
        "certificate": (BytesIO(certificate.data), "certificate.p12"),
        "password": "test password",
    })
    assert result.status_code == 200
    signed = tmp_path / "signed.pdf"
    signed.write_bytes(result.data)
    assert has_embedded_signature(signed)
