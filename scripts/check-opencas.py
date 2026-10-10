"""Recovery and clear-cache boundaries; no real devices are used."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"plugin"))
import opencas_cache as cas
spec=importlib.util.spec_from_file_location("service_check",ROOT/"plugin/cache_service.py")
service=importlib.util.module_from_spec(spec)
stubs={"pwd":types.SimpleNamespace(getpwnam=lambda _:types.SimpleNamespace(pw_dir="/home/deck",pw_uid=1000)),
       "fcntl":types.SimpleNamespace(flock=Mock(),LOCK_EX=2)}
with patch.dict(sys.modules,stubs):
    spec.loader.exec_module(service)

class RecoveryBoundaries(unittest.TestCase):
    def test_missing_kernel_bundle_never_loads_any_module(self):
        engine=cas.OpenCasCache.__new__(cas.OpenCasCache)
        engine.run=Mock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(cas,"ASSETS",Path(tmp)):
            with self.assertRaisesRegex(RuntimeError,"unavailable for this SteamOS kernel"):
                engine.load_modules()
        engine.run.assert_not_called()

    def test_boot_module_failure_restores_native_library(self):
        lib={"id":"library","path":"/run/media/deck/games"}
        manager=service.Manager.__new__(service.Manager)
        manager.config={"cache":{"uuid":"ssd"},"libraries":[lib]}
        manager.ensure_cache=Mock()
        manager.activate=Mock(side_effect=RuntimeError("missing kernel module"))
        manager.block=Mock()
        manager.block.table.return_value={}
        manager.block.origin.return_value="/dev/library-partition"
        with patch.object(service,"mounts",return_value={}), patch.object(service,"save_json"):
            manager.reconcile()
        manager.block.mount_original.assert_called_once_with(lib,"/dev/library-partition")
        self.assertIn("missing kernel module",manager.errors["library"])

class ClearCacheBoundaries(unittest.TestCase):
    def manager(self):
        manager = service.Manager.__new__(service.Manager)
        manager.config = {"cache": {"uuid": "selected-ssd"},
                          "libraries": [{"id": "one"}, {"id": "two"}]}
        manager.block = Mock(spec=cas.OpenCasCache)
        manager.active = Mock(return_value=True)
        manager.block.verify.return_value = {"dirty": 0}
        return manager

    def test_confirmation_and_disk_identity_checked_before_mutation(self):
        manager = self.manager()
        for payload in ({}, {"confirmed": True, "cache_uuid": "different-ssd"}):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                manager.clear_cache(payload)
        manager.block.clear.assert_not_called()
        manager.block.verify.assert_not_called()

    def test_unhealthy_second_library_does_not_clear_first(self):
        manager = self.manager()
        manager.block.verify.side_effect = [{"dirty": 0}, {"dirty": 4096}]
        with self.assertRaisesRegex(RuntimeError, "pending writes"):
            manager.clear_cache({"confirmed": True, "cache_uuid": "selected-ssd"})
        manager.block.clear.assert_not_called()

    def test_partial_failure_is_not_reported_as_complete(self):
        manager = self.manager()
        manager.block.clear.side_effect = [None, RuntimeError("purge failed")]
        with self.assertRaisesRegex(RuntimeError, "Cleared 1 of 2"):
            manager.clear_cache({"confirmed": True, "cache_uuid": "selected-ssd"})
        self.assertEqual(manager.block.clear.call_count, 2)

if __name__=="__main__":unittest.main()
