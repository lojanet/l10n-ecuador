# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ec_import_create_product = fields.Boolean(
        "Create Product if not exists?",
        related="company_id.l10n_ec_import_create_product",
        readonly=False,
    )
    l10n_ec_import_create_document_automatic = fields.Boolean(
        "Create Document Automatic?",
        related="company_id.l10n_ec_import_create_document_automatic",
        readonly=False,
    )

    l10n_ec_import_alias_id = fields.Many2one(
        comodel_name="mail.alias",
        string="Mail for electronic documents",
        related="company_id.l10n_ec_import_alias_id",
        readonly=False,
    )
    l10n_ec_check_data_document_automatic = fields.Boolean(
        "Verify electronic document data?",
        related="company_id.l10n_ec_check_data_document_automatic",
        readonly=False,
    )
    l10n_ec_check_document_exist = fields.Boolean(
        related="company_id.l10n_ec_check_document_exist",
        readonly=False,
    )
