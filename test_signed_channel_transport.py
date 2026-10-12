import unittest
from unittest.mock import Mock,patch
import requests
import signed_channel_transport as transport

class SignedChannelRecovery(unittest.TestCase):
    def test_configured_publisher_direct_tls_after_proxy_failure(self):
        direct=Mock()
        direct.get.return_value=Mock(status_code=200)
        with patch('requests.get',side_effect=requests.ReadTimeout),patch('requests.Session',return_value=direct):
            result=transport.get('https://raw.githubusercontent.com/example/public/app_manifest.json',timeout=10)
        self.assertEqual(result.status_code,200)
        self.assertFalse(direct.trust_env)
        self.assertNotIn('verify',direct.get.call_args.kwargs)
    def test_unconfigured_host_and_http_not_fallback_trusted(self):
        for url in ('https://unconfigured.example/private','http://raw.githubusercontent.com/example'):
            with patch('requests.get',side_effect=requests.ReadTimeout),patch('requests.Session') as session:
                with self.assertRaises(requests.ReadTimeout):transport.get(url,timeout=10)
            session.assert_not_called()
    def test_http_authorization_error_not_bypassed(self):
        response=Mock(status_code=403)
        with patch('requests.get',return_value=response),patch('requests.Session') as session:
            self.assertIs(transport.get('https://raw.githubusercontent.com/example'),response)
        session.assert_not_called()

if __name__=='__main__': unittest.main()
