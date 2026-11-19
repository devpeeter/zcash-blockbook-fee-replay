"""Compare the fee-relevant decoded fields with a serialized v4, v5 or v6 transaction.

These checks validate the data shape used in this replay. They do not verify
signatures, shielded proofs, modern transaction IDs or spent output values.
"""

from hashlib import sha256


class Reader:
    def __init__(self, data):
        self.data = memoryview(data)
        self.offset = 0

    def take(self, length):
        end = self.offset + length
        if end > len(self.data):
            raise ValueError("Truncated transaction bytes")
        result = self.data[self.offset:end]
        self.offset = end
        return result

    def integer(self, size, signed=False):
        return int.from_bytes(self.take(size), "little", signed=signed)

    def count(self):
        tag = self.integer(1)
        if tag < 253:
            return tag
        size, minimum = {253: (2, 253), 254: (4, 65536), 255: (8, 1 << 32)}[tag]
        value = self.integer(size)
        if value < minimum:
            raise ValueError("Non-canonical CompactSize")
        return value


def same(actual, expected, field):
    if type(actual) is not type(expected) or actual != expected:
        raise ValueError(f"Serialized transaction disagrees with {field}")


def transparent(reader, raw):
    same(reader.count(), len(raw["vin"]), "transparent input count")
    for vin in raw["vin"]:
        prev = bytes(reader.take(32))[::-1].hex()
        index = reader.integer(4)
        script = reader.take(reader.count())
        reader.take(4)  # Sequence.
        if "coinbase" in vin:
            same((prev, index), ("0" * 64, 0xffffffff), "coinbase outpoint")
            same(script.hex(), vin["coinbase"].lower(), "coinbase script")
        else:
            same(prev, vin["txid"], "previous transaction")
            same(index, vin["vout"], "previous output index")

    same(reader.count(), len(raw["vout"]), "transparent output count")
    for index, vout in enumerate(raw["vout"]):
        same(index, vout["n"], "transparent output index")
        value = reader.integer(8, signed=True)
        same(value, vout.get("valueZat", vout.get("valueSat")), "transparent output amount")
        script = reader.take(reader.count())
        same(script.hex(), vout["scriptPubKey"]["hex"].lower(), "transparent output script")


def modern_sapling(reader, raw):
    spends = reader.count()
    same(spends, len(raw["vShieldedSpend"]), "Sapling spends")
    reader.take(96 * spends)
    outputs = reader.count()
    same(outputs, len(raw["vShieldedOutput"]), "Sapling outputs")
    reader.take(756 * outputs)
    balance = reader.integer(8, signed=True) if spends or outputs else 0
    same(balance, raw["valueBalanceZat"], "Sapling value balance")
    if spends:
        reader.take(32)  # Shared anchor.
    reader.take((192 + 64) * spends + 192 * outputs)
    if spends or outputs:
        reader.take(64)  # Binding signature.


def action_pool(reader, raw, name, encoded):
    actions = reader.count() if encoded else 0
    # Zebra omits an empty Ironwood object. Only bytes can distinguish an
    # empty bundle from an incomplete JSON response for an active one.
    if name not in raw:
        same(actions, 0, name + " bundle")
        return
    pool = raw[name]
    same(actions, len(pool["actions"]), name + " actions")
    balance = 0
    if actions:
        reader.take(820 * actions + 1)  # Actions and flags.
        balance = reader.integer(8, signed=True)
        reader.take(32)  # Anchor.
        reader.take(reader.count())  # Length-prefixed proof.
        reader.take(64 * actions + 64)  # Spend authorizations and binding signature.
    same(balance, pool["valueBalanceZat"], name + " value balance")


def legacy_shielded(reader, raw):
    reader.take(8)  # Lock time and expiry height follow transparent fields for v4.
    same(reader.integer(8, signed=True), raw["valueBalanceZat"], "Sapling value balance")
    spends = reader.count()
    same(spends, len(raw["vShieldedSpend"]), "Sapling spends")
    reader.take(384 * spends)
    outputs = reader.count()
    same(outputs, len(raw["vShieldedOutput"]), "Sapling outputs")
    reader.take(948 * outputs)
    joins = reader.count()
    same(joins, len(raw["vjoinsplit"]), "Sprout JoinSplits")
    for joinsplit in raw["vjoinsplit"]:
        same(reader.integer(8), joinsplit["vpub_oldZat"], "Sprout public input")
        same(reader.integer(8), joinsplit["vpub_newZat"], "Sprout public output")
        reader.take(1698 - 16)  # Rest of the Groth16 JoinSplit description.
    if joins:
        reader.take(32 + 64)  # JoinSplit public key and signature.
    if spends or outputs:
        reader.take(64)  # Sapling binding signature.


def check_transaction(raw):
    version = raw["version"]
    groups = {4: 0x892f2085, 5: 0x26a7270a, 6: 0xd884b698}
    if type(version) is not int or version not in groups:
        raise ValueError("Unsupported transaction version")
    data = bytes.fromhex(raw["hex"])
    same(len(data), raw["size"], "transaction size")
    reader = Reader(data)
    same(reader.integer(4), 0x80000000 | version, "transaction version")
    same(reader.integer(4), groups[version], "version group")
    if version >= 5:
        reader.take(12)  # Branch ID, lock time and expiry height.
    transparent(reader, raw)
    if version == 4:
        txid = sha256(sha256(data).digest()).digest()[::-1].hex()
        same(txid, raw["txid"], "v4 transaction ID")
        legacy_shielded(reader, raw)
    else:
        same(raw["vjoinsplit"], [], "Sprout JoinSplits")
        modern_sapling(reader, raw)
    action_pool(reader, raw, "orchard", encoded=version >= 5)
    action_pool(reader, raw, "ironwood", encoded=version == 6)
    same(reader.offset, len(data), "transaction length")
