# -*- coding: utf-8 -*-
import base64
import logging
import polib
from deep_translator import GoogleTranslator
from odoo import api, fields, models, _


_logger = logging.getLogger(__name__)


class BaseLanguageExport(models.TransientModel):
    _inherit = 'base.language.export'

    def _get_languages(self):
        return [(lang, lang.capitalize()) for lang in GoogleTranslator().get_supported_languages()]

    def _get_default_source_lang(self):
        default_lang = False
        if 'english' in GoogleTranslator().get_supported_languages():
            default_lang = 'english'
        return default_lang

    automatic_translate = fields.Boolean(
        string='Automatic Translate',
    )
    source_lang = fields.Selection(
        selection='_get_languages',
        string='Source Language',
        default=_get_default_source_lang
    )
    target_lang = fields.Selection(
        selection='_get_languages',
        string='Target Language',
    )

    @api.onchange('automatic_translate')
    def _onchange_automatic_translate(self):
        if self.automatic_translate:
            self.lang = '__new__'

    def act_getfile(self):
        res = super(BaseLanguageExport, self).act_getfile()
        if self.automatic_translate:
            file_po = polib.pofile(base64.decodebytes(self.data).decode('utf-8'))
            for entry in file_po:
                if not entry.msgid:
                    continue
                try:
                    translation = GoogleTranslator(
                        source=self.source_lang,
                        target=self.target_lang
                    ).translate(entry.msgid)

                    entry.msgstr = translation
                    _logger.info("Translate: %s -> %s" % (entry.msgid, entry.msgstr))
                except Exception as e:
                    msg = "%s %s %s %s" % (
                        _("Translation error. The key could not be translated. Key:"),
                        entry.msgid, _("Error:"), e
                    )
                    _logger.warning(msg)

            self.name = self.name.replace('.pot', f'_{self.target_lang}.po')
            self.data = base64.b64encode(str(file_po).encode('utf-8'))

        return res
