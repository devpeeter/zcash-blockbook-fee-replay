import gzip
import json
import unittest
from decimal import Decimal
from pathlib import Path

from block_integrity import check_native_header, transaction_root
from fee_receipt import get_receipt
from transaction_bytes import check_transaction

ROOT = Path(__file__).resolve().parent
OVERSTATED = "72dec0378794ece65acff91a05355eb543eeb8dc19c90441ae8b64690aab11c2"


def load(path):
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    return json.loads(data, parse_float=Decimal)


class ReceiptChecks(unittest.TestCase):
    def setUp(self):
        self.raw = load(ROOT / "receipts" / (OVERSTATED + "-tx-specific.json.gz"))
        self.tx = load(ROOT / "receipts" / (OVERSTATED + "-tx.json.gz"))
        self.index = load(ROOT / "receipts" / "3584390-index.json")
        self.routes = {"tx/" + OVERSTATED: self.tx, "tx-specific/" + OVERSTATED: self.raw,
                       "block-index/3584390": self.index}

    def fee(self):
        return get_receipt(self.routes.__getitem__, OVERSTATED)["fees"]

    def test_recorded_fee(self):
        self.assertEqual(self.fee(), "15000")

    def test_omitted_active_ironwood(self):
        del self.raw["ironwood"]
        with self.assertRaisesRegex(ValueError, "ironwood bundle"):
            self.fee()

    def test_incorrect_signed_balance(self):
        self.raw["ironwood"]["valueBalanceZat"] += 1
        with self.assertRaisesRegex(ValueError, "ironwood value balance"):
            self.fee()

    def test_truncated_wire(self):
        self.raw["hex"] = self.raw["hex"][:-2]
        self.raw["size"] -= 1
        with self.assertRaisesRegex(ValueError, "Truncated"):
            self.fee()

    def test_actually_empty_ironwood(self):
        block = load(ROOT / "captures" / "zebra" / "3584406.json.gz")["result"]
        tx = next(t for t in block["tx"] if t["txid"] ==
                  "37edbe73354bcdec64383cdf5157bd0b09d61fa9dc6132c0112b61cecac521f6")
        self.assertEqual(tx["version"], 6)
        self.assertNotIn("ironwood", tx)
        check_transaction(tx)

    def test_inconsistent_spent_output_amount(self):
        self.tx["vin"][0]["value"] = str(int(self.tx["vin"][0]["value"]) + 1)
        with self.assertRaisesRegex(ValueError, "transparent input total"):
            self.fee()

    def test_changed_active_block(self):
        self.index["blockHash"] = "ab" * 32
        with self.assertRaisesRegex(ValueError, "no longer active"):
            self.fee()

    def test_unconfirmed(self):
        self.tx["confirmations"] = 0
        with self.assertRaisesRegex(ValueError, "Confirmed"):
            self.fee()

    def test_unknown_version(self):
        self.raw["version"] = 7
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.fee()

    def test_wrong_merkle_root(self):
        block = load(ROOT / "captures" / "zebra" / "3584390.json.gz")["result"]
        txids = [t["txid"] for t in block["tx"]]
        txids[1], txids[2] = txids[2], txids[1]
        with self.assertRaisesRegex(ValueError, "Merkle root"):
            check_native_header(block, transaction_root(txids))

    def test_wrong_block_header(self):
        block = load(ROOT / "captures" / "zebra" / "3584390.json.gz")["result"]
        block["time"] += 1
        with self.assertRaisesRegex(ValueError, "header hash"):
            check_native_header(block, block["merkleroot"])


if __name__ == "__main__":
    unittest.main()
