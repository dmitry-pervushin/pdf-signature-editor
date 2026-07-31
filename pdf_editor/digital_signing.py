from __future__ import annotations

import os
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers
from pyhanko.sign.signers import PdfSignatureMetadata, PdfSigner
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from .i18n import tr as _


class DigitalSigningError(RuntimeError):
    pass


def create_self_signed_pkcs12(
    output_path: Path,
    common_name: str,
    email: str,
    password: str,
    validity_years: int = 5,
) -> None:
    if not common_name.strip():
        raise DigitalSigningError(_("certificate_name_required"))
    if not password:
        raise DigitalSigningError(_("certificate_password_required"))

    try:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=3072,
        )
        attributes = [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name.strip()),
        ]
        if email.strip():
            attributes.append(
                x509.NameAttribute(NameOID.EMAIL_ADDRESS, email.strip())
            )
        subject = issuer = x509.Name(attributes)
        now = datetime.now(UTC)

        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365 * validity_years))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=True,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=None,
                    decipher_only=None,
                ),
                True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
                False,
            )
        )
        if email.strip():
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.RFC822Name(email.strip())]),
                False,
            )
        certificate = builder.sign(private_key, hashes.SHA256())

        data = pkcs12.serialize_key_and_certificates(
            name=common_name.strip().encode("utf-8"),
            key=private_key,
            cert=certificate,
            cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(
                password.encode("utf-8")
            ),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        if os.name == "posix":
            output_path.chmod(0o600)
    except DigitalSigningError:
        raise
    except Exception as exc:
        raise DigitalSigningError(
            _("certificate_create_failed_detail", error=exc)
        ) from exc


def sign_pdf_with_pkcs12(
    input_path: Path,
    output_path: Path,
    certificate_path: Path,
    password: str,
) -> None:
    try:
        # pyHanko logs a full traceback for an incorrect password. The GUI
        # reports a concise error instead, so temporarily silence that logger.
        pkcs12_logger = logging.getLogger("pyhanko.sign.signers.pdf_cms")
        logger_was_disabled = pkcs12_logger.disabled
        pkcs12_logger.disabled = True
        try:
            signer = signers.SimpleSigner.load_pkcs12(
                certificate_path,
                passphrase=password.encode("utf-8"),
            )
        finally:
            pkcs12_logger.disabled = logger_was_disabled
        if signer is None:
            raise DigitalSigningError(_("certificate_open_failed"))

        field_name = f"Signature_{uuid.uuid4().hex[:12]}"
        metadata = PdfSignatureMetadata(
            field_name=field_name,
            reason="Signed with PDF Signature Editor",
        )
        with input_path.open("rb") as input_stream:
            writer = IncrementalPdfFileWriter(input_stream)
            with output_path.open("wb") as output_stream:
                PdfSigner(metadata, signer=signer).sign_pdf(
                    writer,
                    output=output_stream,
                )
    except DigitalSigningError:
        raise
    except Exception as exc:
        raise DigitalSigningError(_("pdf_sign_failed_detail", error=exc)) from exc

    if not has_embedded_signature(output_path):
        raise DigitalSigningError(_("signature_verification_failed"))


def has_embedded_signature(pdf_path: Path) -> bool:
    try:
        with pdf_path.open("rb") as stream:
            reader = PdfFileReader(stream)
            if not reader.embedded_signatures:
                return False
            embedded_signature = reader.embedded_signatures[-1]
            validation_context = ValidationContext(
                trust_roots=[embedded_signature.signer_cert],
                allow_fetching=False,
                revocation_mode="soft-fail",
            )
            status = validate_pdf_signature(
                embedded_signature,
                signer_validation_context=validation_context,
            )
            return bool(status.intact and status.valid)
    except Exception:
        return False
