from datetime import datetime
from xml.etree.ElementTree import tostring

from lxml import objectify

from odoo import api, models
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF

EDI_DF = "%d/%m/%Y"


class L10nEcXmlParse(models.AbstractModel):
    _name = "l10n_ec.xml.parser"
    _description = "Parser de Xml electronics"

    @api.model
    def _ln10_ec_get_xml_tag_supported(self):
        return ["RespuestaAutorizacion", "autorizacion"]

    @api.model
    def _l10n_ec_is_xml_valid(self, file_xml):
        # verificar si es un xml con estructura valida
        is_xml_valid = file_xml.tag in self._ln10_ec_get_xml_tag_supported()
        company = False
        if is_xml_valid:
            document_list = self._l10n_ec_get_document_info_from_xml(file_xml)
            for document_info in document_list:
                company = self._l10n_ec_get_company_for_xml(document_info)
                if company:
                    break
        return is_xml_valid and company

    @api.model
    def _l10n_ec_get_company_for_xml(self, document_info):
        Companies = self.env["res.company"]
        company = Companies.browse()
        company_vat = False
        if document_info.tag == "factura":
            company_vat = document_info.infoFactura.identificacionComprador.text
        elif document_info.tag == "notaCredito":
            company_vat = document_info.infoNotaCredito.identificacionComprador.text
        elif document_info.tag == "notaDebito":
            company_vat = document_info.infoNotaDebito.identificacionComprador.text
        elif document_info.tag == "comprobanteRetencion":
            company_vat = (
                document_info.infoCompRetencion.identificacionSujetoRetenido.text
            )
        if company_vat:
            if len(company_vat) == 10:
                company_vat += "001"
            company = Companies.search([("vat", "=", company_vat)], limit=1)
        return company

    @api.model
    def _l10n_ec_get_document_info_from_xml(self, file_xml):
        document_list = []
        # si el xml tiene un nodo comprobante, crear el objectify desde el text de dicho nodo
        # pero si no tiene ese nodo, toca buscar en el xml un atributo @id='comprobante'
        # asi que en ese caso se debe crear el objectify desde
        # el nodo padre que contenta dicho atributo
        comprobantes_node = file_xml.xpath("//comprobante")
        if comprobantes_node:
            for comprobante_node in comprobantes_node:
                document_info = objectify.fromstring(comprobante_node.text.encode())
                document_list.append(document_info)
        else:
            # soporte para documentos que no tengan el nodo comprobante(nuestro caso hasta V11)
            comprobantes_node = file_xml.xpath("//@id[.='comprobante']/..")
            for comprobante_node in comprobantes_node:
                document_info = objectify.fromstring(
                    tostring(comprobante_node).decode()
                )
                document_list.append(document_info)
        return document_list

    def l10n_ec_xml_get_latam_document_type(self, company, document_code):
        document_find = self.env["l10n_latam.document.type"].search(
            [("code", "=", document_code), ("country_id", "=", company.country_id.id)],
            limit=1,
        )
        return document_find

    def l10n_ec_check_edi_exist(self, electronicAthorization):
        """
        check document exist by electronic authorization
        """
        messages = []
        domain = [
            (
                "l10n_ec_electronic_authorization",
                "=",
                electronicAthorization,
            ),
        ]
        current_edi = self.search(domain, limit=1)
        if current_edi:
            messages.append(
                f"Ya existe un documento con el numero: "
                f"{current_edi.l10n_latam_document_number} para el proveedor: "
                f"{current_edi.partner_id.name}, no se creo otro documento"
            )
        return messages, current_edi

    def l10n_ec_xml_get_domain_for_doc_mod(
        self, partner_id, document_number, invoice_type, document_type
    ):
        """
        Devuelve los criterios para buscar si una factura existe o no(para documento modificado)
        """
        domain = [
            ("commercial_partner_id", "=", partner_id),
            (
                "l10n_latam_document_number",
                "=",
                document_number,
            ),
            ("move_type", "=", invoice_type),
        ]
        if document_type:
            domain.append(
                (
                    "l10n_latam_document_type_id",
                    "=",
                    document_type.id,
                ),
            )
        return domain

    def l10n_ec_xml_prepare_invoice_vals(
        self,
        company,
        document_info,
        latam_document_type,
        invoice_type,
        fechaEmision,
    ):
        info_tributaria = document_info.infoTributaria
        partner_find = self.l10n_ec_xml_find_create_partner(info_tributaria)
        issue_date = datetime.strptime(fechaEmision, EDI_DF)
        estab = info_tributaria.estab.text
        ptoEmi = info_tributaria.ptoEmi.text
        secuencial = info_tributaria.secuencial.text
        document_number = f"{estab}-{ptoEmi}-{secuencial}"

        invoice_vals = {
            "l10n_latam_document_number": document_number,
            "l10n_latam_document_type_id": latam_document_type.id,
            "l10n_ec_electronic_authorization": info_tributaria.claveAcceso.text,
            "l10n_ec_xml_access_key": info_tributaria.claveAcceso.text,
            "partner_id": partner_find.id,
            "company_id": company.id,
            "move_type": invoice_type,
            "invoice_date": issue_date,
        }
        return invoice_vals

    def l10n_ec_xml_prepare_credit_note_vals(
        self,
        company,
        document_info,
        latam_document_type,
        invoice_type,
        fechaEmision,
    ):
        invoice_model = self.env["account.move"]
        infoNotaCredito = document_info.infoNotaCredito
        codDocModificado = infoNotaCredito.codDocModificado.text
        numDocModificado = infoNotaCredito.numDocModificado.text
        fechaEmisionDocSustento = datetime.strptime(
            infoNotaCredito.fechaEmisionDocSustento.text,
            EDI_DF,
        )
        credit_note_vals = self.l10n_ec_xml_prepare_invoice_vals(
            company,
            document_info,
            latam_document_type,
            invoice_type,
            fechaEmision,
        )
        document_type_doc_mod = self.l10n_ec_xml_get_latam_document_type(
            company, codDocModificado
        )
        domain_invoice = self.l10n_ec_xml_get_domain_for_doc_mod(
            credit_note_vals["partner_id"],
            numDocModificado,
            "in_invoice",
            document_type_doc_mod,
        )
        current_invoice = invoice_model.search(domain_invoice, limit=1)
        if current_invoice:
            credit_note_vals["l10n_ec_original_invoice_id"] = current_invoice.id
        else:
            credit_note_vals["l10n_ec_legacy_document_number"] = numDocModificado
            credit_note_vals["l10n_ec_legacy_document_date"] = fechaEmisionDocSustento
            credit_note_vals["l10n_ec_legacy_document"] = True
        return credit_note_vals

    def l10n_ec_xml_prepare_debit_note_vals(
        self,
        company,
        document_info,
        latam_document_type,
        invoice_type,
        fechaEmision,
    ):
        invoice_model = self.env["account.move"]
        infoNotaDebito = document_info.infoNotaDebito
        codDocModificado = infoNotaDebito.codDocModificado.text
        numDocModificado = infoNotaDebito.numDocModificado.text
        fechaEmisionDocSustento = datetime.strptime(
            infoNotaDebito.fechaEmisionDocSustento.text,
            EDI_DF,
        )
        credit_note_vals = self.l10n_ec_xml_prepare_invoice_vals(
            company,
            document_info,
            latam_document_type,
            invoice_type,
            fechaEmision,
        )
        document_type_doc_mod = self.l10n_ec_xml_get_latam_document_type(
            company, codDocModificado
        )
        domain_invoice = self.l10n_ec_xml_get_domain_for_doc_mod(
            credit_note_vals["partner_id"],
            numDocModificado,
            "in_invoice",
            document_type_doc_mod,
        )
        current_invoice = invoice_model.search(domain_invoice, limit=1)
        if current_invoice:
            credit_note_vals["l10n_ec_original_invoice_id"] = current_invoice.id
        else:
            credit_note_vals["l10n_ec_legacy_document_number"] = numDocModificado
            credit_note_vals["l10n_ec_legacy_document_date"] = fechaEmisionDocSustento
            credit_note_vals["l10n_ec_legacy_document"] = True
        return credit_note_vals

    def l10n_ec_xml_find_create_partner(self, partner_node):
        Partners = self.env["res.partner"]
        partner_vals = self.l10n_ec_xml_prepare_partner_vals(partner_node)
        partner_find = Partners.search(
            self.l10n_ec_xml_get_domain_for_partner(partner_vals), limit=1
        )
        ctx = {
            "search_default_supplier": 1,
            "res_partner_search_mode": "supplier",
            "default_is_company": True,
            "default_supplier_rank": 1,
        }
        ctx.update(self.env.context.copy())
        # FIXME: al levantar asistente desde el menu de compras
        # se pasa por contexto default_move_type = 'in_invoice'
        # pero al crear un cliente, se interpreta como un valor por defecto
        # para el cliente lo cual provoca error xq in_invoice no es una
        # opcion del campo move_type en res.partner
        ctx.pop("default_move_type", False)
        if not partner_find:
            partner_find = Partners.with_context(**ctx).create(partner_vals)
        return partner_find

    def l10n_ec_xml_prepare_partner_vals(self, partner_node):
        partner_vals = {
            "name": partner_node.razonSocial.text,
            "l10n_latam_identification_type_id": self.env.ref("l10n_ec.ec_ruc").id,
            "vat": partner_node.ruc.text,
            "country_id": self.env.company.country_id.id,
        }
        if hasattr(partner_node, "nombreComercial"):
            partner_vals["l10n_ec_business_name"] = partner_node.nombreComercial.text
        if hasattr(partner_node, "dirMatriz"):
            partner_vals["street"] = partner_node.dirMatriz.text
        return partner_vals

    def l10n_ec_xml_get_domain_for_partner(self, partner_vals):
        domain = [("vat", "=", partner_vals["vat"]), ("parent_id", "=", False)]
        return domain

    def l10n_ec_xml_find_create_product(
        self, detail_xml, supplier_taxes, partner_id, force_create_product=False
    ):
        message_product_list = []
        Products = self.env["product.product"]
        SupplierInfo = self.env["product.supplierinfo"]
        product_vals = self.l10n_ec_xml_extract_product_values(
            detail_xml, supplier_taxes
        )
        product_find = Products.search(
            self.l10n_ec_xml_get_domain_for_product(product_vals), limit=1
        )
        ctx = self.env.context.copy()
        # FIXME: al levantar asistente desde el menu de compras
        # se pasa por contexto default_move_type = 'in_invoice'
        # pero al crear un producto, se interpreta como un valor por defecto
        # para el producto lo cual provoca error xq in_invoice no es una
        # opción del campo move_type en product.product
        ctx.pop("default_move_type", False)
        if not product_find:
            product_info_domain = [
                ("name", "=", partner_id),
            ]
            if product_vals.get("default_code"):
                product_info_domain.append(
                    ("product_code", "=", product_vals["default_code"])
                )
            else:
                product_info_domain.append(("product_name", "=", product_vals["name"]))
            product_supplier_info = SupplierInfo.search(product_info_domain, limit=1)
            if product_supplier_info:
                if product_supplier_info.product_id:
                    product_find = product_supplier_info.product_id
                elif product_supplier_info.product_tmpl_id.product_variant_id:
                    product_find = (
                        product_supplier_info.product_tmpl_id.product_variant_id
                    )
            if not product_find:
                # cuando no se debe crear el producto, agregar log
                if not force_create_product:
                    message_product_list.append(
                        "No se encuentra un producto con codigo principal: %s, "
                        "nombre: %s, "
                        "por favor verifique o cree el producto de ser necesario"
                        % (product_vals.get("default_code") or "", product_vals["name"])
                    )
                else:
                    product_find = Products.with_context(**ctx).create(product_vals)
                    if not product_supplier_info:
                        SupplierInfo.create(
                            {
                                "name": partner_id,
                                "product_code": product_vals.get("default_code") or "",
                                "product_name": product_vals.get("name"),
                                "product_tmpl_id": product_find.product_tmpl_id.id,
                            }
                        )
        return product_find, message_product_list

    def l10n_ec_xml_extract_product_values(self, detail_xml, taxes):
        product_vals = {
            "type": "service",
            "sale_ok": False,
            "purchase_ok": True,
        }
        if hasattr(detail_xml, "descripcion"):
            product_vals["name"] = detail_xml.descripcion.text
        elif hasattr(detail_xml, "razon"):
            product_vals["name"] = detail_xml.razon.text
        if hasattr(detail_xml, "precioUnitario"):
            product_vals["standard_price"] = float(detail_xml.precioUnitario.text)
        elif hasattr(detail_xml, "valor"):
            product_vals["standard_price"] = float(detail_xml.valor.text)
        if hasattr(detail_xml, "codigoPrincipal"):
            product_vals["default_code"] = detail_xml.codigoPrincipal.text
        elif hasattr(detail_xml, "codigoAuxiliar"):
            product_vals["default_code"] = detail_xml.codigoAuxiliar.text
        # cuando el producto no tenia codigo se envia N A
        # descartar esos codigos para buscar por el nombre del producto mejor
        if product_vals.get("default_code", "") == "N A":
            product_vals["default_code"] = ""
        if taxes:
            product_vals["supplier_taxes_id"] = [(6, 0, taxes.ids)]
        return product_vals

    def l10n_ec_xml_get_domain_for_product(self, product_vals):
        domain = []
        if product_vals.get("default_code"):
            domain.append(("default_code", "=", product_vals["default_code"]))
        else:
            domain.append(("name", "=", product_vals["name"]))
        return domain

    def l10n_ec_xml_get_domain_for_tax(self, company, tax_code, codigoPorcentaje):
        domain = [
            ("company_id", "=", company.id),
            ("type_tax_use", "=", "purchase"),
            (
                "tax_group_id.l10n_ec_xml_fe_code",
                "=",
                tax_code,
            ),  # filtrar si es IVA, Renta, ICE, IRBPNR
            (
                "l10n_ec_xml_fe_code",
                "=",
                codigoPorcentaje,
            ),  # filtrar si es IVA 12, IVA 0, etc
        ]
        return domain

    def l10n_ec_xml_find_taxes(self, company, tax_xml_node):
        TaxModel = self.env["account.tax"]
        taxes = TaxModel.browse()
        message_list = []
        for tax_xml in tax_xml_node.impuestos.impuesto:
            tax_code = tax_xml.codigo.text
            codigoPorcentaje = tax_xml.codigoPorcentaje.text
            domain = self.l10n_ec_xml_get_domain_for_tax(
                company, tax_code, codigoPorcentaje
            )
            tax_find = TaxModel.search(domain, limit=1, order="sequence")
            if not tax_find:
                message_list.append(
                    f"No se encontro un impuesto tipo: {tax_code} "
                    f"que pertenezca al grupo con codigo: {codigoPorcentaje}"
                )
            taxes |= tax_find
        return taxes, message_list

    def l10n_ec_xml_prepare_invoice_line_vals(
        self, detail_xml, product, supplier_taxes
    ):
        name = detail_xml.descripcion.text
        ail_vals = {
            "name": product.name or name,
            "product_id": product.id,
            "product_uom_id": product.uom_id.id,
            "quantity": float(detail_xml.cantidad.text),
            # FIXME: el descuento es en monto no en porcentaje
            "discount": float(detail_xml.descuento.text),
            "price_unit": float(detail_xml.precioUnitario.text),
            "move_id": self.id,
        }
        if supplier_taxes:
            ail_vals["tax_ids"] = [(6, 0, supplier_taxes.ids)]
        return ail_vals

    def l10n_ec_xml_prepare_debit_note_line_vals(
        self, detail_xml, product, supplier_taxes
    ):
        name = detail_xml.razon.text
        ail_vals = {
            "name": product.name or name,
            "product_id": product.id,
            "product_uom_id": product.uom_id.id,
            "quantity": float(detail_xml.cantidad.text),
            "price_unit": float(detail_xml.valor.text),
            "move_id": self.id,
        }
        if supplier_taxes:
            ail_vals["tax_ids"] = [(6, 0, supplier_taxes.ids)]
        return ail_vals

    @api.model
    def _l10n_ec_create_file_authorized(
        self, xml_file, authorization_number, authorization_date, environment
    ):
        ViewModel = self.env["ir.ui.view"].sudo()
        xml_values = {
            "xml_file": xml_file,
            "authorization_number": authorization_number,
            "authorization_date": authorization_date.strftime(DTF),
            "environment": "PRODUCCION" if environment == "production" else "PRUEBAS",
        }
        xml_authorized = ViewModel._render_template(
            "l10n_ec_import_edi.ec_edi_authorization", xml_values
        )
        return xml_authorized
