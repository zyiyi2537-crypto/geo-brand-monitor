import { webcrypto } from 'node:crypto';
if (!globalThis.crypto) globalThis.crypto = webcrypto;

import { MoltsPayServer } from 'moltspay/server';

const server = new MoltsPayServer('./moltspay.services.json');

async function handlePurchase(params) {
  const { user_id, membership_slug } = params;

  const res = await fetch('http://127.0.0.1:8070/api/payment/moltspay/fulfill', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: Number(user_id), membership_slug }),
  });

  if (!res.ok) {
    const err = await res.text();
    return { success: false, error: err };
  }

  const data = await res.json();
  return { success: true, payment_id: String(data.payment_id) };
}

server.skill('membership-detector', handlePurchase);
server.skill('membership-starter', handlePurchase);
server.skill('membership-growth', handlePurchase);

server.listen(3010);
console.log('MoltsPayServer listening on :3010');
