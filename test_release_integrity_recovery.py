import unittest
from unittest.mock import Mock,patch
from pathlib import Path
import app_updater as updater

class IntegrityRecoveryTests(unittest.TestCase):
    def test_exact_authorized_commit_recovery_keeps_signed_hash(self):
        url='https://raw.githubusercontent.com/yeqi1469-create/policy-amadeus-rulepack/main/PolicyAmadeus.exe'
        response=Mock()
        response.json.return_value={'object':{'sha':'a'*40}}
        with patch.object(updater,'_download_verified_once',side_effect=[updater.UpdateIntegrityError(),Path('verified.exe')]) as download,patch('requests.get',return_value=response):
            self.assertEqual(updater._download_verified(url,'b'*64),Path('verified.exe'))
        self.assertEqual(download.call_args.args[0],url.replace('/main/','/'+'a'*40+'/'))
        self.assertEqual(download.call_args.args[1],'b'*64)
    def test_second_integrity_failure_never_approves_or_loops(self):
        response=Mock()
        response.json.return_value={'object':{'sha':'a'*40}}
        with patch.object(updater,'_download_verified_once',side_effect=updater.UpdateIntegrityError) as download,patch('requests.get',return_value=response):
            with self.assertRaises(updater.UpdateIntegrityError):
                updater._download_verified('https://raw.githubusercontent.com/yeqi1469-create/policy-amadeus-rulepack/main/PolicyAmadeus.exe','b'*64)
        self.assertEqual(download.call_count,2)
    def test_other_repositories_do_not_get_recovery(self):
        with patch.object(updater,'_download_verified_once',side_effect=updater.UpdateIntegrityError),patch('requests.get') as get:
            with self.assertRaises(updater.UpdateIntegrityError): updater._download_verified('https://raw.githubusercontent.com/other/repo/main/program.exe','b'*64)
        get.assert_not_called()

if __name__=='__main__': unittest.main()
