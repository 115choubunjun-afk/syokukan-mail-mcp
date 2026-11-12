import unittest
from unittest.mock import Mock

from mailer import Drafts


class MailTests(unittest.TestCase):
    def setUp(self):
        self.deliver = Mock()
        self.drafts = Drafts(self.deliver)

    def test_send_exact_preview_only_once(self):
        key, draft = self.drafts.create("owner@example.com", "测试", "正文")
        self.deliver.assert_not_called()
        self.drafts.confirm(key)
        self.deliver.assert_called_once_with(draft)
        with self.assertRaises(KeyError):
            self.drafts.confirm(key)

    def test_no_retry_when_delivery_is_uncertain(self):
        key, _ = self.drafts.create("owner@example.com", "test", "body")
        self.deliver.side_effect = OSError()
        with self.assertRaises(OSError):
            self.drafts.confirm(key)
        with self.assertRaises(KeyError):
            self.drafts.confirm(key)

    def test_reject_header_injection_and_multiple_addresses(self):
        for address in ("owner@example.com\r\nBcc: a@example.com", "a@example.com,b@example.com"):
            with self.assertRaises(ValueError):
                self.drafts.create(address, "test", "body")
        with self.assertRaises(ValueError):
            self.drafts.create("a@example.com", "test\nCc: x@example.com", "body")
