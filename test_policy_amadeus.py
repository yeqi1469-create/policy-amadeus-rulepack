from __future__ import annotations
import json
import base64
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from knowledge_update import MIN_VISIBLE_SOURCE_CHARS, _effective_eu_versions, _fingerprint_source, _normalized_legal_text, _scheduled_legal_versions, run_startup_check
from policy_generator import extract_license_fields, generate_translated_bundle
from policy_studio import VERIFIED_MARKETS, compact_market_scope, group_market_values
from policy_validator import PolicyValidationError, missing_policy_concepts, validate_localized_output
from rulepack_manager import RulepackError, load_rulepack, update_from_manifest, validate_rulepack, version_key
from app_updater import _signed_fields, _verify_manifest
LICENCE_DIR = Path('synthetic-test-fixture')

class RulepackTests(unittest.TestCase):

    def test_newer_bundled_rulepack_wins_over_stale_download(self) -> None:
        from rulepack_manager import active_rulepack_path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloaded = root / 'legal_rulepack.json'
            bundled = root / 'bundled.json'
            downloaded.write_text(json.dumps({'rulepack_version': '2026.08.27-1'}), encoding='utf-8')
            bundled.write_text(json.dumps({'rulepack_version': '2026.09.29-1'}), encoding='utf-8')
            with patch('rulepack_manager._data_dir', return_value=root), patch('rulepack_manager._bundled_path', return_value=bundled):
                self.assertEqual(active_rulepack_path(), bundled)

    def test_app_update_manifest_requires_trusted_signature(self) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        private = Ed25519PrivateKey.generate()
        public = base64.b64encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        manifest = {'version': '2026.09.23-2', 'download_url': 'https://example.com/PolicyAmadeus.exe', 'sha256': 'a' * 64}
        manifest['signature'] = base64.b64encode(private.sign(_signed_fields(manifest['version'], manifest['download_url'], manifest['sha256']))).decode()
        self.assertEqual(_verify_manifest(manifest, public)[0], manifest['version'])
        manifest['download_url'] = 'https://example.com/tampered.exe'
        with self.assertRaisesRegex(RuntimeError, '数字签名'):
            _verify_manifest(manifest, public)

    def test_only_effective_eu_consolidations_are_selected(self) -> None:
        from datetime import date
        before = _effective_eu_versions(date(2026, 9, 4))
        after = _effective_eu_versions(date(2026, 9, 27))
        self.assertEqual(before['EU Consumer Rights Directive'], '2022-05-28')
        self.assertEqual(after['EU Consumer Rights Directive'], '2026-09-27')
        self.assertEqual(before['EU Sale of Goods Directive'], '2026-07-31')

    def test_future_national_change_is_recorded_but_not_active_early(self) -> None:
        from datetime import date
        pack = load_rulepack()
        self.assertNotIn('Austrian FAGG electronic withdrawal function', _scheduled_legal_versions(pack, date(2026, 9, 29)))
        self.assertEqual(_scheduled_legal_versions(pack, date(2026, 10, 1))['Austrian FAGG electronic withdrawal function'], 'FAGG section 13a, BGBl. I Nr. 59/2026 (effective 2026-10-01)')

    def test_every_selectable_market_has_an_official_source(self) -> None:
        from knowledge_update import COUNTRY_OFFICIAL_SOURCES
        from policy_studio import EUROPE_MARKETS
        self.assertEqual(set(EUROPE_MARKETS), set(COUNTRY_OFFICIAL_SOURCES))
        for country, urls in COUNTRY_OFFICIAL_SOURCES.items():
            with self.subTest(country=country):
                self.assertTrue(urls)
                self.assertTrue(all((url.startswith('https://') for url in urls)))

    def test_source_fingerprint_rejects_empty_legal_page_threshold(self) -> None:
        self.assertGreaterEqual(MIN_VISIBLE_SOURCE_CHARS, 1000)

    def test_source_fingerprint_ignores_navigation_and_footer_changes(self) -> None:
        body = 'Mandatory consumer rights ' * 100
        first = f'<header>Menu A</header><main><article>{body}</article></main><footer>Today</footer>'
        second = f'<header>Menu B</header><main><article>{body}</article></main><footer>Tomorrow</footer>'
        self.assertEqual(_normalized_legal_text(first), _normalized_legal_text(second))

    def test_source_normalizer_does_not_consume_body_after_nested_script(self) -> None:
        body = 'Mandatory consumer rights and remedies ' * 100
        html = f'<header><script>var menu = 1;</script><nav>Menu</nav></header><div>{body}</div><footer><form>Subscribe</form></footer>'
        normalized = _normalized_legal_text(html)
        self.assertGreaterEqual(len(normalized), MIN_VISIBLE_SOURCE_CHARS)
        self.assertIn('Mandatory consumer rights', normalized)

    def test_source_normalizer_keeps_law_inside_large_portal_form(self) -> None:
        body = 'Mandatory consumer rights and remedies ' * 3000
        html = f'<header>Menu</header><form method="POST">{body}</form><footer>Footer</footer>'
        normalized = _normalized_legal_text(html)
        self.assertGreaterEqual(len(normalized), MIN_VISIBLE_SOURCE_CHARS)
        self.assertIn('Mandatory consumer rights', normalized)

    def test_source_normalizer_extracts_content_div_inside_portal_form(self) -> None:
        body = 'Mandatory consumer rights and remedies ' * 100
        html = f'<form><div id="container"><div id="content"><div class="main">{body}</div></div></div></form></body>'
        normalized = _normalized_legal_text(html)
        self.assertGreaterEqual(len(normalized), MIN_VISIBLE_SOURCE_CHARS)
        self.assertIn('Mandatory consumer rights', normalized)

    def test_turkish_source_ignores_volatile_main_navigation(self) -> None:
        article = 'Mesafeli sözleşmeler tüketici hakları ' * 100
        first = f'<main><nav>Minister A</nav><div class="__zone">{article}</div></section><aside>Card A</aside></main>'
        second = f'<main><nav>Minister B</nav><div class="__zone">{article}</div></section><aside>Card B</aside></main>'
        self.assertEqual(_normalized_legal_text(first), _normalized_legal_text(second))

    def test_consolidated_portal_view_dates_do_not_trigger_changes(self) -> None:
        body = 'Consumer withdrawal rights and remedies ' * 100
        nl_a = f'<main>{body} Geraadpleegd op 19-09-2026. Geldend van 16-07-2026 t/m heden.</main>'
        nl_b = f'<main>{body} Geraadpleegd op 21-09-2026. Geldend van 16-07-2026 t/m heden.</main>'
        self.assertEqual(_normalized_legal_text(nl_a), _normalized_legal_text(nl_b))
        at_a = f'<main>RIS - Fassung vom 19.09.2026 {body}</main>'
        at_b = f'<main>RIS - Fassung vom 21.09.2026 {body}</main>'
        self.assertEqual(_normalized_legal_text(at_a), _normalized_legal_text(at_b))

    def test_finlex_asset_query_metadata_does_not_trigger_changes(self) -> None:
        body = 'Kuluttajansuoja ja kuluttajan oikeudet ' * 100
        first = f'<main>{body} href="/api/media/statute.pdf?revision=28\\u0026timestamp=2026-09-14T03%3A45%3A22.441Z"</main>'
        second = f'<main>{body} href="/api/media/statute.pdf?revision=29\\u0026timestamp=2026-09-21T04%3A45%3A22.441Z"</main>'
        self.assertEqual(_normalized_legal_text(first), _normalized_legal_text(second))

    def test_official_fallback_is_used_when_primary_route_fails(self) -> None:

        def fake_fingerprint(url: str) -> str:
            if url == 'primary':
                raise RuntimeError('temporary empty response')
            return 'fallback-hash'
        with patch('knowledge_update._fingerprint', side_effect=fake_fingerprint):
            self.assertEqual(_fingerprint_source(('primary', 'fallback')), {'fallback': 'fallback-hash'})

    def test_preferred_official_route_wins_when_both_are_healthy(self) -> None:
        with patch('knowledge_update._fingerprint', side_effect=lambda url: f'{url}-hash'):
            self.assertEqual(_fingerprint_source(('primary', 'fallback')), {'primary': 'primary-hash', 'fallback': 'fallback-hash'})

    def test_version_comparison_is_numeric(self) -> None:
        self.assertGreater(version_key('2026.08.27-10'), version_key('2026.08.27-9'))

    def test_bundled_rulepack_is_valid(self) -> None:
        pack = load_rulepack()
        validate_rulepack(pack)
        self.assertIn('EU', pack['coverage_groups'])

    def test_invalid_deadline_is_rejected(self) -> None:
        pack = json.loads(Path('legal_rulepack.json').read_text(encoding='utf-8'))
        pack['coverage_groups']['EU']['refund_deadline_days'] = 0
        with self.assertRaises(RulepackError):
            validate_rulepack(pack)

    def test_signed_rulepack_update(self) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        candidate = json.loads(Path('legal_rulepack.json').read_text(encoding='utf-8'))
        candidate['rulepack_version'] = '9999.01.01-1'
        payload = json.dumps(candidate, ensure_ascii=False).encode('utf-8')
        digest = hashlib.sha256(payload).hexdigest()
        private_key = Ed25519PrivateKey.generate()
        public_key = base64.b64encode(private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        signed = {'rulepack_version': candidate['rulepack_version'], 'download_url': 'https://example.com/rules.json', 'sha256': digest}
        canonical = json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        manifest = {**signed, 'signature': base64.b64encode(private_key.sign(canonical)).decode()}

        class Response:

            def __init__(self, body, is_json=False):
                self.content, self._body, self.is_json = (body, body, is_json)

            def raise_for_status(self):
                return None

            def json(self):
                return manifest

        class Requests:

            @staticmethod
            def get(url, timeout=0):
                return Response(b'', True) if url.endswith('manifest.json') else Response(payload)
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {'LOCALAPPDATA': temp_dir, 'POLICY_AMADEUS_RULEPACK_PUBLIC_KEY': public_key}), patch.dict(sys.modules, {'requests': Requests}):
            result = update_from_manifest('https://example.com/manifest.json')
            self.assertEqual(result['state'], 'updated')
            self.assertEqual(load_rulepack()['rulepack_version'], '9999.01.01-1')

    def test_unsigned_manifest_is_rejected(self) -> None:

        class Response:

            def raise_for_status(self):
                return None

            def json(self):
                return {'rulepack_version': '9999', 'download_url': 'https://example.com/rules', 'sha256': '0' * 64}

        class Requests:

            @staticmethod
            def get(url, timeout=0):
                return Response()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {'LOCALAPPDATA': temp_dir}, clear=False), patch.dict(sys.modules, {'requests': Requests}):
            os.environ.pop('POLICY_AMADEUS_RULEPACK_PUBLIC_KEY', None)
            with self.assertRaises(RulepackError):
                update_from_manifest('https://example.com/manifest.json')

