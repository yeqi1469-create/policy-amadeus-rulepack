import copy,hashlib,json,os,tempfile,unittest
from unittest.mock import patch
import current_law_review as current
import codex_review_worker as worker
import rulepack_manager as manager

class FullCurrentRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.environment=patch.dict(os.environ,{'LOCALAPPDATA':self.directory.name})
        self.environment.start()
        self.pack=manager.load_rulepack()
        self.url='https://e-seimas.lrs.lt/portal/legalAct/lt/TAD/TAIS.6020/asr'
        self.old='https://e-seimas.lrs.lt/portal/legalAct/lt/TAD/TAIS.163482'
        self.body='Article 1. Official synthetic consumer statute requirement. '*100
        self.evidence={'mode':current.MODE,'source':'Country — Lithuania','url':self.old,'new_url':self.url,
                       'new_sha256':hashlib.sha256(self.body.encode()).hexdigest(),'after':self.body,
                       'before':None,'old_sha256':None,'historical_body_available':False}
        self.decision={'classification':'already_covered','reason':'Full current synthetic law covered',
                      'effective_on':'','effective_timezone':'','quotes':[self.body[:50]],'patches':[]}
        self.verifier={'approved':True,'reason':'Independent full current synthetic check',
                       'quotes':[self.body[:50]],**{g:True for g in current.GATES}}
    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()
    def proposal(self):
        return {'id':worker.digest({'source':self.evidence['source'],'url':self.old,
                    'new':self.evidence['new_sha256'],'base':worker.digest(self.pack)}),
                'base_rulepack_sha256':worker.digest(self.pack),'evidence':self.evidence,
                'decision':self.decision,'verification':self.verifier}
    def test_explicit_retired_route_can_only_migrate_after_full_revalidation(self):
        merged=worker.merge_proposal(self.pack,self.proposal())
        self.assertEqual(merged['reviewed_source_replacements'][self.evidence['source']][self.old]['url'],self.url)
        self.assertFalse(merged['codex_review_history'][-1]['historical_body_available'])
        self.assertNotIn(self.evidence['source'],self.pack.get('reviewed_source_replacements',{}))
    def test_missing_independent_gate_blocks_approval(self):
        for gate in current.GATES:
            verifier=copy.deepcopy(self.verifier)
            verifier[gate]=False
            with self.subTest(gate=gate),self.assertRaises(worker.ReviewError):
                current.validate(self.evidence,self.decision,verifier)
    def test_metadata_only_without_old_body_forbidden(self):
        self.decision['classification']='metadata_only'
        with self.assertRaises(worker.ReviewError): worker.validate_proposal(self.proposal(),self.pack)
    def test_unconfigured_supplement_cannot_be_approved(self):
        self.evidence['additional_documents']=[{'url':'https://untrusted.example/law','sha256':self.evidence['new_sha256'],'body':self.body}]
        with self.assertRaises(worker.ReviewError): worker.validate_proposal(self.proposal(),self.pack)
    def test_single_country_numeric_override_does_not_mutate_eu_baseline(self):
        pack=copy.deepcopy(self.pack)
        eu_before=copy.deepcopy(pack['coverage_groups']['EU'])
        worker._apply_patches(pack,[{'path':'/country_overlays/Lithuania/repair_remedy_liability_extension_months','value_json':'0'}])
        self.assertEqual(pack['coverage_groups']['EU'],eu_before)
        rendered=current.policy_examples('Country — Lithuania',pack)
        self.assertTrue(rendered['supported'])
        self.assertNotIn('extended once by **12 months**',rendered['policies']['Refund and Return Policy'])
        with self.assertRaises(worker.ReviewError):
            worker._apply_patches(pack,[{'path':'/country_overlays/Lithuania/refund_deadline_days','value_json':'0'}])
    def test_fabricated_old_body_forbidden(self):
        self.evidence['before']=self.body
        with self.assertRaises(worker.ReviewError): worker.validate_proposal(self.proposal(),self.pack)
    def test_unknown_retired_url_not_trusted(self):
        self.evidence['url']='https://e-seimas.lrs.lt/unreviewed-arbitrary-document'
        with self.assertRaises(worker.ReviewError): current.validate(self.evidence,self.decision,self.verifier)
    def test_chunk_ranges_reconstruct_every_character(self):
        text=('Long consumer statute.\n'*50000)+'END'
        parts=current.chunks(text)
        self.assertEqual(''.join(p['text'] for p in parts),text)
        self.assertEqual(parts[0]['start'],0)
        self.assertEqual(parts[-1]['end'],len(text))
        self.assertTrue(all(a['end']==b['start'] for a,b in zip(parts,parts[1:])))
    def test_actual_templates_render_without_network_or_private_license(self):
        with patch('knowledge_update.run_startup_check',side_effect=AssertionError('No live check in synthetic render')):
            result=current.policy_examples('Country — Lithuania',self.pack)
        self.assertTrue(result['supported'])
        self.assertEqual(set(result['policies']),worker.POLICIES)
        self.assertIn('Synthetic Verification Store',result['policies']['Contact Information'])
    def test_unsupported_market_not_silently_certified(self):
        with patch.object(worker,'codex_json') as model:
            self.evidence['source']='Country — Serbia'
            with self.assertRaises(worker.ReviewError): current.review(self.evidence,self.pack)
        model.assert_not_called()
    def test_no_progress_does_not_repeat_indefinitely(self):
        failed={'state':'retry_pending','source_errors':{'Country — Serbia':{'failed_at':1}}}
        with patch.object(worker,'_run_one',return_value=failed) as attempt:
            self.assertEqual(worker.run(),failed)
        self.assertEqual(attempt.call_count,2)

if __name__=='__main__': unittest.main()
