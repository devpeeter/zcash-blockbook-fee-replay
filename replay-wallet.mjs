// Serve byte-for-byte recorded provider replies on localhost and run the published wallet.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { gunzipSync } from 'node:zlib';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const folder = path.dirname(fileURLToPath(import.meta.url));
const run = promisify(execFile);
const cases = [
  [3584389, 'aac3fa0faf4804c62fc21cdd798b4ad992d981d003a2cdf74ec51599720da90e'],
  [3584390, '72dec0378794ece65acff91a05355eb543eeb8dc19c90441ae8b64690aab11c2'],
  [2726407, '63679fc7f9628bc5065636813ee6adbe89f6dfdf3635524ac0792b344a9fd588'],
];
const routes = new Map();
for (const [height, txid] of cases) {
  for (const route of ['tx', 'tx-specific']) {
    const bytes = await readFile(path.join(folder,'receipts',txid+'-'+route+'.json.gz'));
    routes.set('/api/v2/'+route+'/'+txid, gunzipSync(bytes));
  }
  routes.set('/api/v2/block-index/'+height, await readFile(path.join(folder,'receipts',height+'-index.json')));
}
const server = createServer((req,res) => {
  const reply = req.method === 'GET' && routes.get(req.url);
  res.writeHead(reply ? 200 : 404, {'Content-Type':'application/json'});
  res.end(reply || '{}');
});
await new Promise((resolve,reject) => {
  server.once('error',reject);
  server.listen(0,'127.0.0.1',resolve);
});
try {
  for (const [height, txid] of cases) {
    const env = {...process.env,
      BLOCKBOOK_API_V2:'http://127.0.0.1:'+server.address().port+'/api/v2',
      ZEBRA_BLOCK_FILE:height === 2726407 ? path.join(folder, 'historical-zebra.json.gz') :
        path.join(folder,'captures','zebra',height+'.json.gz'),
    };
    const {stdout} = await run(process.execPath,[path.join(folder,'wallet-live.mjs'),txid],{env});
    const result = JSON.parse(stdout);
    if (result.status !== 'PASS') throw new Error('Receipt replay failed');
    console.log(JSON.stringify({scope:'archived provider responses and released SDK',
      txid:result.txid, original_zat:result.stock_wallet_zat, corrected_zat:result.corrected_wallet_zat,
      reference_zat:result.independent_zebra_zat,status:result.status}));
  }
} finally {
  await new Promise(resolve => server.close(resolve));
}
