from odoo import fields
from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nECCommon(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(
        cls,
        chart_template_ref="l10n_ec.l10n_ec_ifrs",
    ):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.company = cls.company_data["company"]
        cls.company.write(
            {
                "l10n_ec_invoice_version": False,
                "country_id": cls.env.ref("base.ec").id,
            }
        )
        # Models
        cls.Partner = cls.env["res.partner"].with_company(cls.company).sudo()
        cls.Journal = cls.env["account.journal"].with_company(cls.company)
        cls.AccountMove = cls.env["account.move"].with_company(cls.company)
        cls.AccountFiscalPosition = cls.env["account.fiscal.position"].with_company(
            cls.company
        )
        cls.Tax = cls.env["account.tax"].with_company(cls.company)
        cls.TaxGroup = cls.env["account.tax.group"].with_company(cls.company)
        # Dates
        cls.current_datetime = fields.Datetime.context_timestamp(
            cls.AccountMove, fields.Datetime.now()
        )
        cls.current_date = fields.Date.context_today(cls.AccountMove)
        # Partners
        cls.partner_contact = cls.company.partner_id
        cls.partner_cf = cls.Partner.create(
            {
                "name": "Consumidor Final",
                "vat": "9999999999999",
                "country_id": cls.env.ref("base.ec").id,
            }
        )

        # Impuestos
        cls.tax_group_vat = cls.TaxGroup.search(
            [("l10n_ec_type", "=", "vat12")], limit=1
        )
        cls.taxes_zero_vat = cls.Tax.search(
            [("tax_group_id.l10n_ec_type", "=", "zero_vat")], limit=2
        )
        cls.taxes_vat = cls.Tax.search(
            [("tax_group_id", "=", cls.tax_group_vat.id)], limit=2
        )
        cls.tax_not_charged_vat = cls.Tax.search(
            [("tax_group_id.l10n_ec_type", "=", "not_charged_vat")], limit=1
        )
        cls.tax_exempt_vat = cls.Tax.search(
            [("tax_group_id.l10n_ec_type", "=", "exempt_vat")], limit=1
        )
        cls.tax_group_withhold_vat = cls.TaxGroup.search(
            [("l10n_ec_type", "=", "withhold_vat")], limit=1
        )
        cls.tax_group_withhold_profit = cls.TaxGroup.search(
            [("l10n_ec_type", "=", "withhold_income_tax")], limit=1
        )
        # Diarios
        cls.journal_sale = cls.company_data["default_journal_sale"]
        cls.journal_purchase = cls.company_data["default_journal_purchase"]
        cls.journal_cash = cls.company_data["default_journal_cash"]

        # Number authorization
        cls.number_authorization_electronic = "".rjust(49, "1")

    def _setup_company_ec(self):
        """Configurar datos para compañia ecuatoriana"""
        self.company.write(
            {
                "vat": "1190033814001",
                "currency_id": self.env.ref("base.USD").id,
            }
        )

    def _l10n_ec_create_form_move(
        self,
        move_type=None,
        internal_type=None,
        form_id=None,
    ):
        """Método base con datos genericos para crear formulario de:
           Faturas, notas de crédito/debito, retenciones de venta
        :param move_type: Tipo de documento (in_invoice,in_refund,withhold)
            si no se envia se coloca Factura de compra "in_invoice"
        :param internal_type: Tipo interno del documento(invoice,credit_note,
           debit_note,withholding) si no envia se coloca factura "invoice"
        :param form_id: ID del formulario si fuese diferente al de la factura,
           por defecto None
        """
        move_type = move_type or "in_invoice"
        internal_type = internal_type or "invoice"
        move_form = Form(
            self.AccountMove.with_context(
                default_move_type=move_type,
                internal_type=internal_type,
                mail_create_nosubscribe=True,
            ),
            form_id,
        )
        return move_form
