import json
import unittest

from official_document import extract_official_document


class OfficialDocumentTests(unittest.TestCase):
    def test_rada_extracts_statute_not_revision_menu_or_browser_warning(self):
        url = 'https://zakon.rada.gov.ua/go/1023-12'
        law = 'Стаття 1. Права споживачів. ' * 80
        def page(date):
            return f'<main>Browser warning {date}<div id="article" class="valid">{law}</div><aside>Share {date}</aside></main>'
        self.assertEqual(extract_official_document(page('today'),url), law.strip())
        self.assertEqual(extract_official_document(page('today'),url), extract_official_document(page('tomorrow'),url))
        self.assertNotEqual(extract_official_document(page('today'),url), extract_official_document(page('today').replace('Права','Нові права'),url))

    def test_rada_large_comparison_shell_is_not_statute(self):
        html = '<main>' + 'Document valid revision export ' * 1000 + '</main>'
        with self.assertRaisesRegex(ValueError, 'shell'):
            extract_official_document(html, 'https://zakon.rada.gov.ua/laws/show/en/1023-12/comp20121119')
        with self.assertRaises(ValueError):
            extract_official_document('<div id="article">Metadata </div>'*300, 'https://zakon.rada.gov.ua/laws/show/1023-12')

    def test_rada_shell_not_written_as_trusted_evidence(self):
        import os, tempfile
        from pathlib import Path
        from unittest.mock import Mock, patch
        from knowledge_update import _fingerprint
        html = '<main>Export revision metadata </main>' * 1000
        response = Mock(headers={'content-type':'text/html'}, content=html.encode(), text=html)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, POLICY_AMADEUS_EVIDENCE_DIR=directory), patch('requests.get',return_value=response):
            with self.assertRaises(ValueError):
                _fingerprint('https://zakon.rada.gov.ua/laws/show/1023-12')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_moldova_view_count_is_not_document_text(self):
        url = 'https://consumator.gov.md/en/node/575'
        def page(views, days):
            return f'<article data-history-node-id="575"><h1>Safe shopping</h1><span class="post-views">{views}</span><div class="field--name-body">Withdrawal: {days} days.</div></article>'
        self.assertEqual(extract_official_document(page(44,14),url),extract_official_document(page(48,14),url))
        self.assertNotEqual(extract_official_document(page(44,14),url),extract_official_document(page(48,30),url))

    def test_malta_pdf_endpoint_rejects_large_navigation_shell(self):
        from unittest.mock import Mock, patch
        from knowledge_update import _fingerprint
        response = Mock()
        response.headers = {'content-type':'text/html'}
        response.content = b'<main>Navigation and latest laws </main>'*1000
        response.text = response.content.decode()
        with patch('requests.get',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'PDF'):
                _fingerprint('https://legislation.mt/eli/cap/378/eng/pdf')

    def test_ris_navigation_date_changes_but_law_changes_are_detected(self):
        url = 'https://www.ris.bka.gv.at/eli/bgbl/i/2014/33/P0/NOR40162350'
        def page(day, days):
            return f'<main>§ 1 am {day}<div class="documentContent"><h2>Text</h2>Rücktritt {days} Tage</div></main>'
        self.assertEqual(extract_official_document(page('29.09.2026', 14), url), extract_official_document(page('30.09.2026', 14), url))
        self.assertNotEqual(extract_official_document(page('30.09.2026', 14), url), extract_official_document(page('30.09.2026', 30), url))

    def test_guichet_live_office_hours_do_not_mask_policy_changes(self):
        url = 'https://guichet.public.lu/fr/entreprises/commerce/pratiques-commerciales/vente/a-distance-b2c.html'
        def page(state, days):
            return f'<main>Délai: {days} jours<div class="cmp-hours"><details><summary>{state}</summary><div>Lundi 9h00</div></details></div>Remboursement</main>'
        self.assertEqual(extract_official_document(page('Ouvert', 14), url), extract_official_document(page('Fermé', 14), url))
        self.assertNotEqual(extract_official_document(page('Ouvert', 14), url), extract_official_document(page('Fermé', 30), url))

    def test_finlex_builds_and_chunk_boundaries_do_not_change_statute(self):
        url = 'https://www.finlex.fi/fi/lainsaadanto/1978/38'
        def page(key, build, days, split=False):
            section = ['$', 'section', None, {'lang': 'fi', 'className': build + '__akomaNtoso', 'children': '$L' + key}]
            paragraph = ['$', 'p', None, {'className': build, 'children': f'Peruutus {days} päivää. Voimaan 1.10.2026.'}]
            stream = '0:' + json.dumps(section, ensure_ascii=False) + '\n' + key + ':' + json.dumps(paragraph, ensure_ascii=False) + '\n'
            stream += 'ff:' + json.dumps(['$', 'aside', None, {'children': build + ' New unrelated laws'}]) + '\n'
            chunks = [stream[:35], stream[35:]] if split else [stream]
            return ''.join('<script>self.__next_f.push(' + json.dumps([1, chunk], ensure_ascii=False) + ')</script>' for chunk in chunks)
        self.assertEqual(extract_official_document(page('a', 'build1', 14), url), extract_official_document(page('b', 'build2', 14, True), url))
        self.assertNotEqual(extract_official_document(page('a', 'build1', 14), url), extract_official_document(page('b', 'build2', 30, True), url))

    def test_finlex_missing_statute_references_fail_instead_of_hashing_partial_text(self):
        section = ['$', 'section', None, {'lang': 'fi', 'className': 'akomaNtoso', 'children': '$Labc'}]
        html = '<script>self.__next_f.push(' + json.dumps([1, '0:' + json.dumps(section) + '\n']) + ')</script>'
        with self.assertRaises(ValueError):
            extract_official_document(html, 'https://www.finlex.fi/fi/lainsaadanto/1978/38')

    def test_large_etal_shell_is_not_a_law(self):
        html = '<div>' + 'Menu Search Document Type ' * 1000 + '</div><div id="doc-content-outline-root"></div>'
        with self.assertRaises(ValueError):
            extract_official_document(html, 'https://etalonline.by/document/?regnum=H11000262')


if __name__ == '__main__':
    unittest.main()
