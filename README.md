# Zcash fees in confirmed Blockbook wallet receipts

This repository reproduces a fee display error in a Zcash Blockbook service and demonstrates a read-only correction through the published Any Wallet Kit wallet. The amount displayed on a receipt can differ from the network fee a transaction actually paid. All amounts in the replay output use integer zatoshis. One ZEC equals 100,000,000 zatoshis.

## Reproduce

In the directory containing this README, run the offline checks with Python 3.9 or later.

```sh
python3 verify.py
```

A successful run exits with code zero and prints `PASS`, 100 blocks, 102 non-coinbase transactions, 42 original fee discrepancies, 102 corrected matches and three explorer receipt checks. The command also runs the Python regression tests. For the full per-transaction comparison, run `python3 window.py`. The saved output is in `window-result.json`.

To run the three receipts through the released wallet SDK, install the pinned dependencies and run the Node checks. Use Node.js 22 or later and npm. The dependency installation needs network access. The two tests below it run locally.

```sh
npm ci --ignore-scripts --no-audit --no-fund
node --test test-receipt-client.mjs
node replay-wallet.mjs
```

The wallet replay serves recorded HTTP responses on loopback and calls `WalletAccountReadOnlyZcash.getTransactionReceipt` with each client. It prints one JSON result per transaction. No wallet keys or funds are needed.

## Results

The 100 consecutive Zcash mainnet blocks span heights 3,584,389 through 3,584,488. The blocks were mined on November 18, 2026 UTC, during the evening of November 17 in Toronto. QuickNode supplied the Blockbook fee fields and native transaction records. A separately hosted Zebra RPC service on Tatum supplied each reference fee. The block replay recomputes the transaction Merkle roots and encoded header hashes, checks continuity against the pinned end hash, and compares the complete transaction lists. The two native sources also returned identical serialized transactions in this window.

Of 102 non-coinbase transactions, Blockbook understated 29 fees and overstated 13. The corrected calculation matched the Zebra fee in all 102 cases. All 309 spent transparent outputs matched Zebra's outpoint and amount. These counts describe one provider over this specific window. Coinbase transactions are excluded from the comparison. Two transactions from the window and one historical control also have archived individual receipts from the ZecBlock explorer.

| Mainnet height | Stock SDK fee (ZEC) | Corrected SDK fee (ZEC) | Zebra fee (ZEC) |
| --- | ---: | ---: | ---: |
| 3,584,389 | 0 | 0.00015000 | 0.00015000 |
| 3,584,390 | 16.83176885 | 0.00015000 | 0.00015000 |
| 2,726,407 (2024 control) | 72.56179835 | 0.00155000 | 0.00155000 |

The three example IDs, block hashes and ZecBlock comparisons are in `three-receipts.json`. All three wallet cases also passed fresh live checks on November 18, 2026 against QuickNode and Tatum. The full results are in `wallet-live-result.json`, `wallet-overstated-result.json` and `historical-result.json`. Source endpoints and the pinned end hash are in `sources.json`. The historical transaction was reported publicly by Daira Hopwood. [Upstream issue](https://github.com/trezor/blockbook/issues/1160) · [QuickNode transaction API](https://www.quicknode.com/docs/zcash/api-v2-tx)

## Fee calculation and scope

For a non-coinbase transaction, the replay subtracts transparent outputs from the value of transparent inputs, adds each Sprout JoinSplit's `vpub_new - vpub_old`, and adds the signed Sapling, Orchard and Ironwood value balances for the pools present. The serialized transaction determines whether an optional pool is empty. A missing active bundle, inconsistent balance, changed block hash or unsupported transaction format makes the calculation fail. [Zcash protocol specification](https://zips.z.cash/protocol/protocol.pdf) · [Version 6 transaction encoding](https://zips.z.cash/zip-0229)

The prototype reads confirmed v4, v5 and v6 transaction shapes used by these providers. It compares decoded outpoints, output amounts and pool balances with the serialized bytes. Transparent input amounts come from the operator's resolved previous outputs. The two-provider fee comparison is a separate evidence check. A single live client still trusts its operator for those previous output values and active-chain information. This replay does not independently validate modern transaction IDs, shielded proofs or Zcash consensus.

The opt-in wallet integration runs in Node and invokes Python for the fee calculation. The evidence covers fee display in the pinned SDK, `@anywalletkit/wallet-zcash@0.5.4`. A production in-process client and adoption by any wallet team remain separate work.

## Live check

With the dependencies installed, the same wallet code can read an individual receipt from QuickNode and compare it with the live Tatum Zebra node.

```sh
node wallet-live.mjs 72dec0378794ece65acff91a05355eb543eeb8dc19c90441ae8b64690aab11c2
```

To collect the archived range again, use an empty directory.

```sh
python3 window.py --fetch --captures new-captures > new-window.json
```

Public endpoints can rate-limit requests. The offline checks work from the included responses. The live wallet command accepts a Blockbook `/api/v2` base in `BLOCKBOOK_API_V2` and a Zebra RPC URL in `ZEBRA_RPC_URL`. Each wallet result identifies whether the reference came from a saved RPC response or a live call.

The MIT license covers the original replay code. Captured responses identify their source, and npm dependencies retain their respective licenses.
