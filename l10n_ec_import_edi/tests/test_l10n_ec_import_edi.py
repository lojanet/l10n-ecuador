import logging
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import misc, os

from odoo.addons.l10n_ec_account_edi.models.account_edi_format import AccountEdiFormat
from odoo.addons.l10n_ec_import_edi.models.l10n_ec_edi_imported import (
    L10nEcElectronicDocumentImported,
)

from .test_edi_common import TestL10nECEdiCommon

_logger = logging.getLogger(__name__)


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nClDte(TestL10nECEdiCommon):
    def test_wizard_import_edi(self):
        """Test de prueba wizard importar txt de documentos electrónicos"""
        self._setup_company_ec()

    def test_onchange_l10n_ec_xml_access_key(self):
        """Test de prueba onchange del número de autorización en Facturas de Proveedor"""
        self._setup_company_ec()
        self.env["ir.config_parameter"].sudo().set_param(
            "l10n_ec_check_data_document_automatic", True
        )
        # colocar varias opciones, el nro aut (vacio,< a 49, no existe, existe, existe pero es de otra empresa)
        self.number_authorization_electronic = (
            "0302202301119175142200120051000000570191234567819"
        )
        form = self._l10n_ec_create_form_move()

        def mock_l10n_ec_get_edi_wsclient(self, a, b):
            return "VACIO"

        def mock_l10n_ec_download_file(self, client_ws, l10n_ec_xml_access_key):
            file_path = os.path.join(
                "l10n_ec_import_edi", "tests", "edi", "Notacredito_1.xml"
            )
            file_content = misc.file_open(file_path, mode="rb").read()
            print("Factura:", file_content)
            return file_content

        with patch.object(
            AccountEdiFormat,
            "_l10n_ec_get_edi_wsclient",
            mock_l10n_ec_get_edi_wsclient,
        ):
            with patch.object(
                L10nEcElectronicDocumentImported,
                "_l10n_ec_download_file",
                mock_l10n_ec_download_file,
            ):
                form.l10n_ec_authorization_number = self.number_authorization_electronic
                print(
                    "nombre del cliente:",
                    form.partner_id.name,
                    "El RUC",
                    form.partner_id.vat,
                )
                print(
                    "",
                )
                self.assertEqual(
                    form.partner_id.name, "ESTACION DE SERVICIO VALDIVIESO Y COMPANIA"
                )
                self.assertEqual(form.partner_id.vat, "1191757706001")

        # with self.assertRaises(UserError):
        #     invoice.action_post()
        # self.product_a.list_price = 40
        # form = self._l10n_ec_create_form_move(
        #     move_type="out_invoice",
        #     internal_type="invoice",
        #     partner=self.env.ref("l10n_ec.ec_final_consumer"),
        # )
        # invoice = form.save()
        # invoice.action_post()
        # self.assertEqual(invoice.state, "posted")
