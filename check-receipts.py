"""Replay two November 17 receipts and the separate 2024 historical control against a second explorer."""
import gzip
import json
from decimal import Decimal
from pathlib import Path
from fee_receipt import get_receipt, amount, require

folder = Path(__file__).resolve().parent / "receipts"
cases = [
    (3584389, "aac3fa0faf4804c62fc21cdd798b4ad992d981d003a2cdf74ec51599720da90e", "November 17"),
    (3584390, "72dec0378794ece65acff91a05355eb543eeb8dc19c90441ae8b64690aab11c2", "November 17"),
    (2726407, "63679fc7f9628bc5065636813ee6adbe89f6dfdf3635524ac0792b344a9fd588", "2024 historical control"),
]

def read(path):
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    return json.loads(data, parse_float=Decimal)

def check(height, txid, label):
    name = "historical-independent-explorer" if label.startswith("2024") else txid + "-independent-explorer"
    source = read(folder / (name + ".json.gz"))["data"]
    record = read(folder / (txid + "-tx.json.gz"))
    raw = read(folder / (txid + "-tx-specific.json.gz"))
    active = read(folder / (str(height) + "-index.json"))
    require(source["txid"] == record["txid"] == txid and int(source["blockHeight"]) == record["blockHeight"] == height,
            "Source transaction or height mismatch")
    require(source["blockHash"] == record["blockHash"] == active["blockHash"] and source["isCanonical"] is True,
            "Cross-provider block mismatch")
    routes = {"tx/" + txid: record, "tx-specific/" + txid: raw, "block-index/" + str(height): active}
    baseline = amount(record["fees"])
    corrected = amount(get_receipt(routes.__getitem__, txid)["fees"])
    independent = amount(source["feeZat"])
    require(independent == Decimal(source["fee"]) * 100_000_000, "Explorer fee has inconsistent units")
    require(baseline != independent == corrected, "Expected corrected receipt to match the independent explorer")
    return {"label": label, "txid": txid, "height": height, "hash": active["blockHash"],
            "blockbook_zat": baseline, "corrected_zat": corrected, "independent_zecblock_zat": independent,
            "status": "PASS"}

if __name__ == "__main__":
    print(json.dumps([check(*case) for case in cases], indent=2))
