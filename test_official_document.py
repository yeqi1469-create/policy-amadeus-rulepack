import json
import unittest

from official_document import extract_official_document


class OfficialDocumentTests(unittest.TestCase):
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
