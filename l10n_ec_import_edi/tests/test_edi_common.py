import base64

from odoo.tests import tagged
from odoo.tools import misc, os

from odoo.addons.account_edi.tests.common import AccountEdiTestCommon

from .test_common import TestL10nECCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nECEdiCommon(AccountEdiTestCommon, TestL10nECCommon):
    @classmethod
    def setUpClass(
        cls,
        chart_template_ref="l10n_ec.l10n_ec_ifrs",
        edi_format_ref="l10n_ec_account_edi.edi_format_ec_sri",
    ):
        super().setUpClass(
            chart_template_ref=chart_template_ref, edi_format_ref=edi_format_ref
        )
        cls.env.user.tz = "America/Guayaquil"
        # Archivo xml básico
        cls.attachment = cls.env["ir.attachment"].create(
            {
                "name": "invoice.xml",
                "datas": base64.encodebytes(
                    b"<?xml version='1.0' encoding='UTF-8'?><Invoice/>"
                ),
                "mimetype": "application/xml",
            }
        )

        file_path = os.path.join(
            "l10n_ec_account_edi", "tests", "certificates", "test.p12"
        )
        file_content = misc.file_open(file_path, mode="rb").read()
        # Crear certificado de firma electrónica válido
        cls.certificate = (
            cls.env["sri.key.type"]
            .sudo()
            .create(
                {
                    "name": "Test",
                    "file_name": "test.p12",
                    "password": "123456",
                    "file_content": base64.b64encode(file_content),
                    "company_id": cls.company_data["company"].id,
                },
            )
        )
