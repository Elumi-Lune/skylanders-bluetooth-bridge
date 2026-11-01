"""Offline regression of catalogue parsing and measured BLE packet handling."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from skylanders_catalogue import Catalogue, parse_readme
from skylanders_bridge_v1_2 import status_codes, query_block_one, parse_query_response

class CatalogueTests(unittest.TestCase):
    def test_parse_and_lookup(self):
        raw = "### Trap Team\nSkylander | CharacterID | VariantID\n--- | --- | ---\nJawbreaker | 470 | 12288\n"
        rows = parse_readme(raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(Catalogue({'entries': rows}).identify(470,12288)[0], 'Jawbreaker')
    def test_status(self):
        self.assertEqual(status_codes(bytes.fromhex('53 05 00 00 00'))[:3], [1,1,0])
    def test_q_is_read_only(self):
        self.assertEqual(query_block_one(0), bytes.fromhex('51 10 01')+bytes(17))
        sample = bytes.fromhex('51 10 01 d6 01 00 00 3d 2a 16 dd 8f de 00 00 00 30 af 9e 00')
        result = parse_query_response(sample,0)
        self.assertEqual((result.character_id, result.variant_id),(470,12288))
        with self.assertRaises(ValueError):
            parse_query_response(sample,1)

if __name__ == '__main__': unittest.main()
