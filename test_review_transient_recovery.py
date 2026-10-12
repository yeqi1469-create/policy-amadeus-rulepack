import hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import codex_review_worker as worker
import knowledge_update as knowledge
from update_storage import write_json

class TransientReviewRecovery(unittest.TestCase):
    def test_review_recovers_temporary_failure_without_approving_hash(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'LOCALAPPDATA':directory}):
            source='Country — Serbia'
            url=knowledge.SOURCES[source][1]
            text='Official consumer statute article text. '*80
            digest=hashlib.sha256(text.encode()).hexdigest()
            document={'url':url,'normalized_text':text}
            def fetch(candidate):
                self.assertEqual(candidate,url)
                fetch.calls+=1
                if fetch.calls==1: raise TimeoutError('temporary transport failure')
                write_json(worker.folder()/'codex_review/evidence'/(digest+'.json'),document)
                return digest
            fetch.calls=0
            with patch.object(worker,'prior_document',return_value=document), \
                 patch.object(worker,'record'),patch.object(knowledge,'_fingerprint',side_effect=fetch), \
                 patch.object(knowledge.time,'sleep'):
                evidence=worker.prepare_evidence(source,url,digest)
            self.assertEqual(fetch.calls,2)
            self.assertEqual(evidence['before'],evidence['after'])
            self.assertFalse((worker.folder()/'knowledge_update_cache.json').exists())

    def test_all_configured_attempts_failing_keeps_failure(self):
        with patch.object(knowledge,'_fingerprint',side_effect=TimeoutError),patch.object(knowledge.time,'sleep'):
            with self.assertRaises(RuntimeError):
                knowledge._fingerprint_source(('https://official.example/law',))

if __name__=='__main__': unittest.main()
