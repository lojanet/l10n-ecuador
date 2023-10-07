import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from .data import TAX_SUPPORT

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ec_withholding_type = fields.Selection(
        [
            ("purchase", "Purchase"),
            ("sale", "Sale"),
        ],
        string="Withholding Type",
    )
    l10n_ec_withhold_line_ids = fields.One2many(
        comodel_name="account.move.line",
        inverse_name="l10n_ec_withhold_id",
        string="Lineas de retencion",
        readonly=True,
    )
    l10n_ec_withhold_ids = fields.Many2many(
        "account.move",
        relation="l10n_ec_withhold_invoice_rel",
        column1="move_id",
        column2="withhold_id",
        string="Withhold",
        readonly=True,
        copy=False,
    )

    l10n_ec_withhold_count = fields.Integer(
        string="Withholds Count", compute="_compute_l10n_ec_withhold_count"
    )

    l10n_ec_withhold_active = fields.Boolean(
        string="Withholds ?",
        compute="_compute_l10n_ec_withhold_active",
        store=True,
    )

    l10n_ec_tax_support = fields.Selection(
        TAX_SUPPORT, string="Tax Support", help="Tax support in invoice line"
    )

    @api.constrains("name", "journal_id", "state")
    def _check_unique_sequence_number(self):
        if (
            self.l10n_latam_internal_type == "withhold"
            and self.l10n_ec_journal_type == "sale"
        ):
            withhold = self.filtered(
                lambda x: x.is_withhold() and x.l10n_latam_use_documents
            )
            return super(AccountMove, self - withhold)._check_unique_sequence_number()

        return super(AccountMove, self)._check_unique_sequence_number()

    def is_invoice(self, include_receipts=False):
        # when user print report
        # if is withhold force print(skip exception on server)
        if self.env.context.get("force_print_withhold") and self.is_withhold():
            return True
        return super(AccountMove, self).is_invoice(include_receipts)

    @api.model
    def get_withhold_types(self):
        return ["purchase", "sale"]

    def is_withhold(self):
        return (
            self.company_id.account_fiscal_country_id.code == "EC"
            and self.l10n_latam_internal_type == "withhold"
            and self.l10n_ec_withholding_type in self.get_withhold_types()
        )

    def is_purchase_withhold(self):
        return self.l10n_ec_withholding_type == "purchase" and self.is_withhold()

    def action_invoice_print(self):
        res = super(AccountMove, self).action_invoice_print()
        if any(move.is_withhold() for move in self):
            res["context"]["force_print_withhold"] = True
        return res

    def action_invoice_sent(self):
        res = super(AccountMove, self).action_invoice_sent()
        if any(move.is_withhold() for move in self):
            res["context"]["force_print_withhold"] = True
        return res

    def _get_name_invoice_report(self):
        self.ensure_one()
        if self.is_withhold():
            return "l10n_ec_account_edi.report_invoice_document"
        return super()._get_name_invoice_report()

    def action_try_create_ecuadorian_withhold(self):
        action = {}
        if any(
            move.is_purchase_document() and move.l10n_ec_withhold_active
            for move in self
        ):
            if len(self) > 1:
                raise UserError(
                    _(
                        "You can't create Withhold for some invoice, "
                        "Please select only a Invoice."
                    )
                )
            action = self._action_create_purchase_withhold_wizard()
        elif any(
            move.is_sale_document() and move.l10n_ec_withhold_active for move in self
        ):
            action = self._action_create_sale_withhold_wizard()
        else:
            raise UserError(
                _(
                    "Please select only invoice "
                    "what satisfies the requirements for create withhold"
                )
            )
        return action

    def _action_create_sale_withhold_wizard(self):
        action = self.env.ref(
            "l10n_ec_withhold.l10n_ec_wizard_sale_withhold_action_window"
        ).read()[0]
        action["views"] = [
            (
                self.env.ref(
                    "l10n_ec_withhold.l10n_ec_wizard_sale_withhold_form_view"
                ).id,
                "form",
            )
        ]
        ctx = safe_eval(action["context"])
        ctx.pop("default_type", False)
        ctx.update(self.env.context.copy())
        action["context"] = ctx
        return action

    def _action_create_purchase_withhold_wizard(self):
        self.ensure_one()
        action = self.env.ref(
            "l10n_ec_withhold.l10n_ec_wizard_purchase_withhold_action_window"
        ).read()[0]
        action["views"] = [
            (
                self.env.ref(
                    "l10n_ec_withhold.l10n_ec_wizard_purchase_withhold_form_view"
                ).id,
                "form",
            )
        ]
        ctx = safe_eval(action["context"])
        ctx.pop("default_type", False)
        ctx.update(
            {
                "default_partner_id": self.partner_id.id,
                "default_invoice_id": self.id,
                "default_issue_date": self.invoice_date,
            }
        )
        action["context"] = ctx
        return action

    def action_show_l10n_ec_withholds(self):
        withhold_ids = self.l10n_ec_withhold_ids.ids
        action = self.env.ref("account.action_move_journal_line").read()[0]
        context = {
            "create": False,
            "delete": True,
            "edit": False,
        }
        action["context"] = context
        action["name"] = _("Withholding")
        view_tree_id = self.env.ref(
            "l10n_ec_withhold.view_account_move_withhold_tree"
        ).id
        view_form_id = self.env.ref(
            "l10n_ec_withhold.view_account_move_withhold_form"
        ).id
        action["view_mode"] = "form"
        action["views"] = [(view_form_id, "form")]
        action["res_id"] = withhold_ids[0]
        if len(withhold_ids) > 1:
            action["view_mode"] = "tree,form"
            action["views"] = [(view_tree_id, "tree"), (view_form_id, "form")]
            action["domain"] = [("id", "in", withhold_ids)]

        return action

    @api.depends("l10n_ec_withhold_ids")
    def _compute_l10n_ec_withhold_count(self):
        for move in self:
            move.l10n_ec_withhold_count = len(move.l10n_ec_withhold_ids)

    @api.depends(
        "state",
        "fiscal_position_id",
        "company_id",
    )
    def _compute_l10n_ec_withhold_active(self):
        for move in self:
            if move.state != "posted" or move.move_type not in [
                "in_invoice",
                "out_invoice",
            ]:
                move.l10n_ec_withhold_active = False
                continue
            # En Ventas si la posición fiscal del cliente retiene
            move.l10n_ec_withhold_active = move.fiscal_position_id.l10n_ec_withhold
            if (
                move.move_type in move.get_purchase_types()
                and move.l10n_ec_withhold_active
                and self.company_id.property_account_position_id
            ):
                # En Compras si la posición fiscal retiene y el proveedor retiene,
                # vemos si la compañía retiene
                move.l10n_ec_withhold_active = (
                    self.company_id.property_account_position_id.l10n_ec_withhold
                )

    def _get_l10n_ec_tax_support(self):
        self.ensure_one()
        return self.partner_id.l10n_ec_tax_support

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        self.l10n_ec_tax_support = self._get_l10n_ec_tax_support()
        return super(AccountMove, self)._onchange_partner_id()


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    l10n_ec_withhold_id = fields.Many2one(
        comodel_name="account.move",
        string="Withhold",
        readonly=True,
        copy=False,
    )

    l10n_ec_tax_support = fields.Selection(
        TAX_SUPPORT,
        string="Tax Support",
        copy=False,
        help="Tax support in invoice line",
    )

    l10n_ec_invoice_withhold_id = fields.Many2one(
        comodel_name="account.move",
        string="Withhold",
        readonly=True,
        copy=False,
    )

    @api.onchange("name", "product_id")
    def _onchange_get_l10n_ec_tax_support(self):
        for line in self:
            line.l10n_ec_tax_support = line._get_l10n_ec_tax_support()

    def _get_l10n_ec_tax_support(self):
        self.ensure_one()
        if (
            not self.l10n_ec_tax_support
            and self.move_id
            and self.move_id.l10n_ec_tax_support
        ):
            return self.move_id.l10n_ec_tax_support
        return False
