"""Master-switch and updater boundaries. No real disks or network are touched."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin"))
import updates
from opencas_cache import OpenCasCache

spec = importlib.util.spec_from_file_location("updater_service_check", ROOT / "plugin/cache_service.py")
service = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    "pwd": types.SimpleNamespace(getpwnam=lambda _: types.SimpleNamespace(pw_dir="/home/deck", pw_uid=1000)),
    "fcntl": types.SimpleNamespace(flock=Mock(), LOCK_EX=2),
}):
    spec.loader.exec_module(service)


class MasterSwitch(unittest.TestCase):
    def manager(self):
        m = service.Manager.__new__(service.Manager)
        m.config = {"enabled": True, "cache": {"uuid": "ssd"}, "libraries": [
            {"id": "one", "path": "/games", "uuid": "hdd"}]}
        m.runtime = {}
        m.errors = {}
        m.block = Mock(spec=OpenCasCache)
        m.block.table.return_value = {}
        m.block.origin.return_value = "/dev/original"
        m.save = Mock()
        m.ensure_cache = Mock()
        m.activate = Mock()
        m.deactivate = Mock()
        return m

    def test_busy_game_refuses_disable_before_any_change(self):
        m = self.manager()
        with patch.object(service, "busy", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "Close games"):
                m.set_enabled(False)
        self.assertTrue(m.config["enabled"])
        m.deactivate.assert_not_called()
        m.save.assert_not_called()

    def test_disable_keeps_selection_and_stops_active_cache(self):
        m = self.manager()
        m.block.table.return_value = {"type": "cache"}
        m.reconcile = Mock()
        original = list(m.config["libraries"])
        with patch.object(service, "busy", return_value=False):
            m.set_enabled(False)
        self.assertFalse(m.config["enabled"])
        self.assertEqual(original, m.config["libraries"])
        m.deactivate.assert_not_called()
        m.block.set_mode.assert_called_once_with(original[0], "pt")
        m.block.release_allocations.assert_not_called()

    def test_missing_kernel_uses_hdd_with_either_switch_position(self):
        for enabled in (False, True):
            m = self.manager()
            m.config["enabled"] = enabled
            with patch.object(service, "mounts", return_value={}), patch.object(service, "save_json"), \
                    patch.object(service, "compatibility", return_value={"supported": False, "message": "Module unavailable"}):
                m.reconcile()
            m.ensure_cache.assert_not_called()
            m.activate.assert_not_called()
            m.block.load_modules.assert_not_called()
            m.block.mount_original.assert_called_once_with(m.config["libraries"][0], "/dev/original")

    def test_fallback_never_mounts_an_origin_owned_by_cache(self):
        m = self.manager()
        m.config["enabled"] = False
        m.block.table.return_value = {"type": "cache"}
        with patch.object(service, "mounts", return_value={}), patch.object(service, "save_json"):
            m.reconcile()
        m.block.mount_original.assert_not_called()

    def test_prepared_update_uninstall_does_not_need_disconnected_selected_drives(self):
        m = self.manager()
        m.config["enabled"] = False
        m.config["update_pending"] = True
        with patch.object(service, "mounts", return_value={}):
            m.stop_all()
        m.ensure_cache.assert_not_called()
        m.block.deactivate.assert_not_called()


    def test_bypass_is_restored_at_boot_without_enabling_acceleration(self):
        m = self.manager()
        m.config["enabled"] = False
        with patch.object(service, "compatibility", return_value={"supported": True}), patch.object(service, "save_json"):
            m.reconcile()
        m.ensure_cache.assert_called_once()
        m.activate.assert_called_once_with(m.config["libraries"][0])
        self.assertFalse(m.config["enabled"])

    def test_mode_switch_does_not_detach_or_clear_cache(self):
        engine = OpenCasCache.__new__(OpenCasCache)
        engine.m = types.SimpleNamespace(config={"enabled": False})
        engine.active = Mock(return_value=True)
        engine.verify = Mock(side_effect=[{"mode": "wt", "dirty": 0}, {"mode": "pt", "dirty": 0}])
        engine.cli = Mock()
        engine.invalidate = Mock()
        engine.run = Mock()
        lib = {"cas_id": 1001}
        engine.activate(lib)
        engine.cli.assert_called_once_with("-Q", "-i", "1001", "-c", "pt", timeout=120)
        engine.invalidate.assert_not_called()
        engine.run.assert_not_called()


class UpdateSelection(unittest.TestCase):
    def test_selects_newest_matching_stable_release_instead_of_latest(self):
        manifests = {}
        def release(version, kernel, prerelease=False):
            tag = "v" + version
            names = ["deckycache-update.json", "DeckyCache-" + version + ".zip"]
            assets = [{"name": name, "size": 100, "browser_download_url": updates.DOWNLOADS + tag + "/" + name} for name in names]
            manifests[assets[0]["browser_download_url"]] = {
                "schema": 1, "version": version, "channel": "stable", "arch": "x86_64",
                "kernels": [kernel], "asset": names[1], "sha256": "a" * 64}
            return {"tag_name": tag, "prerelease": prerelease, "draft": False, "assets": assets}
        releases = [release("0.7.0", "test-kernel", True),
                    release("0.6.0", "other-kernel"), release("0.5.0", "test-kernel")]
        def read(url, _):
            return json.dumps(releases if "/releases?" in url else manifests[url]).encode()
        with patch.object(updates, "read_url", side_effect=read), \
                patch.object(updates.platform, "machine", return_value="x86_64"):
            candidate = updates.check_update("0.4.5-dev2", "test-kernel")
            self.assertEqual(candidate["version"], "0.5.0")
            self.assertIsNone(updates.check_update("0.5.0", "test-kernel"))
            self.assertIsNone(updates.check_update("0.4.4", "unmatched-kernel"))

    def archive(self, extra=None, module_digest=None):
        version, kernel = "0.5.0", "test-kernel"
        content = {"DeckyCache/package.json": json.dumps({"version": version}),
                   "DeckyCache/plugin.json": json.dumps({"name": "DeckyCache"})}
        hashes = {}
        for name in ("casadm", "cas_bd.ko", "cas_cache.ko"):
            body = "test-" + name
            path = "DeckyCache/bin/opencas/" + (name if name == "casadm" else kernel + "/" + name)
            content[path] = body
            hashes[name] = hashlib.sha256(body.encode()).hexdigest()
        if module_digest:hashes["cas_cache.ko"] = module_digest
        content["DeckyCache/bin/opencas/" + kernel + "/manifest.json"] = json.dumps({"kernel": kernel, "sha256": hashes})
        for name in ("main.py", "cache_service.py", "compatibility.py", "updates.py", "dist/index.js"):
            content["DeckyCache/" + name] = ""
        if extra:content[extra] = "unsafe"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, body in content.items():archive.writestr(name, body)
        data = stream.getvalue()
        return data, {"version": version, "kernel": kernel, "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()}

    def test_archive_hash_kernel_modules_and_paths_are_checked(self):
        with patch.object(updates.platform, "release", return_value="test-kernel"):
            data, candidate = self.archive()
            updates.verify_archive(data, candidate)
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                updates.verify_archive(data + b"changed", candidate)
            for extra in ("DeckyCache/../../outside", "OtherPlugin/main.py", "DeckyCache/C:/outside", "DeckyCache/./main.py"):
                data, candidate = self.archive(extra=extra)
                with self.assertRaisesRegex(RuntimeError, "unsafe path"):
                    updates.verify_archive(data, candidate)
            data, candidate = self.archive(module_digest="0" * 64)
            with self.assertRaisesRegex(RuntimeError, "module failed"):
                updates.verify_archive(data, candidate)
        data, candidate = self.archive()
        with patch.object(updates.platform, "release", return_value="different-kernel"):
            with self.assertRaisesRegex(RuntimeError, "kernel changed"):
                updates.verify_archive(data, candidate)


class BridgeFailure(unittest.IsolatedAsyncioTestCase):
    async def test_service_failure_keeps_plugin_loadable(self):
        spec = importlib.util.spec_from_file_location("update_bridge_check", ROOT / "plugin/main.py")
        main = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"decky": types.SimpleNamespace(logger=Mock())}):
            spec.loader.exec_module(main)
        plugin = main.Plugin()
        with patch.object(plugin, "_install_service", side_effect=RuntimeError("service unavailable")):
            await plugin._main()
        main.decky.logger.exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()
