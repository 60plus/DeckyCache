"""Small host-independent checks; never mounts, formats or contacts a device."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin"))
# Import the service on Windows as well as Linux without requiring user deck.
# No actual locking/storage operations are exercised by these boundary checks.
stubs = {
    "pwd": types.SimpleNamespace(getpwnam=lambda _: types.SimpleNamespace(pw_dir="/home/deck", pw_uid=1000)),
    "fcntl": types.SimpleNamespace(flock=Mock(), LOCK_EX=2),
}
spec = importlib.util.spec_from_file_location("cache_service_check", ROOT / "plugin/cache_service.py")
service = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, stubs):
    spec.loader.exec_module(service)


class LifecycleCheck(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rules = self.root / "etc/udev/rules.d"
        self.rules.mkdir(parents=True)
        self.vendor = self.root / "usr/lib/udev/rules.d/99-steamos-automount.rules"
        self.vendor.parent.mkdir(parents=True)
        self.vendor.write_text('ACTION=="add", RUN+="vendor-automount"\nLABEL="steamos_automount_end"\n')
        self.override = self.rules / "99-steamos-automount.rules"
        self.manager = service.Manager.__new__(service.Manager)
        self.manager.config = {"cache": None, "libraries": []}

    def rule_path(self, value):
        return self.root / value.lstrip("/")

    def test_no_selection_does_not_change_rules_or_trigger_devices(self):
        for custom in (None, "# User's custom automount rules\n"):
            with self.subTest(custom_rule=custom is not None):
                if custom is not None:
                    self.override.write_text(custom)
                before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                with patch.object(service, "Path", self.rule_path), patch.object(service, "command") as command:
                    self.manager.sync_rules()
                after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                self.assertEqual(before, after)
                command.assert_not_called()

    def test_selected_disk_still_gets_automount_protection_once(self):
        self.manager.config = {"cache": {"uuid": "1111-aaaa"}, "libraries": [{"uuid": "2222-bbbb"}]}
        original = self.vendor.read_bytes()
        with patch.object(service, "Path", self.rule_path), patch.object(service, "command") as command:
            self.manager.sync_rules()
            self.assertTrue(command.called)
            rule = (self.rules / "99-deckycache.rules").read_text()
            for uuid in ("1111-aaaa", "2222-bbbb"):
                self.assertIn(f'ENV{{ID_FS_UUID}}=="{uuid}", ENV{{UDISKS_IGNORE}}="1"', rule)
            self.assertTrue(self.override.read_bytes().endswith(original))
            self.assertEqual(original, self.vendor.read_bytes())
            command.reset_mock()
            self.manager.sync_rules()
            command.assert_not_called()

    def test_nvidia_shutdown_guard_tracks_selection_and_is_idempotent(self):
        (self.root / "sys/module/nvidia").mkdir(parents=True)
        guard = self.root / "etc/systemd/system/plymouth-reboot.service.d/90-deckycache-shutdown-order.conf"
        with patch.object(service, "Path", self.rule_path), patch.object(service, "command") as command:
            self.manager.sync_shutdown_order()
            self.assertFalse(guard.exists())
            command.assert_not_called()
            self.manager.config["libraries"] = [{"uuid": "2222-bbbb"}]
            self.manager.sync_shutdown_order()
            self.assertIn("After=user@1000.service deckycache.service", guard.read_text())
            command.assert_called_once_with("systemctl", "daemon-reload")
            command.reset_mock()
            self.manager.sync_shutdown_order()
            command.assert_not_called()
            self.manager.config["libraries"] = []
            self.manager.sync_shutdown_order()
            self.assertFalse(guard.exists())
            command.assert_called_once_with("systemctl", "daemon-reload")

    def test_shutdown_guard_preserves_custom_file_and_other_hardware(self):
        guard = self.root / "etc/systemd/system/plymouth-reboot.service.d/90-deckycache-shutdown-order.conf"
        guard.parent.mkdir(parents=True)
        guard.write_text("# User configuration\n")
        self.manager.config["libraries"] = [{"uuid": "2222-bbbb"}]
        with patch.object(service, "Path", self.rule_path), patch.object(service, "command") as command:
            self.manager.sync_shutdown_order()
            command.assert_not_called()
            (self.root / "sys/module/nvidia").mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "custom shutdown-order"):
                self.manager.sync_shutdown_order()
            self.assertEqual(guard.read_text(), "# User configuration\n")
            command.assert_not_called()

    def test_request_queued_before_checkpoint_cannot_reactivate_cache(self):
        run, state = self.root / "run", self.root / "state"
        stopping = run / "stopping"
        # The stop marker appears while a request waits to acquire the lock.
        def acquire(*_):
            stopping.touch()
        with patch.object(service, "RUN", run), patch.object(service, "STATE", state), \
                patch.object(service.fcntl, "flock", side_effect=acquire), \
                patch.object(service, "Manager") as manager:
            for action in ("format", "reuse", "library", "reconcile", "migrate-opencas", "clear-cache", "enabled", "prepare-update"):
                with self.subTest(action=action):
                    stopping.unlink(missing_ok=True)
                    with self.assertRaisesRegex(RuntimeError, "Cache is stopping"):
                        service.locked_action({"action": action})
                    manager.assert_not_called()
            # Status and cleanup remain possible while stopping.
            for action in ("status", "stop", "checkpoint"):
                service.locked_action({"action": action})
                manager.return_value.action.assert_called_with({"action": action})


if __name__ == "__main__":
    unittest.main()
