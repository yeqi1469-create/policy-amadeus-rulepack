import unittest
from unittest.mock import Mock, patch

import requests
import app_updater
import codex_review_worker as worker


class UpdateTransportTests(unittest.TestCase):
    def test_repository_reads_retry_without_retrying_publication(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True}
        session = Mock()
        session.get.side_effect = [requests.ReadTimeout(), requests.ConnectionError(), response]
        with patch.object(worker, "folder", return_value=__import__('pathlib').Path('synthetic-absent-folder')), patch.object(worker.time, "sleep"):
            self.assertEqual(worker._api(session, "GET", "/git/ref/heads/main"), {"ok": True})
        self.assertEqual(session.get.call_count, 3)
        session.request.side_effect = requests.ReadTimeout()
        with self.assertRaises(requests.ReadTimeout):
            worker._api(session, "POST", "/git/commits", json={"synthetic": True})
        session.request.assert_called_once()

    def test_repository_read_failure_bounded_and_auth_denial_not_retried(self):
        session = Mock()
        session.get.side_effect = requests.ReadTimeout()
        with patch.object(worker, "folder", return_value=__import__('pathlib').Path('synthetic-absent-folder')), patch.object(worker.time, "sleep"):
            with self.assertRaises(requests.ReadTimeout):
                worker._api(session, "GET", "")
        self.assertEqual(session.get.call_count, 3)
        session = Mock()
        session.get.return_value = Mock(status_code=403)
        with patch.object(worker, "folder", return_value=__import__('pathlib').Path('synthetic-absent-folder')):
            with self.assertRaises(worker.ReviewError):
                worker._api(session, "GET", "")
        session.get.assert_called_once()

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
