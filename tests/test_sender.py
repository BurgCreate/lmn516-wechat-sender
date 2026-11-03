import os
import tempfile
import unittest
from pathlib import Path
from lmn_wechat_sender import send_message, digest_text


class FakeBackend:
    def __init__(self, fail_on=None):
        self.actions = []
        self.fail_on = fail_on
        self.calls = 0

    def activate(self):
        self.actions.append("activate")

    def press(self, keys):
        self.calls += 1
        self.actions.append(("press", keys))
        if self.fail_on == self.calls:
            raise RuntimeError("simulated input failure")

    def paste(self, text):
        self.actions.append(("paste", text))

    def wait(self):
        pass


class SenderTests(unittest.TestCase):
    def test_five_steps_once(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as directory:
            result = send_message("Example", "hello", backend=backend,
                                  lock_path=Path(directory) / "lock")
        self.assertTrue(result["ok"])
        self.assertTrue(result["attempted"])
        self.assertFalse(result["accepted_by_client"])
        self.assertEqual(result["delivery_state"], "enter-dispatched-unverified")
        self.assertEqual([v for v in backend.actions if v == ("paste", "Example")], [("paste", "Example")])
        self.assertEqual([v for v in backend.actions if v == ("paste", "hello")], [("paste", "hello")])
        self.assertEqual(sum(v == ("press", "key code 36") for v in backend.actions), 2)

    def test_error_before_enter(self):
        backend = FakeBackend(fail_on=1)
        with tempfile.TemporaryDirectory() as directory:
            result = send_message("Example", "hello", backend=backend,
                                  lock_path=Path(directory) / "lock")
        self.assertFalse(result["ok"])
        self.assertFalse(result["attempted"])
        self.assertEqual(result["delivery_state"], "not-attempted")

    def test_ambiguous_enter(self):
        backend = FakeBackend(fail_on=5)
        with tempfile.TemporaryDirectory() as directory:
            result = send_message("Example", "hello", backend=backend,
                                  lock_path=Path(directory) / "lock")
        self.assertFalse(result["ok"])
        self.assertTrue(result["attempted"])
        self.assertEqual(result["delivery_state"], "ambiguous-do-not-resend")

    def test_dry_run_never_activates(self):
        result = send_message("Example", "hello", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["attempted"])

    def test_source_lock_rejects_mismatch(self):
        with self.assertRaises(ValueError):
            send_message("Example", "hello", dry_run=True, source_sha256=digest_text("other"))


if __name__ == "__main__":
    unittest.main()
