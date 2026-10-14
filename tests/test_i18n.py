import ast
import os
from pathlib import Path
from string import Formatter
import sys
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))

from i18n import HELPER_MESSAGES, SUPPORTED, TRANSLATIONS, detect_language, helper_message, tr


class LocaleTests(unittest.TestCase):
    def test_supported_regions_and_fallback(self):
        for locale, expected in [('it_IT.UTF-8', 'it'), ('fr_CA', 'fr'), ('de_DE@euro', 'de'),
                                 ('es-MX', 'es'), ('en_GB.UTF-8', 'en'), ('pt_BR', 'en'),
                                 ('C.UTF-8', 'en'), ('POSIX', 'en'), ('', 'en')]:
            with self.subTest(locale=locale):
                self.assertEqual(detect_language({'LANG': locale}), expected)

    def test_session_precedence(self):
        cases = [({'LANG': 'it_IT', 'LC_MESSAGES': 'fr_FR'}, 'fr'),
                 ({'LANG': 'it_IT', 'LC_MESSAGES': 'fr_FR', 'LC_ALL': 'de_DE'}, 'de'),
                 ({'LANG': 'it_IT', 'LANGUAGE': 'pt_BR:es_ES:en'}, 'es'),
                 ({'LANG': 'C', 'LANGUAGE': 'it'}, 'en')]
        for env, expected in cases:
            with self.subTest(env=env):
                self.assertEqual(detect_language(env), expected)

    def test_translation_follows_session(self):
        for language, expected in [('en', 'Protected'), ('it', 'Protetto'), ('fr', 'Protégé'),
                                   ('de', 'Geschützt'), ('es', 'Protegido')]:
            with patch.dict(os.environ, {'LANG': language}, clear=True):
                self.assertEqual(tr('Protected'), expected)
                self.assertEqual(tr('Unknown text'), 'Unknown text')

    def test_helper_message_never_formats(self):
        with patch.dict(os.environ, {'LANG': 'it_IT'}, clear=True):
            self.assertEqual(helper_message('Error'), 'Errore')
            self.assertEqual(helper_message('raw {braces}'), 'raw {braces}')

    def test_placeholder_names_do_not_clash(self):
        self.assertEqual(tr('{message} {text}', message='a', text='b'), 'a b')

    def test_catalogue_complete_with_same_placeholders(self):
        fields = lambda text: {field for _, field, _, _ in Formatter().parse(text) if field}
        for source, translations in TRANSLATIONS.items():
            self.assertEqual(len(translations), len(SUPPORTED) - 1, source)
            for translation in translations:
                self.assertTrue(translation.strip(), source)
                self.assertEqual(fields(source), fields(translation), source)

    def test_every_tr_literal_is_translated(self):
        for path in sorted(SOURCE.glob('*.py')):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'tr' and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    self.assertIn(node.args[0].value, TRANSLATIONS, f'{path.name}: {node.args[0].value!r}')

    def test_helper_messages_are_translated(self):
        for message in HELPER_MESSAGES:
            self.assertIn(message, TRANSLATIONS, message)


if __name__ == '__main__':
    unittest.main()
