from pathlib import Path

from reportlab.pdfgen import canvas

from pdf_editor.digital_signing import (
    create_self_signed_pkcs12,
    has_embedded_signature,
    sign_pdf_with_pkcs12,
)


def test_create_certificate_and_sign_pdf(tmp_path: Path) -> None:
    certificate = tmp_path / "test-certificate.p12"
    unsigned = tmp_path / "unsigned.pdf"
    signed = tmp_path / "signed.pdf"

    create_self_signed_pkcs12(
        certificate,
        common_name="Test Signer",
        email="signer@example.test",
        password="correct horse battery staple",
    )
    assert certificate.exists()

    pdf = canvas.Canvas(str(unsigned), pagesize=(300, 400))
    pdf.drawString(30, 350, "Digitally signed test document")
    pdf.save()

    sign_pdf_with_pkcs12(
        unsigned,
        signed,
        certificate,
        "correct horse battery staple",
    )
    assert signed.exists()
    assert has_embedded_signature(signed)
