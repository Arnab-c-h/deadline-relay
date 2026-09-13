import tempfile
import unittest
from pathlib import Path

from relay.store import Store


class StoreTests(unittest.TestCase):
    def test_documents_and_provider_records_survive_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite"
            store = Store(path)
            store.save("plans", "p1", {"id": "p1", "hash": "abc"})
            store.put_record({"key": "calendar:M2", "fields": {"start": "2026-09-25"}})
            reopened = Store(path)
            self.assertEqual(reopened.get("plans", "p1")["hash"], "abc")
            self.assertEqual(reopened.records()["calendar:M2"]["fields"]["start"], "2026-09-25")


if __name__ == "__main__":
    unittest.main()
