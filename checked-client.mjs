// A research integration for the public custom-client option of @anywalletkit/wallet-zcash.
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

// For the research replay and local Node applications. A production library can compute
// the fee in-process. No shell or wallet credentials participate in this read.
const run = promisify(execFile);
export function localFeeLookup(api, python = 'python3') {
  const script = fileURLToPath(new URL('./fee_receipt.py', import.meta.url));
  return async txid => {
    const {stdout} = await run(python, [script, api, txid], {timeout: 70000});
    const result = JSON.parse(stdout);
    if (result.status !== 'CALCULATED') throw new Error('Fee calculation unavailable');
    return result;
  };
}

export function checkedClient(BlockbookClient, provider, getCheckedReceipt, transport = globalThis.fetch) {
  // The SDK drops blockHash when it converts transaction details to receipt information.
  // Compare the original block while the hash is still present, then let the SDK map it.
  class ReceiptDetailsClient extends BlockbookClient {
    async getTransactionDetails(id) {
      const original = await super.getTransactionDetails(id);
      if (!original || original.blockHeight <= 0) return original;
      const checked = await getCheckedReceipt(id);
      if (original.txid !== id || checked.txid !== id || checked.height !== original.blockHeight ||
          !/^[0-9a-f]{64}$/.test(original.blockHash) || original.blockHash !== checked.block_hash ||
          typeof checked.fee_zat !== 'string' || !/^[0-9]+$/.test(checked.fee_zat)) {
        throw new Error('Inconsistent confirmed fee receipt');
      }
      return {...original, fees: checked.fee_zat};
    }
  }
  const receipts = new ReceiptDetailsClient(provider, transport);
  class CheckedReceiptClient extends BlockbookClient {
    getTransactionInfo(txid) {
      return receipts.getTransactionInfo(txid.toLowerCase());
    }
  }
  return new CheckedReceiptClient(provider, transport);
}
