// Run the published watch-only account twice for the same confirmed Zcash transaction.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { WalletAccountReadOnlyZcash, ZcashBlockbookClient } from '@anywalletkit/wallet-zcash';
import { checkedClient, localFeeLookup } from './checked-client.mjs';

const run = promisify(execFile);
const pkg = createRequire(import.meta.url)('@anywalletkit/wallet-zcash/package.json');
const api = (process.env.BLOCKBOOK_API_V2 || 'https://docs-demo.zec-mainnet.quiknode.pro/api/v2').replace(/\/+$/, '');
const rpc = process.env.ZEBRA_RPC_URL || 'https://zcash-mainnet-zebrad.gateway.tatum.io';
const txid = process.argv[2] || 'aac3fa0faf4804c62fc21cdd798b4ad992d981d003a2cdf74ec51599720da90e';
const python = process.env.PYTHON || 'python3';

async function main() {
  if (!/^[a-f0-9]{64}$/.test(txid) || !api.endsWith('/api/v2'))
    throw new Error('Supply a transaction ID and a Blockbook /api/v2 base');
  const script = fileURLToPath(new URL('./reference.py', import.meta.url));
  const args = [script, api, rpc, txid];
  if (process.env.ZEBRA_BLOCK_FILE) args.push('--captured-block', process.env.ZEBRA_BLOCK_FILE);
  const { stdout } = await run(python, args, {timeout: 115000});
  const ref = JSON.parse(stdout);
  const config = {url: api.slice(0, -'/api/v2'.length)};
  const plainWallet = new WalletAccountReadOnlyZcash(ref.address, {
    client: {type: 'blockbook-http', clientConfig: config},
  });
  const fixedWallet = new WalletAccountReadOnlyZcash(ref.address, {
    client: checkedClient(ZcashBlockbookClient, config, localFeeLookup(api, python)),
  });
  const oldReceipt = await plainWallet.getTransactionReceipt(txid);
  const fixedReceipt = await fixedWallet.getTransactionReceipt(txid);
  if (![oldReceipt, fixedReceipt].every(r => r && r.hash === txid && r.blockNumber === BigInt(ref.height) &&
        r.fee !== undefined && r.confirmations > 0 && r.status === 1))
    throw new Error('Confirmed wallet receipt identity or fee missing');
  const currentBlock = await fetch(api+'/block-index/'+ref.height,{signal:AbortSignal.timeout(20000)});
  if (!currentBlock.ok || (await currentBlock.json()).blockHash !== ref.block_hash)
    throw new Error('Blockbook active block changed during wallet test');
  const original = String(oldReceipt.fee);
  const corrected = String(fixedReceipt.fee);
  const status = original !== ref.blockbook_zat || corrected !== ref.independent_zat ? 'FAIL'
    : original === ref.independent_zat ? 'NO_DISCREPANCY' : 'PASS';
  const result = {status, recorded_utc: new Date().toISOString(), package: pkg.name, version: pkg.version,
    method: 'WalletAccountReadOnlyZcash.getTransactionReceipt', reference_source: ref.reference_source,
    txid, height: ref.height, block_hash: ref.block_hash,
    blockbook_zat: ref.blockbook_zat, stock_wallet_zat: original, corrected_wallet_zat: corrected,
    independent_zebra_zat: ref.independent_zat,
    confirmations: {stock:oldReceipt.confirmations, corrected:fixedReceipt.confirmations}};
  console.log(JSON.stringify(result,null,2));
  if (status !== 'PASS') process.exitCode = 1;
}
main().catch(error => {
  const details = error.stdout?.toString().trim();
  console.log(JSON.stringify({status:'UNAVAILABLE', reason:details || error.message}));
  process.exitCode = 1;
});
