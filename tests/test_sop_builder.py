import tempfile
import unittest
from pathlib import Path


class TestSopBuilder(unittest.TestCase):
    def setUp(self):
        # Patch backend.data_store module-level paths to a temp dir
        from backend import data_store

        self._data_store = data_store
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)

        data_store.DATA_DIR = base / "data"
        data_store.CHECK_IDS_PATH = data_store.DATA_DIR / "check_ids.yaml"
        data_store.SOPS_DIR = data_store.DATA_DIR / "sops"

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_and_list_sop_global(self):
        ds = self._data_store
        ds.save_sop("my_sop", {"title": "T", "created_at": "now", "version": 1, "states": []})
        sops = ds.list_all_sops()
        ids = [sid for sid, _ in sops]
        self.assertIn("my_sop", ids)
        loaded = ds.load_sop("my_sop")
        self.assertEqual(loaded.get("title"), "T")

    def test_validation_allows_forward_refs_on_add_state(self):
        from backend import validation

        errors = validation.validate_new_state(
            sop_states=[{"state_id": "A", "is_start": True}],
            state_id="B",
            is_start=False,
            is_end=False,
            next_state_ids=["C"],  # forward reference
            has_existing_start=True,
        )
        self.assertEqual(errors, [])

    def test_finalize_requires_next_state_ids_exist(self):
        from backend import validation

        sop = {
            "states": [
                {"state_id": "A", "is_start": True, "is_end": False, "next_state_ids": ["B"]},
                # Missing B
                {"state_id": "END", "is_start": False, "is_end": True, "next_state_ids": []},
            ]
        }
        errors = validation.validate_sop_final(sop)
        self.assertTrue(any("does not exist" in e for e in errors))


if __name__ == "__main__":
    unittest.main()