class LocalizedOutputTests(unittest.TestCase):

    def test_translator_error_text_is_rejected(self) -> None:
        documents = [(str(index), 'No translation was found using the current translator. ' * 5) for index in range(6)]
        with self.assertRaises(PolicyValidationError):
            validate_localized_output(documents, 'support@example.com', '+45 12 34 56 78')

    def test_contact_mutation_is_rejected(self) -> None:
        documents = [(str(index), 'A' * 150) for index in range(6)]
        with self.assertRaises(PolicyValidationError):
            validate_localized_output(documents, 'support@example.com', '+45 12 34 56 78')

    def test_incomplete_shipping_policy_is_detected(self) -> None:
        missing = missing_policy_concepts([('Shipping Policy', 'Shipping costs and tracking only')])
        self.assertIn('Shipping Policy', missing)
        self.assertIn('shipping destinations', missing['Shipping Policy'])
        self.assertIn('order processing time', missing['Shipping Policy'])
        self.assertIn('customs, duties and taxes', missing['Shipping Policy'])

    def test_incomplete_refund_policy_is_detected(self) -> None:
        missing = missing_policy_concepts([('Refund and Return Policy', 'Refunds and payment method')])
        self.assertIn('Refund and Return Policy', missing)
        self.assertIn('applicable return window', missing['Refund and Return Policy'])
        self.assertIn('return shipping costs', missing['Refund and Return Policy'])
        self.assertIn('exceptions', missing['Refund and Return Policy'])

