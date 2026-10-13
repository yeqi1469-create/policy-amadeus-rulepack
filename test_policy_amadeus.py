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
from policy_generator import extract_license_fields, generate_translated_bundle
from policy_studio import VERIFIED_MARKETS, compact_market_scope, group_market_values
from policy_validator import PolicyValidationError, missing_policy_concepts, validate_localized_output
from rulepack_manager import RulepackError, load_rulepack, validate_rulepack, version_key
LICENCE_DIR = Path('synthetic-test-fixture')

class RulepackTests(unittest.TestCase):
    def test_version_comparison_is_numeric(self):
        self.assertGreater(version_key('2026.08.27-10'),version_key('2026.08.27-9'))
    def test_bundled_rulepack_is_valid(self):
        pack=load_rulepack()
        validate_rulepack(pack)
        self.assertIn('EU',pack['coverage_groups'])
    def test_invalid_deadline_is_rejected(self):
        pack=json.loads(Path('legal_rulepack.json').read_text(encoding='utf-8'))
        pack['coverage_groups']['EU']['refund_deadline_days']=0
        with self.assertRaises(RulepackError): validate_rulepack(pack)

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
    def test_lithuania_legacy_finding_generates_six_visible_drafts_without_clearance(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,LOCALAPPDATA=directory):
            report=Path(directory)/'Policy Amadeus'/'knowledge_coverage_latest.json'
            report.parent.mkdir()
            original=json.dumps({'changed':['Country — Lithuania'],'rulepack_version':'older_report'})
            report.write_text(original,encoding='utf-8')
            policies,settings=generate_translated_bundle('Lithuania','support@example.com','+45 12 34 56 78',str(LICENCE_DIR/'12710.pdf'),'英语','Example','https://example.com')
            self.assertEqual(len(policies),6)
            self.assertTrue(all(body.startswith('DRAFT — PENDING LEGAL REVIEW — NOT FOR PUBLICATION') for _,body in policies))
            self.assertEqual(settings['legal_review_status'],'pending')
            self.assertFalse(settings['publication_approved'])
            self.assertEqual(report.read_text(encoding='utf-8'),original)

if __name__ == '__main__':
    unittest.main(verbosity=2)
