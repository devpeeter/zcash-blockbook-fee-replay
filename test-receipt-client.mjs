import assert from 'node:assert/strict';
import test from 'node:test';
import { ZcashBlockbookClient } from '@anywalletkit/wallet-zcash';
import { checkedClient } from './checked-client.mjs';

const id = '01'.repeat(32);
const block = '02'.repeat(32);
const provider = { url: 'http://localhost' };
const original = { txid: id, blockHeight: 20, confirmations: 4, blockHash: block, fees: '100000' };
const checked = { txid: id, height: 20, block_hash: block, fee_zat: '15000' };
const reply = tx => async () => Response.json(tx);

test('the confirmed fee goes through the published SDK conversion', async () => {
  const client = checkedClient(ZcashBlockbookClient, provider, async () => checked, reply(original));
  assert.equal((await client.getTransactionInfo(id)).fee, 15000n);
});

test('a different block at the same height fails the receipt', async () => {
  const otherBlock = { ...checked, block_hash: '03'.repeat(32) };
  const client = checkedClient(ZcashBlockbookClient, provider, async () => otherBlock, reply(original));
  await assert.rejects(client.getTransactionInfo(id), /Inconsistent confirmed fee/);
});

test('an unconfirmed receipt skips the confirmed-fee calculation', async () => {
  const pending = { ...original, blockHeight: -1, confirmations: 0 };
  const client = checkedClient(ZcashBlockbookClient, provider, assert.fail, reply(pending));
  assert.equal((await client.getTransactionInfo(id)).blockHeight, -1);
});

test('ordinary transaction detail reads keep the original provider fee', async () => {
  const client = checkedClient(ZcashBlockbookClient, provider, assert.fail, reply(original));
  assert.equal((await client.getTransactionDetails(id)).fees, original.fees);
});