class ResultGroupingTests(unittest.TestCase):

    def test_compact_scope_uses_all_and_exclusion_labels(self) -> None:
        markets = [{'country': name} for name in ('Germany', 'France', 'Ireland', 'Spain', 'Italy')]
        self.assertEqual(compact_market_scope(markets, markets), '全部适配')
        self.assertEqual(compact_market_scope(markets, markets[:4]), '除意大利外均适配')
        self.assertEqual(compact_market_scope(markets, markets[:2]), '德国、法国')

    def test_common_values_merge_and_different_market_is_not_omitted(self) -> None:
        markets = [{'country': 'Germany', 'value': '共同填写值'}, {'country': 'Austria', 'value': '共同填写值'}, {'country': 'Italy', 'value': '意大利专用填写值'}]
        groups = group_market_values(markets, lambda market: market['value'])
        self.assertEqual(len(groups), 2)
        self.assertEqual([m['country'] for m in groups[0]['markets']], ['Germany', 'Austria'])
        self.assertEqual(groups[0]['value'], '共同填写值')
        self.assertEqual([m['country'] for m in groups[1]['markets']], ['Italy'])
        self.assertEqual(groups[1]['value'], '意大利专用填写值')

    def test_two_different_markets_both_render_as_separate_groups(self) -> None:
        markets = [{'country': 'Germany', 'value': '德国要求'}, {'country': 'Austria', 'value': '奥地利要求'}]
        groups = group_market_values(markets, lambda market: market['value'])
        self.assertEqual([(g['markets'][0]['country'], g['value']) for g in groups], [('Germany', '德国要求'), ('Austria', '奥地利要求')])

class GenerationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_dir.cleanup)
        env = patch.dict(os.environ, {'LOCALAPPDATA': cls.fixture_dir.name})
        env.start()
        cls.addClassCleanup(env.stop)
        if os.environ.get('POLICY_AUTOMATION_SYNTHETIC_IDENTITY') == '1' or not (LICENCE_DIR / '12710.pdf').exists():
            fields = {key: '' for key in ('unit', 'vat_id', 'duns_number', 'first_name', 'last_name')}
            fields.update(legal_name='Example ApS', organization_name='Example ApS', profile_type='组织', country='Denmark', street_address='Examplevej 1', postal_code='2600', city='Glostrup', registration_number='12345678', registration_label='CVR No.', legal_form='Anpartsselskab (ApS)', register_name='Det Centrale Virksomhedsregister', authorized_representative='Example Director')
            for target, result in (('policy_generator.extract_license_fields', fields), ('policy_generator.extract_license_data', ('Example ApS\nExamplevej 1\n2600 Glostrup\nDenmark', ''))):
                fixture = patch(target, return_value=result)
                fixture.start()
                cls.addClassCleanup(fixture.stop)
        with patch('knowledge_update._fingerprint_source', side_effect=lambda urls: {urls[0]: 'fixture'}), patch('knowledge_update.update_from_manifest', return_value={'state': 'unchanged'}):
            run_startup_check()

    def test_all_visible_markets_generate_six_policies(self) -> None:
        for market in sorted(VERIFIED_MARKETS):
            with self.subTest(market=market):
                policies, settings = generate_translated_bundle(market, 'support@example.com', '+45 12 34 56 78', str(LICENCE_DIR / '12710.pdf'), '英语', 'Example', 'https://example.com')
                self.assertEqual(len(policies), 6)
                self.assertEqual(settings['markets'][0]['validation_status'], '通过')

    def test_germany_austria_common_values_match(self) -> None:
        _policies, settings = generate_translated_bundle('Germany，Austria', 'support@example.com', '+45 12 34 56 78', str(LICENCE_DIR / '12710.pdf'), '英语', 'Example', 'https://example.com')
        germany, austria = settings['markets']
        for key in ('processing_time', 'shipping_time', 'refund_time', 'return_window', 'returns', 'exchanges'):
            self.assertEqual(germany[key], austria[key])
        from datetime import date
        if date.today() < date(2026, 10, 1):
            self.assertNotEqual(germany['withdrawal_function'], austria['withdrawal_function'])
        else:
            self.assertTrue(austria['withdrawal_function_required'])

    def test_italy_uses_current_consumer_code_withdrawal_function_and_source(self) -> None:
        policies, settings = generate_translated_bundle('Italy', 'support@example.com', '+45 12 34 56 78', str(LICENCE_DIR / '12710.pdf'), 'English', 'Example', 'https://example.com')
        italy = settings['markets'][0]
        self.assertTrue(italy['withdrawal_function_required'])
        self.assertEqual(italy['withdrawal_start_label'], 'Esercita il diritto di recesso')
        self.assertEqual(italy['withdrawal_confirm_label'], 'Conferma il recesso')
        self.assertTrue(any(('normattiva.it' in source for source in italy['official_sources'])))
        refund = next((body for title, body in policies if title == 'Refund and Return Policy'))
        self.assertIn('Electronic Withdrawal Function for Italy', refund)
        self.assertIn('Esercita il diritto di recesso', refund)
        self.assertIn('Conferma il recesso', refund)
        terms = next((body for title, body in policies if title == 'Terms of Service'))
        self.assertIn('environmental claims accurately', terms)
        self.assertIn('market-surveillance authorities', terms)

    def test_shipping_cost_and_customs_responsibility_are_explicit(self) -> None:
        modes = {'卖家承担（客户收货时不另付）': 'the seller bears any applicable customs duties', '消费者承担（结账前明确披露）': 'the customer is the importer and bears', '不适用（境内或关税同盟内配送）': 'the customer is not charged import customs duty'}
        for mode, expected in modes.items():
            with self.subTest(mode=mode):
                policies, settings = generate_translated_bundle('Germany', 'support@example.com', '+45 12 34 56 78', str(LICENCE_DIR / '12710.pdf'), '英语', 'Example', 'https://example.com', mode)
                shipping = next((body for title, body in policies if title == 'Shipping Policy'))
                self.assertIn('free for all orders delivered within Germany', shipping)
                self.assertIn(expected, shipping.casefold())
                self.assertEqual(settings['customs_responsibility'], mode)

    def test_generated_identity_does_not_claim_an_unverified_licence(self) -> None:
        policies, _settings = generate_translated_bundle('Germany', 'support@example.com', '+45 12 34 56 78', str(LICENCE_DIR / '12710.pdf'), '英语', 'Example', 'https://example.com')
        text = '\n'.join((body for _title, body in policies)).casefold()
        for phrase in ('licensed business', 'licensed seller', 'licensed company', 'licensed operator'):
            self.assertNotIn(phrase, text)
        self.assertIn('the legal business identified below operates this online store', text)
        self.assertIn('purchases are made directly between the customer and the seller identified in these terms', text)

    def test_current_eu_repair_right_update_is_in_refund_policy(self) -> None:
        policies, _settings = generate_translated_bundle('Germany', 'support@example.com', '+45 12 34 56 78', str(LICENCE_DIR / '12710.pdf'), '英语', 'Example', 'https://example.com')
        refund = next((body for title, body in policies if title == 'Refund and Return Policy'))
        self.assertIn('repairability', refund)
        self.assertIn('extended once by **12 months**', refund)

    def test_eea_market_does_not_inherit_unconfirmed_eu_repair_extension(self) -> None:
        policies, _settings = generate_translated_bundle('Norway', 'support@example.com', '+45 12 34 56 78', str(LICENCE_DIR / '12710.pdf'), '英语', 'Example', 'https://example.com')
        refund = next((body for title, body in policies if title == 'Refund and Return Policy'))
        self.assertNotIn('extended once by **12 months**', refund)

    def test_refund_deadline_and_return_dispatch_wording(self) -> None:
        policies, _settings = generate_translated_bundle('Ireland', 'support@example.com', '+45 12 34 56 78', str(LICENCE_DIR / '12710.pdf'), '英语', 'Example', 'https://example.com')
        refund = next((body for title, body in policies if title == 'Refund and Return Policy'))
        self.assertNotIn('calendar days days', refund)
        self.assertIn('14 calendar days after sending the notice', refund)
        self.assertIn('up to 6 years', refund)

    def test_requested_twenty_five_markets_are_all_preserved(self) -> None:
        markets = 'Ireland,France,Germany,Netherlands,Belgium,Austria,Denmark,Norway,Sweden,Spain,Portugal,Italy,Greece,Cyprus,Poland,Czechia,Slovakia,Hungary,Romania,Bulgaria,Estonia,Latvia,Lithuania,Slovenia,Croatia'
        policies, settings = generate_translated_bundle(markets, 'support@example.com', '+45 12 34 56 78', str(LICENCE_DIR / '12710.pdf'), '英语', 'Example', 'https://example.com')
        self.assertEqual(len(settings['markets']), 25)
        self.assertEqual(len({m['country'] for m in settings['markets']}), 25)
        for title, body in policies[:4]:
            with self.subTest(title=title):
                self.assertEqual(body.count('# Ireland\n'), 1)
                self.assertEqual(body.count('# Croatia\n'), 1)
if __name__ == '__main__':
    unittest.main(verbosity=2)
