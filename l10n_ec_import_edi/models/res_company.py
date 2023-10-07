# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ec_import_alias_id = fields.Many2one(
        comodel_name="mail.alias",
        string="Mail for electronic documents",
    )
    l10n_ec_import_create_product = fields.Boolean("Create Product if not exists?")
    l10n_ec_import_create_document_automatic = fields.Boolean(
        "Create Document Automatic?"
    )
    l10n_ec_check_data_document_automatic = fields.Boolean(
        "Verify electronic document data?", default=True
    )
    l10n_ec_check_document_exist = fields.Boolean(
        "Verify document related exist on System?", default=True
    )
