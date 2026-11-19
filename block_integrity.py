"""Check the transaction Merkle root and serialized header of the archived Zcash blocks."""

import hashlib
import struct


def double_sha256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def transaction_root(txids):
    if not txids:
        raise ValueError("Empty block transaction list")
    layer = [bytes.fromhex(txid)[::-1] for txid in txids]
    if any(len(txid) != 32 for txid in layer):
        raise ValueError("Invalid transaction ID length")
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [double_sha256(layer[i] + layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0][::-1].hex()


def check_native_header(block, expected_root):
    if block["merkleroot"] != expected_root or block["nTx"] != len(block["tx"]):
        raise ValueError("Native block transaction list disagrees with its Merkle root or count")
    fields = [bytes.fromhex(block[k])[::-1] for k in ("previousblockhash", "merkleroot", "blockcommitments")]
    nonce = bytes.fromhex(block["nonce"])[::-1]
    solution = bytes.fromhex(block["solution"])
    # This replay targets the standard 1,344-byte mainnet Equihash solution.
    if any(len(field) != 32 for field in [*fields, nonce]) or len(solution) != 1344:
        raise ValueError("Unsupported block header shape")
    header = b"".join([
        struct.pack("<I", block["version"]), *fields,
        struct.pack("<II", block["time"], int(block["bits"], 16)), nonce,
        b"\xfd" + struct.pack("<H", len(solution)), solution,
    ])
    if double_sha256(header)[::-1].hex() != block["hash"]:
        raise ValueError("Serialized block header hash mismatch")
