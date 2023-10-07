import base64
import logging
from datetime import datetime

from lxml import etree

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10nEcElectronicDocumentImported(models.Model):
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
        "l10n_ec.xml.parser",
    ]
    _name = "l10n_ec.edi.imported"
    _description = "Imported Document Electronics"
    _rec_name = "l10n_latam_document_number"

    l10n_latam_document_number = fields.Char(
        string="Document Number", size=17, index=True, copy=False, readonly=True
    )
    l10n_latam_document_type_id = fields.Many2one(
        "l10n_latam.document.type", string="Document Type", readonly=True
    )
    internal_type = fields.Selection(
        [
            ("invoice", "Invoices"),
            ("debit_note", "Debit Notes"),
            ("credit_note", "Credit Notes"),
            ("withholding", "Withholding"),
        ],
        readonly=True,
    )
    l10n_ec_xml_access_key = fields.Char(
        "Access Key",
        size=49,
        copy=False,
        readonly=True,
        states={"draft": [("readonly", False)]},
    )
    l10n_ec_electronic_authorization = fields.Char(
        "Electronic Authorization",
        size=49,
        copy=False,
        readonly=True,
    )
    l10n_ec_authorization_date = fields.Datetime(
        "Date Authorization", copy=False, readonly=True
    )
    invoice_date = fields.Date("Date Emission", copy=False, readonly=True)
    partner_id = fields.Many2one("res.partner", "Partner", copy=False, readonly=True)
    move_id = fields.Many2one(
        "account.move", "Document related", copy=False, readonly=False
    )
    l10n_ec_original_invoice_id = fields.Many2one(
        "account.move", "Document Mod", copy=False, readonly=True
    )
    l10n_ec_legacy_document = fields.Boolean(
        string="Is External Doc. Modified?",
        help="With this option activated, the system will not require "
        "an invoice to issue the Debut or Credit Note",
    )
    l10n_ec_legacy_document_date = fields.Date(string="External Document Date")
    l10n_ec_legacy_document_number = fields.Char(string="External Document Number")
    document_line_ids = fields.One2many(
        "l10n_ec.edi.imported.line",
        "document_id",
        "Details",
        copy=False,
        readonly=True,
    )
    document_logs_ids = fields.One2many(
        "l10n_ec.edi.imported.logs",
        "document_id",
        "Logs",
        copy=False,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending"),
            ("done", "Done"),
            ("cancel", "Cancel"),
        ],
        required=True,
        readonly=True,
        default="draft",
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        "Company",
        copy=False,
        readonly=True,
        default=lambda self: self.env.company,
    )

    manual_move = fields.Boolean(
        string="Set Move Manual?",
        readonly=True,
        states={"draft": [("readonly", False)], "pending": [("readonly", False)]},
    )

    @api.onchange("l10n_ec_xml_access_key")
    def _onchange_l10n_ec_xml_access_key(self):
        warning = {}
        messages = []
        invoice_model = self.env["account.move"]
        if self.l10n_ec_xml_access_key and len(self.l10n_ec_xml_access_key) == 49:
            domain = [
                (
                    "l10n_ec_xml_access_key",
                    "=",
                    self.l10n_ec_xml_access_key,
                ),
            ]
            current_edi = self.search(domain, limit=1)
            if current_edi:
                messages.append(
                    f"Ya existe un documento con clave de accesso: "
                    f"{current_edi.l10n_ec_xml_access_key} no se creo otro documento"
                )
                self.l10n_ec_xml_access_key = ""
            else:
                messages, current_invoice = invoice_model.l10n_ec_check_edi_exist(
                    self.l10n_ec_xml_access_key
                )
                if current_invoice:
                    self.l10n_ec_xml_access_key = ""
        if messages:
            warning = {
                "title": _("Information for User"),
                "message": "\n".join(messages),
            }
        return {"warning": warning}

    def unlink(self):
        for document in self:
            if document.state not in ("draft", "pending"):
                raise UserError(_("Cant'n unlink Document, Try cancel!"))
        return super(L10nEcElectronicDocumentImported, self).unlink()

    @api.model
    def action_cron_download_file(self):
        all_companies = self.env["res.company"].search([])
        for company in all_companies:
            recs_to_process = self.search(
                [
                    ("state", "=", "draft"),
                    ("l10n_ec_xml_access_key", "!=", False),
                    ("company_id", "=", company.id),
                ],
                limit=100,
            )
            recs_to_process.with_context(
                allowed_company_ids=company.ids
            ).action_download_file()
        return True

    def action_download_file(self):
        return self._action_download_file()

    def _action_download_file(self, client_ws=None):
        # webservice para consultar documentos autorizados en ambiente produccion
        xml_data = self.env["account.edi.format"]
        if client_ws is None:
            client_ws = xml_data._l10n_ec_get_edi_ws_client(
                "production", "authorization"
            )
        for document in self:
            try:
                xml_attachment = document.l10n_ec_get_attachments_electronic()
                if not xml_attachment:
                    xml_authorized = self._l10n_ec_download_file(
                        client_ws, document.l10n_ec_xml_access_key
                    )
                    xml_attachment = (
                        document.l10n_ec_action_create_attachments_electronic(
                            xml_authorized
                        )
                    )
                document.with_context(
                    allowed_company_ids=document.company_id.ids
                ).message_post(attachment_ids=xml_attachment.ids)
            except Exception as ex:
                raise UserError(tools.ustr(ex)) from None
        return True

    def action_done(self):
        AccountMove = self.env["account.move"]
        invoices = self.mapped("move_id")
        # TODO: Procesar retenciones recibidas, temporalmete puesto en False
        withholdings = False
        documents_exist = self.filtered("move_id")
        if documents_exist:
            documents_exist.write(
                {
                    "state": "done",
                }
            )
        for document in self - documents_exist:
            vals_to_write = {}
            message_list = []
            attachments = self.env["ir.attachment"].search(
                [("res_id", "=", document.id), ("res_model", "=", self._name)]
            )
            if not attachments:
                continue
            for attachment in attachments:
                try:
                    content = base64.b64decode(attachment.datas)
                    tree = etree.fromstring(content)
                    if not self._l10n_ec_is_xml_valid(tree):
                        continue
                except Exception:
                    _logger.exception(
                        f"The xml file: {attachment.name} is badly formatted."
                    )
                    continue
                document_list = self._l10n_ec_get_document_info_from_xml(tree)
                for document_info in document_list:
                    message_list, vals_to_write = self._l10n_ec_vals_to_write(
                        AccountMove, document, document_info
                    )
            if message_list:
                vals_to_write.update(
                    {
                        "document_logs_ids": [
                            (0, 0, {"name": x}) for x in message_list
                        ],
                    }
                )
            if vals_to_write:
                document.write(vals_to_write)
        if withholdings:
            domain = [("id", "in", withholdings.ids)]
            res_model = withholdings._name
        else:
            domain = [("id", "in", invoices.ids)]
            res_model = invoices._name
        action_vals = {
            "name": _("Generated Documents"),
            "domain": domain,
            "res_model": res_model,
            "views": [[False, "tree"], [False, "form"]],
            "type": "ir.actions.act_window",
            "context": self._context,
        }
        if withholdings:
            if len(withholdings) == 1:
                action_vals.update({"res_id": withholdings[0].id, "view_mode": "form"})
            else:
                action_vals["view_mode"] = "tree,form"
        elif invoices:
            if len(invoices) == 1:
                action_vals.update({"res_id": invoices[0].id, "view_mode": "form"})
            else:
                action_vals["view_mode"] = "tree,form"
        else:
            action_vals = False
        return action_vals

    def _l10n_ec_vals_to_write(self, AccountMove, document, document_info):
        vals_to_write = {}
        message_list = []
        if document_info.tag in ["factura", "notaCredito", "notaDebito"]:
            default_type = "in_invoice"
            if document.internal_type == "credit_note":
                default_type = "in_refund"
            ctx = {
                "allowed_company_ids": document.company_id.ids,
                "default_move_type": default_type,
                "internal_type": document.internal_type,
            }
            try:
                invoice = AccountMove.with_context(**ctx).new({})
                if document_info.tag == "factura":
                    (
                        messages,
                        invoice,
                    ) = invoice._l10n_ec_create_invoice_from_xml(document_info)
                    message_list.extend(messages)
                elif document_info.tag == "notaCredito":
                    (
                        messages,
                        invoice,
                    ) = invoice._l10n_ec_create_credit_note_from_xml(document_info)
                    message_list.extend(messages)
                elif document_info.tag == "notaDebito":
                    (
                        messages,
                        invoice,
                    ) = invoice._l10n_ec_create_debit_note_from_xml(document_info)
                    message_list.extend(messages)
                # solo crear el documento cuando haya lineas
                # para evitar dejar un documento en borrador
                # que no aparezca en ningun menu
                if invoice.line_ids:
                    # se espera tener un NewId pero si el documento
                    # ya existia no crearlo nuevamente
                    is_new_invoice = isinstance(invoice.id, models.NewId)
                    if is_new_invoice:
                        values = invoice._convert_to_write(invoice._cache)
                        invoice = AccountMove.with_context(**ctx).create(values)
                    vals_to_write.update(
                        {
                            "move_id": invoice.id,
                            "state": "done",
                        }
                    )
            except Exception as ex:
                # capturar excepcion para mostrarla
                # de manera mas amigable al usuario
                raise UserError(tools.ustr(ex)) from None
        elif document_info.tag == "comprobanteRetencion":
            # TODO: Desarrollar la Logica para retenciones recibidas
            messages, new_withholding = self.with_context(
                allowed_company_ids=document.company_id.ids
            )._l10n_ec_create_withhold(document_info)
        return message_list, vals_to_write

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        has_xml_valid = False
        for attachment in msg_dict.get("attachments", []):
            if not attachment.fname.endswith(".xml"):
                continue
            try:
                tree = etree.fromstring(attachment.content)
                if self._l10n_ec_is_xml_valid(tree):
                    has_xml_valid = True
                else:
                    _logger.warning(
                        f"The xml file: {attachment.name} "
                        f"is badly formatted or not find a company, not imported"
                    )
            except Exception:
                _logger.exception(
                    f"The xml file: {attachment.name} is badly formatted."
                )
        # si no es un xml valido evitar crear registros innecesarios en este modelo
        # devolver un recordset vacio
        if not has_xml_valid:
            return self.browse()
        return super(L10nEcElectronicDocumentImported, self).message_new(
            msg_dict, custom_values=custom_values
        )

    @api.returns("mail.message", lambda value: value.id)
    def message_post(self, **kwargs):
        # si no tengo un recordset es xq el adjunto no era valido
        # en la funcion message_new se hace esta verificacion
        if not self:
            return self
        new_message = super(L10nEcElectronicDocumentImported, self).message_post(
            **kwargs
        )
        for attachment in new_message.attachment_ids:
            # lo ideal seria usar el mimetype para saber si es un xml
            # pero cuando viene desde el correo se guarda como text/plain
            if not attachment.name.endswith(".xml"):
                continue
            try:
                content = base64.b64decode(attachment.datas)
                tree = etree.fromstring(content)
                if self._l10n_ec_is_xml_valid(tree):
                    self._l10n_ec_create_record_from_xml(tree)
                    if self.company_id.l10n_ec_import_create_document_automatic:
                        self.action_done()
            except Exception:
                _logger.exception(
                    f"The xml file: {attachment.name} is badly formatted."
                )
        return new_message

    @api.model
    def _l10n_ec_download_file(self, client_ws, l10n_ec_xml_access_key):
        xml_authorized = ""
        response = client_ws.service.autorizacionComprobante(
            claveAccesoComprobante=l10n_ec_xml_access_key
        )
        autorizacion_list = []
        if hasattr(response, "autorizaciones") and response.autorizaciones is not None:
            if not isinstance(response.autorizaciones.autorizacion, list):
                autorizacion_list = [response.autorizaciones.autorizacion]
            else:
                autorizacion_list = response.autorizaciones.autorizacion
        for doc in autorizacion_list:
            if doc.estado == "AUTORIZADO" and doc.comprobante:
                #                print("Comprobante Sin Autorizar directo:",doc.comprobante)
                #                tree = ET.fromstring(doc.comprobante)
                authorization_date = (
                    doc.fechaAutorizacion
                    if hasattr(doc, "fechaAutorizacion")
                    else False
                )
                # si no es una fecha valida, tomar la fecha actual del sistema
                if not isinstance(authorization_date, datetime):
                    authorization_date = fields.Datetime.context_timestamp(
                        self, datetime.now()
                    )
                # crear el xml adjunto para que se procese
                xml_authorized = self._l10n_ec_create_file_authorized(
                    doc.comprobante,  # tree,
                    l10n_ec_xml_access_key,
                    authorization_date,
                    "production",
                )
        #                print("Documento Autorizado: ->", xml_authorized)
        return xml_authorized

    def _l10n_ec_create_record_from_xml(self, tree):
        document_list = self._l10n_ec_get_document_info_from_xml(tree)
        message_list = []
        for document_info in document_list:
            company = self._l10n_ec_get_company_for_xml(document_info)
            messages = []
            if document_info.tag == "factura":
                messages = self.with_context(
                    allowed_company_ids=company.ids
                )._l10n_ec_create_as_invoice(document_info)
            elif document_info.tag == "notaCredito":
                messages = self.with_context(
                    allowed_company_ids=company.ids, internal_type="credit_note"
                )._l10n_ec_create_as_credit_note(document_info)
            elif document_info.tag == "notaDebito":
                messages = self.with_context(
                    allowed_company_ids=company.ids, internal_type="debit_note"
                )._l10n_ec_create_as_debit_note(document_info)
            elif document_info.tag == "comprobanteRetencion":
                messages = self.with_context(
                    allowed_company_ids=company.ids
                )._l10n_ec_create_as_withhold(document_info)
            self.write(
                {
                    "document_logs_ids": [(0, 0, {"name": x}) for x in messages],
                    "state": "pending",
                }
            )
            message_list.extend(messages)
        return message_list

    def _l10n_ec_create_as_invoice(self, document_info):
        InvoiceModel = self.env["account.move"]
        ImportedLineModel = self.env["l10n_ec.edi.imported.line"]
        company = self.env.company
        invoice_type = "in_invoice"
        internal_type = "invoice"
        document_code = document_info.infoTributaria.codDoc.text
        fechaEmision = document_info.infoFactura.fechaEmision.text
        messages = []
        latam_document_type = self.l10n_ec_xml_get_latam_document_type(
            company, document_code
        )
        if not latam_document_type:
            messages.append(
                _("No valid document type found with code: %s") % document_code
            )
        invoice_vals = self.l10n_ec_xml_prepare_invoice_vals(
            company,
            document_info,
            latam_document_type,
            invoice_type,
            fechaEmision,
        )
        messages, current_invoice = InvoiceModel.l10n_ec_check_edi_exist(invoice_vals)
        if current_invoice:
            invoice_vals["move_id"] = current_invoice.id
        document_vals = self.process_vals_before_update(internal_type, invoice_vals)
        document_vals.update(
            {
                "internal_type": internal_type,
                "document_line_ids": [(5, 0)],
                "document_logs_ids": [(5, 0)],
            }
        )
        self.write(document_vals)
        document_line_vals = []
        for detail_xml in document_info.detalles.detalle:
            supplier_taxes, message_tax_list = self.l10n_ec_xml_find_taxes(
                company, detail_xml
            )
            messages.extend(message_tax_list)
            product, message_product_list = self.l10n_ec_xml_find_create_product(
                detail_xml, supplier_taxes, document_vals["partner_id"]
            )
            messages.extend(message_product_list)
            vals_line = self.l10n_ec_xml_prepare_invoice_line_vals(
                detail_xml, product, supplier_taxes
            )
            document_line = ImportedLineModel.new(vals_line)
            vals_line = document_line._convert_to_write(
                {name: document_line[name] for name in document_line._cache}
            )
            document_line_vals.append((0, 0, vals_line))
        self.write(
            {
                "document_line_ids": document_line_vals,
            }
        )
        return messages

    def _l10n_ec_create_as_credit_note(self, document_info):
        InvoiceModel = self.env["account.move"]
        ImportedLineModel = self.env["l10n_ec.edi.imported.line"]
        company = self.env.company
        invoice_type = "in_refund"
        internal_type = "credit_note"
        document_code = document_info.infoTributaria.codDoc.text
        fechaEmision = document_info.infoNotaCredito.fechaEmision.text
        messages = []
        latam_document_type = self.l10n_ec_xml_get_latam_document_type(
            company, document_code
        )
        if not latam_document_type:
            messages.append(
                _("No valid document type found with code: %s") % document_code
            )
        invoice_vals = self.l10n_ec_xml_prepare_credit_note_vals(
            company,
            document_info,
            latam_document_type,
            invoice_type,
            fechaEmision,
        )
        messages, current_invoice = InvoiceModel.l10n_ec_check_edi_exist(invoice_vals)
        if current_invoice:
            invoice_vals["move_id"] = current_invoice.id
        document_vals = self.process_vals_before_update(internal_type, invoice_vals)
        document_vals.update(
            {
                "internal_type": internal_type,
                "document_line_ids": [(5, 0)],
                "document_logs_ids": [(5, 0)],
            }
        )
        self.write(document_vals)
        document_line_vals = []
        for detail_xml in document_info.detalles.detalle:
            supplier_taxes, message_tax_list = self.l10n_ec_xml_find_taxes(
                company, detail_xml
            )
            messages.extend(message_tax_list)
            product, message_product_list = self.l10n_ec_xml_find_create_product(
                detail_xml, supplier_taxes, document_vals["partner_id"]
            )
            messages.extend(message_product_list)
            vals_line = self.l10n_ec_xml_prepare_invoice_line_vals(
                detail_xml, product, supplier_taxes
            )
            document_line = ImportedLineModel.new(vals_line)
            vals_line = document_line._convert_to_write(
                {name: document_line[name] for name in document_line._cache}
            )
            document_line_vals.append((0, 0, vals_line))
        self.write(
            {
                "document_line_ids": document_line_vals,
            }
        )
        return messages

    def _l10n_ec_create_as_debit_note(self, document_info):
        InvoiceModel = self.env["account.move"]
        ImportedLineModel = self.env["l10n_ec.edi.imported.line"]
        company = self.env.company
        invoice_type = "in_refund"
        internal_type = "debit_note"
        document_code = document_info.infoTributaria.codDoc.text
        fechaEmision = document_info.infoNotaDebito.fechaEmision.text
        messages = []
        latam_document_type = self.l10n_ec_xml_get_latam_document_type(
            company, document_code
        )
        if not latam_document_type:
            messages.append(
                _("No valid document type found with code: %s") % document_code
            )
        invoice_vals = self.l10n_ec_xml_prepare_debit_note_vals(
            company,
            document_info,
            latam_document_type,
            invoice_type,
            fechaEmision,
        )
        messages, current_invoice = InvoiceModel.l10n_ec_check_edi_exist(invoice_vals)
        if current_invoice:
            invoice_vals["move_id"] = current_invoice.id
        document_vals = self.process_vals_before_update(internal_type, invoice_vals)
        document_vals.update(
            {
                "internal_type": internal_type,
                "document_line_ids": [(5, 0)],
                "document_logs_ids": [(5, 0)],
            }
        )
        self.write(document_vals)
        document_line_vals = []
        for detail_xml in document_info.motivos.motivo:
            # tomar los impuestos del nodo principal y no del motivo
            supplier_taxes, message_tax_list = self.l10n_ec_xml_find_taxes(
                company, document_info.infoNotaDebito
            )
            messages.extend(message_tax_list)
            product, message_product_list = self.l10n_ec_xml_find_create_product(
                detail_xml, supplier_taxes, document_vals["partner_id"]
            )
            messages.extend(message_product_list)
            vals_line = self.l10n_ec_xml_prepare_debit_note_line_vals(
                detail_xml, product, supplier_taxes
            )
            document_line = ImportedLineModel.new(vals_line)
            vals_line = document_line._convert_to_write(
                {name: document_line[name] for name in document_line._cache}
            )
            document_line_vals.append((0, 0, vals_line))
        self.write(
            {
                "document_line_ids": document_line_vals,
            }
        )
        return messages

    def _l10n_ec_create_as_withhold(self, document_info):
        # TODO: Falta la logica para crear desde Retenciones recibidas
        messages = []
        return messages

    def _l10n_ec_create_withhold(self, document_info):
        # TODO: Falta la logica para crear desde Retenciones recibidas
        messages, new_withholding = []
        return messages, new_withholding

    def _get_document_fields_map(self):
        return {
            "invoice": {"l10n_latam_document_number": "document_number"},
            "credit_note": {"l10n_latam_document_number": "document_number"},
            "debit_note": {"l10n_latam_document_number": "document_number"},
            "withholding": {
                "number": "document_number",
                "electronic_authorization": "l10n_ec_electronic_authorization",
                "issue_date": "invoice_date",
            },
        }

    def process_vals_before_update(self, internal_type, document_vals):
        # cambiar o eliminar campos que no son del documento
        # relacionado account.move, mapear el campo del modelo
        # original con el respectivo campo para esta clase
        document_map = self._get_document_fields_map()
        new_vals = {}
        fields_map = document_map.get(internal_type) or {}
        for field_name in document_vals:
            if field_name in self._fields:
                new_vals[field_name] = document_vals[field_name]
            elif field_name in fields_map:
                new_vals[fields_map[field_name]] = document_vals[field_name]
        return new_vals

    # reemplazar funciones genericas para agregar ciertos campos que no son de account.move.line
    def l10n_ec_xml_prepare_invoice_line_vals(
        self, detail_xml, product, supplier_taxes
    ):
        ail_vals = super(
            L10nEcElectronicDocumentImported, self
        ).l10n_ec_xml_prepare_invoice_line_vals(detail_xml, product, supplier_taxes)
        ail_vals["document_id"] = self.id
        ail_vals.pop("move_id", False)
        ail_vals.pop("product_uom_id", False)
        if product:
            ail_vals.pop("name", False)
            ail_vals.update(
                {
                    "product_name": product.name,
                    "product_code": product.default_code,
                }
            )
        else:
            ail_vals["product_name"] = ail_vals.pop("name", "")
            if hasattr(detail_xml, "codigoPrincipal"):
                ail_vals["product_code"] = detail_xml.codigoPrincipal.text
            elif hasattr(detail_xml, "codigoAuxiliar"):
                ail_vals["product_code"] = detail_xml.codigoAuxiliar.text
        return ail_vals

    def l10n_ec_xml_prepare_debit_note_line_vals(
        self, detail_xml, product, supplier_taxes
    ):
        ail_vals = super(
            L10nEcElectronicDocumentImported, self
        ).l10n_ec_xml_prepare_debit_note_line_vals(detail_xml, product, supplier_taxes)
        ail_vals["document_id"] = self.id
        ail_vals.pop("move_id", False)
        ail_vals.pop("product_uom_id", False)
        if product:
            ail_vals.pop("name", False)
            ail_vals.update(
                {
                    "product_name": product.name,
                    "product_code": product.default_code,
                }
            )
        else:
            ail_vals["product_name"] = ail_vals.pop("name", "")
            if hasattr(detail_xml, "codigoPrincipal"):
                ail_vals["product_code"] = detail_xml.codigoPrincipal.text
            elif hasattr(detail_xml, "codigoAuxiliar"):
                ail_vals["product_code"] = detail_xml.codigoAuxiliar.text
        return ail_vals

    def l10n_ec_get_attachments_electronic(self):
        """
        :return: An ir.attachment recordset
        """
        domain = [
            ("res_id", "=", self.id),
            ("res_model", "=", self._name),
            ("name", "=", "%s.xml" % self.l10n_ec_xml_access_key),
            ("description", "=", self.l10n_ec_xml_access_key),
        ]
        return self.env["ir.attachment"].search(domain)

    def l10n_ec_action_create_attachments_electronic(self, file_data=None):
        """
        :return: An ir.attachment recordset
        """
        self.ensure_one()
        ctx = self.env.context.copy()
        # borrar el default_move_type de facturas
        ctx.pop("default_move_type", False)
        AttachmentModel = self.env["ir.attachment"].with_context(**ctx)
        attachment = AttachmentModel.browse()
        if self.l10n_ec_xml_access_key:
            attachment = self.l10n_ec_get_attachments_electronic()
            if not attachment and file_data:
                file_name = self.l10n_ec_xml_access_key
                attachment = AttachmentModel.create(
                    {
                        "name": "%s.xml" % file_name,
                        "res_id": self.id,
                        "res_model": self._name,
                        "datas": base64.encodebytes(file_data.encode()),
                        "store_fname": "%s.xml" % file_name,
                        "description": self.l10n_ec_xml_access_key,
                    }
                )
        return attachment


class L10nEcElectronicDocumentImportedLine(models.Model):
    _name = "l10n_ec.edi.imported.line"
    _description = "Imported Document's Detail"
    _rec_name = "product_name"

    document_id = fields.Many2one(
        "l10n_ec.edi.imported",
        "Document Imported",
        ondelete="cascade",
    )
    product_name = fields.Char()
    product_code = fields.Char()
    product_id = fields.Many2one(
        "product.product",
        "Product",
    )
    quantity = fields.Float(digits="Product Unit of Measure")
    price_unit = fields.Float(digits="Product Price")
    discount = fields.Float(digits="Discount")
    tax_ids = fields.Many2many(
        "account.tax",
        "l10n_ec_edi_imported_line_taxes_rel",
        "line_id",
        "tax_id",
        string="Taxes",
    )


class L10nEcElectronicDocumentImportedLogs(models.Model):
    _name = "l10n_ec.edi.imported.logs"
    _description = "Imported Document's Logs"
    _rec_name = "name"

    document_id = fields.Many2one(
        "l10n_ec.edi.imported",
        "Document Imported",
        ondelete="cascade",
    )
    name = fields.Char(string="Message")
