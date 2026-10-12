import unittest
from unittest.mock import Mock, patch

import requests
import app_updater


class UpdateTransportTests(unittest.TestCase):
    def test_timeout_retries_then_succeeds(self):
        response = Mock(status_code=200)
        with patch("requests.get", side_effect=[requests.Timeout(), requests.ConnectionError(), response]) as get, patch("app_updater.time.sleep") as sleep:
            self.assertIs(app_updater._release_get("https://example.test/manifest", timeout=(15, 30)), response)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_repeated_timeout_is_bounded(self):
        with patch("requests.get", side_effect=requests.Timeout()) as get, patch("app_updater.time.sleep"):
            with self.assertRaises(requests.Timeout):
                app_updater._release_get("https://example.test/manifest")
        self.assertEqual(get.call_count, 3)

    def test_transient_http_retry_closes_failed_response(self):
        failed, success = Mock(status_code=503), Mock(status_code=200)
        with patch("requests.get", side_effect=[failed, success]), patch("app_updater.time.sleep"):
            self.assertIs(app_updater._release_get("https://example.test/manifest"), success)
        failed.close.assert_called_once()

    def test_not_found_not_retried(self):
        response = Mock(status_code=404)
        with patch("requests.get", return_value=response) as get, patch("app_updater.time.sleep") as sleep:
            self.assertIs(app_updater._release_get("https://example.test/manifest"), response)
        get.assert_called_once()
        sleep.assert_not_called()
