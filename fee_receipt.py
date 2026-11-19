"""Read a confirmed Zcash fee using one operator's two Blockbook views and height index."""

import argparse
import json
import re
import sys
from decimal import Decimal
from urllib.error import URLError
from urllib.request import Request, urlopen
from transaction_bytes import check_transaction


class Unverified(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Unverified(message)


def amount(value, signed=False):
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
        value = int(value)
    require(type(value) is int and (signed or value >= 0), "Missing or invalid integer amount")
    return value


def output_zat(raw):
    for key in ("valueZat", "valueSat"):
        if key in raw:
            return amount(raw[key])
    raise Unverified("Missing output amount in zatoshis")


def get_receipt(lookup, txid):
    require(isinstance(txid, str) and re.fullmatch(r"[0-9a-fA-F]{64}", txid), "Invalid txid")
    txid = txid.lower()
    normalized = lookup("tx/" + txid)
    raw = lookup("tx-specific/" + txid)
    require(normalized["txid"] == raw["txid"] == txid, "Transaction ID mismatch")
    height = normalized["blockHeight"]
    confirmations = normalized["confirmations"]
    require(type(height) is int and height > 0 and type(confirmations) is int and confirmations > 0,
            "Confirmed non-genesis transaction required")
    block = normalized["blockHash"]
    require(isinstance(block, str) and re.fullmatch(r"[0-9a-f]{64}", block)
            and raw["blockhash"] == block, "Block hash mismatch")
    require(raw.get("height", height) == height and raw.get("in_active_chain", True) is True,
            "Native transaction is outside the selected chain")
    check_transaction(raw)
    if normalized.get("hex"):
        require(normalized["hex"].lower() == raw["hex"].lower(), "Transaction bytes differ across views")
    require(lookup("block-index/" + str(height))["blockHash"] == block, "Block is no longer active")
    coinbase = len(raw["vin"]) == 1 and "coinbase" in raw["vin"][0]
    if coinbase:
        return {**normalized, "fees": "0"}
    inputs, outputs = normalized["vin"], normalized["vout"]
    require(len(raw["vin"]) == len(inputs) and len(raw["vout"]) == len(outputs),
            "Transparent entry count mismatch")
    spent = set()
    total_in = 0
    for view, native in zip(inputs, raw["vin"]):
        outpoint = (native["txid"], native["vout"])
        # Blockbook omits the output index when it is zero.
        require((view["txid"], view.get("vout", 0)) == outpoint and outpoint not in spent,
                "Transparent previous output mismatch")
        spent.add(outpoint)
        total_in += amount(view["value"])
    total_out = 0
    for i, (view, native) in enumerate(zip(outputs, raw["vout"])):
        value = output_zat(native)
        require(native["n"] == view["n"] == i and amount(view["value"]) == value,
                "Transparent output mismatch")
        total_out += value
    if "valueIn" in normalized:
        require(amount(normalized["valueIn"]) == total_in, "Inconsistent transparent input total")
    if "value" in normalized:
        require(amount(normalized["value"]) == total_out, "Inconsistent transparent output total")
    sprout = sum(amount(js["vpub_newZat"]) - amount(js["vpub_oldZat"]) for js in raw["vjoinsplit"])
    sapling = amount(raw["valueBalanceZat"], signed=True)
    orchard = amount(raw["orchard"]["valueBalanceZat"], signed=True) if "orchard" in raw else 0
    # The serialized action counts and signed pool balances have already been checked.
    ironwood = amount(raw["ironwood"]["valueBalanceZat"], signed=True) if "ironwood" in raw else 0
    fee = total_in - total_out + sprout + sapling + orchard + ironwood
    require(fee >= 0, "Incomplete or inconsistent value balance")
    return {**normalized, "fees": str(fee)}


def http_lookup(base):
    base = base.rstrip("/")
    require(base.startswith(("http://", "https://")), "Expected an HTTP(S) /api/v2 base URL")

    def lookup(route):
        req = Request(base + ("/" + route if route else ""), headers={"Accept": "application/json"})
        with urlopen(req, timeout=20) as response:
            return json.load(response, parse_float=Decimal)
    return lookup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("api", help="operator's /api/v2 base URL")
    parser.add_argument("txid")
    args = parser.parse_args()
    try:
        row = get_receipt(http_lookup(args.api), args.txid)
        print(json.dumps({"status": "CALCULATED", "txid": row["txid"], "height": row["blockHeight"],
                          "block_hash": row["blockHash"], "fee_zat": row["fees"]}))
    except (Unverified, URLError, OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print(json.dumps({"status": "UNVERIFIED", "reason": str(error)}))
        sys.exit(1)
