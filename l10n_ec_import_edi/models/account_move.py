import logging

from lxml import etree

from odoo import _, api, models, tools

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = ["l10n_ec.xml.parser", "account.move"]
    _name = "account.move"

    @api.onchange("l10n_ec_electronic_authorization")
    def _onchange_l10n_ec_electronic_authorization(self):
        warning = {}
        messages = []
        if (
            self.l10n_ec_electronic_authorization
            and len(self.l10n_ec_electronic_authorization) == 49
            and self.is_purchase_document()
            and self.company_id.l10n_ec_check_data_document_automatic
        ):
            messages, current_invoice = self.l10n_ec_check_edi_exist(
                self.l10n_ec_electronic_authorization
            )
            if current_invoice:
                self.l10n_ec_electronic_authorization = ""
            else:
                xml_data = self.env["account.edi.format"]
                xml_authorized = ""
                client_ws = xml_data._l10n_ec_get_edi_ws_client(
                    "production", "authorization"
                )
                if not client_ws:
                    _logger.error(
                        "Cannot connect to SRI to download file with access key %s",
                        self.l10n_ec_electronic_authorization,
                    )
                    return
                try:
                    xml_authorized = self.env[
                        "l10n_ec.edi.imported"
                    ]._l10n_ec_download_file(
                        client_ws, self.l10n_ec_electronic_authorization
                    )
                except Exception as ex:
                    _logger.error(tools.ustr(ex))
                if not xml_authorized:
                    return
                invoice_xml = etree.fromstring(xml_authorized)
                document_list = self._l10n_ec_get_document_info_from_xml(invoice_xml)
                for document_info in document_list:
                    messages = self._l10n_ec_validate_edi(document_info)
        if messages:
            warning = {
                "title": _("Information for User"),
                "message": "\n".join(messages),
            }
        return {"warning": warning}

    def _l10n_ec_validate_edi(self, document_info):
        messages = []
        company = self._l10n_ec_get_company_for_xml(document_info)
        if not company:
            messages.append(_("Can't find company for current xml file, please review"))
            return messages
        elif company != self.company_id:
            messages.append(
                _(
                    "File does not belong to the current company, "
                    "please import file into company: %s"
                )
                % (company.name)
            )
            return messages
        if document_info.tag == "factura":
            if self.move_type != "in_invoice":
                messages.append(
                    _(
                        "Electronic Authorization is for Invoice, "
                        "but current document is not same type, "
                        "please create document on appropriated menu"
                    )
                )
                return messages
            messages, new_document = self.with_context(
                allowed_company_ids=company.ids
            )._l10n_ec_create_invoice_from_xml(document_info)
        elif document_info.tag == "notaCredito":
            if self.move_type != "in_refund":
                messages.append(
                    _(
                        "Electronic Authorization is for Credit Note, "
                        "but current document is not same type, "
                        "please create document on appropriated menu"
                    )
                )
                return messages
            messages, new_document = self.with_context(
                allowed_company_ids=company.ids, internal_type="credit_note"
            )._l10n_ec_create_credit_note_from_xml(document_info)
        elif document_info.tag == "notaDebito":
            if self.move_type != "in_invoice":
                messages.append(
                    _(
                        "Electronic Authorization is for Debit Note, "
                        "but current document is not same type, "
                        "please create document on appropriated menu"
                    )
                )
                return messages
            messages, new_document = self.with_context(
                allowed_company_ids=company.ids, internal_type="debit_note"
            )._l10n_ec_create_debit_note_from_xml(document_info)
        return messages

    def _l10n_ec_create_invoice_from_xml(self, document_info):
        InvoiceLineModel = self.env["account.move.line"]
        is_onchange_invoice = isinstance(self.id, models.NewId)
        company = self.env.company
        create_product = company.l10n_ec_import_create_product
        invoice_type = "in_invoice"
        document_code = document_info.infoTributaria.codDoc.text
        fechaEmision = document_info.infoFactura.fechaEmision.text
        messages = []
        latam_document_type = self.l10n_latam_document_type_id
        if not latam_document_type:
            latam_document_type = self.l10n_ec_xml_get_latam_document_type(
                company, document_code
            )
        if not latam_document_type:
            messages.append(
                _("No valid document type found with code: %s") % document_code
            )
        vals_invoice = self.l10n_ec_xml_prepare_invoice_vals(
            company,
            document_info,
            latam_document_type,
            invoice_type,
            fechaEmision,
        )
        messages, current_invoice = self.l10n_ec_check_edi_exist(vals_invoice)
        if current_invoice:
            self.l10n_ec_electronic_authorization = ""
            return messages, current_invoice
        if is_onchange_invoice:
            self.invoice_line_ids = [(5, 0)]
            self.line_ids = [(5, 0)]
            self.update(vals_invoice)
            # Forzar la asignación del self.l10n_latam_document_number
            # porque es tipo Calculable y no se almacena
            self.l10n_latam_document_number = vals_invoice.get(
                "l10n_latam_document_number"
            )
        else:
            self.write(vals_invoice)
        # provocar el onchange del partner
        self._onchange_partner_id()
        invoice_line_vals = []
        for detail_xml in document_info.detalles.detalle:
            supplier_taxes, message_tax_list = self.l10n_ec_xml_find_taxes(
                company, detail_xml
            )
            messages.extend(message_tax_list)
            product, message_product_list = self.l10n_ec_xml_find_create_product(
                detail_xml,
                supplier_taxes,
                vals_invoice["partner_id"],
                force_create_product=create_product,
            )
            messages.extend(message_product_list)
            vals_line = self.l10n_ec_xml_prepare_invoice_line_vals(
                detail_xml, product, supplier_taxes
            )
            invoice_line = InvoiceLineModel.new(vals_line)
            invoice_line._onchange_product_id()
            invoice_line.price_unit = vals_line["price_unit"]
            invoice_line.quantity = vals_line["quantity"]
            invoice_line.currency_id = self.currency_id
            if vals_line.get("discount"):
                invoice_line.discount = self._l10n_ec_get_discount(vals_line)
            if supplier_taxes:
                invoice_line.tax_ids |= supplier_taxes
            if not invoice_line.account_id:
                invoice_line._get_computed_account()
            if not invoice_line.account_id:
                invoice_line.account_id = self.journal_id.default_account_id
            if is_onchange_invoice:
                self.invoice_line_ids |= invoice_line
            else:
                vals_line_create = invoice_line._convert_to_write(
                    {name: invoice_line[name] for name in invoice_line._cache}
                )
                invoice_line_vals.append((0, 0, vals_line_create))
        if is_onchange_invoice:
            self.invoice_line_ids._onchange_price_subtotal()
            self._recompute_dynamic_lines(recompute_all_taxes=True)
        else:
            amount_total_imported = float(document_info.infoFactura.importeTotal.text)
            self.write({"invoice_line_ids": invoice_line_vals})
            decimal_places = self.currency_id.decimal_places
            if (
                tools.float_compare(
                    self.amount_total,
                    amount_total_imported,
                    precision_digits=decimal_places,
                )
                != 0
            ):
                messages.append(
                    f"Los totales no coinciden, Total sistema: "
                    f"{tools.float_repr(self.amount_total, decimal_places)}, "
                    f"total importado: "
                    f"{tools.float_repr(amount_total_imported, decimal_places)}. "
                    f"Documento: {vals_invoice['l10n_latam_document_number']}"
                )
        return messages, self

    @api.model
    def _l10n_ec_create_credit_note_from_xml(self, document_info):
        InvoiceLineModel = self.env["account.move.line"]
        is_onchange_invoice = isinstance(self.id, models.NewId)
        company = self.env.company
        create_product = company.l10n_ec_import_create_product
        invoice_type = "in_refund"
        document_code = document_info.infoTributaria.codDoc.text
        fechaEmision = document_info.infoNotaCredito.fechaEmision.text
        messages = []
        latam_document_type = self.l10n_latam_document_type_id
        if not latam_document_type:
            latam_document_type = self.l10n_ec_xml_get_latam_document_type(
                company, document_code
            )
        if not latam_document_type:
            messages.append(
                _("No valid document type found with code: %s") % document_code
            )
        vals_invoice = self.l10n_ec_xml_prepare_credit_note_vals(
            company,
            document_info,
            latam_document_type,
            invoice_type,
            fechaEmision,
        )
        messages, current_invoice = self.l10n_ec_check_edi_exist(vals_invoice)
        if current_invoice:
            self.l10n_ec_electronic_authorization = ""
            return messages, current_invoice
        if is_onchange_invoice:
            self.invoice_line_ids = [(5, 0)]
            self.line_ids = [(5, 0)]
            self.update(vals_invoice)
            # Forzar la asignación del self.l10n_latam_document_number
            # porque es tipo Calculable y no se almacena
            self.l10n_latam_document_number = vals_invoice.get(
                "l10n_latam_document_number"
            )
        else:
            self.write(vals_invoice)
        # provocar el onchange del partner
        self._onchange_partner_id()
        invoice_line_vals = []
        for detail_xml in document_info.detalles.detalle:
            supplier_taxes, message_tax_list = self.l10n_ec_xml_find_taxes(
                company, detail_xml
            )
            messages.extend(message_tax_list)
            product, message_product_list = self.l10n_ec_xml_find_create_product(
                detail_xml,
                supplier_taxes,
                vals_invoice["partner_id"],
                force_create_product=create_product,
            )
            messages.extend(message_product_list)
            vals_line = self.l10n_ec_xml_prepare_invoice_line_vals(
                detail_xml, product, supplier_taxes
            )
            invoice_line = InvoiceLineModel.new(vals_line)
            invoice_line._onchange_product_id()
            invoice_line.price_unit = vals_line["price_unit"]
            invoice_line.quantity = vals_line["quantity"]
            if vals_line.get("discount"):
                invoice_line.discount = self._l10n_ec_get_discount(vals_line)
            if supplier_taxes:
                invoice_line.tax_ids |= supplier_taxes
            if not invoice_line.account_id:
                invoice_line._get_computed_account()
            if not invoice_line.account_id:
                invoice_line.account_id = self.journal_id.default_debit_account_id
            if is_onchange_invoice:
                self.invoice_line_ids |= invoice_line
            else:
                vals_line_create = invoice_line._convert_to_write(
                    {name: invoice_line[name] for name in invoice_line._cache}
                )
                invoice_line_vals.append((0, 0, vals_line_create))
        if is_onchange_invoice:
            self.invoice_line_ids._onchange_price_subtotal()
            self._recompute_dynamic_lines(recompute_all_taxes=True)
        else:
            amount_total_imported = float(
                document_info.infoNotaCredito.valorModificacion.text
            )
            self.write({"invoice_line_ids": invoice_line_vals})
            decimal_places = self.currency_id.decimal_places
            if (
                tools.float_compare(
                    self.amount_total,
                    amount_total_imported,
                    precision_digits=decimal_places,
                )
                != 0
            ):
                messages.append(
                    f"Los totales no coinciden, Total sistema: "
                    f"{tools.float_repr(self.amount_total, decimal_places)}, "
                    f"total importado: "
                    f"{tools.float_repr(amount_total_imported, decimal_places)}. "
                    f"Documento: {vals_invoice['l10n_latam_document_number']}"
                )
        return messages, self

    @api.model
    def _l10n_ec_create_debit_note_from_xml(self, document_info):
        InvoiceLineModel = self.env["account.move.line"]
        is_onchange_invoice = isinstance(self.id, models.NewId)
        company = self.env.company
        create_product = company.l10n_ec_import_create_product
        invoice_type = "in_invoice"
        document_code = document_info.infoTributaria.codDoc.text
        fechaEmision = document_info.infoNotaDebito.fechaEmision.text
        messages = []
        latam_document_type = self.l10n_latam_document_type_id
        if not latam_document_type:
            latam_document_type = self.l10n_ec_xml_get_latam_document_type(
                company, document_code
            )
        if not latam_document_type:
            messages.append(
                _("No valid document type found with code: %s") % document_code
            )
        vals_invoice = self.l10n_ec_xml_prepare_debit_note_vals(
            company,
            document_info,
            latam_document_type,
            invoice_type,
            fechaEmision,
        )
        messages, current_invoice = self.l10n_ec_check_edi_exist(vals_invoice)
        if current_invoice:
            self.l10n_ec_electronic_authorization = ""
            return messages, current_invoice
        if is_onchange_invoice:
            self.invoice_line_ids = [(5, 0)]
            self.line_ids = [(5, 0)]
            self.update(vals_invoice)
            # Forzar la asignación del self.l10n_latam_document_number
            # porque es tipo Calculable y no se almacena
            self.l10n_latam_document_number = vals_invoice.get(
                "l10n_latam_document_number"
            )
        else:
            self.write(vals_invoice)
        # provocar el onchange del partner
        self._onchange_partner_id()
        invoice_line_vals = []
        for detail_xml in document_info.motivos.motivo:
            # tomar los impuestos del nodo principal y no del motivo
            supplier_taxes, message_tax_list = self.l10n_ec_xml_find_taxes(
                company, document_info.infoNotaDebito
            )
            messages.extend(message_tax_list)
            product, message_product_list = self.l10n_ec_xml_find_create_product(
                detail_xml,
                supplier_taxes,
                vals_invoice["partner_id"],
                force_create_product=create_product,
            )
            messages.extend(message_product_list)
            vals_line = self.l10n_ec_xml_prepare_debit_note_line_vals(
                detail_xml, product, supplier_taxes
            )
            invoice_line = InvoiceLineModel.new(vals_line)
            invoice_line._onchange_product_id()
            invoice_line.price_unit = vals_line["price_unit"]
            invoice_line.quantity = vals_line["quantity"]
            if vals_line.get("discount"):
                invoice_line.discount = self._l10n_ec_get_discount(vals_line)
            if supplier_taxes:
                invoice_line.tax_ids |= supplier_taxes
            if not invoice_line.account_id:
                invoice_line._get_computed_account()
            if not invoice_line.account_id:
                invoice_line.account_id = self.journal_id.default_debit_account_id
            if is_onchange_invoice:
                self.invoice_line_ids |= invoice_line
            else:
                vals_line_create = invoice_line._convert_to_write(
                    {name: invoice_line[name] for name in invoice_line._cache}
                )
                invoice_line_vals.append((0, 0, vals_line_create))
        if is_onchange_invoice:
            self.invoice_line_ids._onchange_price_subtotal()
            self._recompute_dynamic_lines(recompute_all_taxes=True)
        else:
            amount_total_imported = float(document_info.infoNotaDebito.valorTotal.text)
            self.write({"invoice_line_ids": invoice_line_vals})
            decimal_places = self.currency_id.decimal_places
            if (
                tools.float_compare(
                    self.amount_total,
                    amount_total_imported,
                    precision_digits=decimal_places,
                )
                != 0
            ):
                messages.append(
                    f"Los totales no coinciden, Total sistema: "
                    f"{tools.float_repr(self.amount_total, decimal_places)}, "
                    f"total importado: "
                    f"{tools.float_repr(amount_total_imported, decimal_places)}. "
                    f"Documento: {vals_invoice['l10n_latam_document_number']}"
                )
        return messages, self

    def _l10n_ec_get_discount(self, vals_line):
        # Convertir descuento como monto a descuento como porcentaje
        discount_mount = vals_line["discount"]
        price_unit = vals_line["price_unit"]
        quantity = vals_line["quantity"]
        # evitar que exista división por cero
        price_unit = price_unit if price_unit != 0 else 1
        quantity = quantity if quantity != 0 else 1
        # Convierte de monto a porcentaje
        discount = (discount_mount / price_unit) * 100 / quantity

        return discount
