import base64
import logging

from zeep import Client
from zeep.transports import Transport

from odoo import _, api, models, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TEST_URL = {
    "reception": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl",  # noqa: B950
    "authorization": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl",  # noqa: B950
}

PRODUCTION_URL = {
    "reception": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl",  # noqa: B950
    "authorization": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl",  # noqa: B950
}


class L10necUtils(models.AbstractModel):
    _name = "l10n_ec.utils"
    _description = "Utilities miscellaneous"

    @api.model
    def read_file(self, file, options=None):
        """
        read file from base64
        :options: data for read file, keys(encoding,separator_line,separator_field)
        :returns: [[str,str,...], [str,str,...],....]
        """
        if options is None:
            options = {}
        lines_read = []
        errors = []
        separator_line = str(options.get("separator_line", "\n"))
        separator_field = str(options.get("field_delimiter", ","))
        encoding = str(options.get("encoding", "utf-8"))
        try:
            lines_file = base64.decodebytes(file).decode(encoding).split(separator_line)
            for row in lines_file:
                line = row.split(separator_field)
                lines_read.append(line)
        except UnicodeDecodeError as er:
            raise UserError(
                _(
                    "Error to read file, please choose encoding, "
                    "Field delimiter and text delimiter right. "
                    "\n More info %s"
                )
                % tools.ustr(er)
            ) from None
        except Exception as e:
            raise UserError(
                _("Error to read file. \nMore info %s") % tools.ustr(e)
            ) from None
        return lines_read, errors

    @api.model
    def _l10n_ec_get_edi_wsclient(self, environment, url_type):
        """
        :param environment: tipo de ambiente, puede ser:
            test: Pruebas
            production: Produccion
        :param url_type: el tipo de url a solicitar, puede ser:
            reception: url para recepcion de documentos
            authorization: url para autorizacion de documentos
        :return:
        """
        # Debido a que el servidor esta rechazando las conexiones contantemente,
        # es necesario que se cree una sola instancia
        # Para conexion y asi evitar un reinicio constante de la comunicacion
        wsClient = None
        if environment == "test":
            ws_url = TEST_URL.get(url_type)
        elif environment == "production":
            ws_url = PRODUCTION_URL.get(url_type)
        try:
            transport = Transport(timeout=30)
            wsClient = Client(ws_url, transport=transport)
        except Exception as e:
            _logger.warning(
                "Error in Connection with web services of SRI: %s. Error: %s",
                ws_url,
                tools.ustr(e),
            )
        return wsClient
