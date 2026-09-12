// POST /api/client/:token/payment -> submit a payment (with optional screenshot) for review.
// The screenshot is stored under its own KV key (shot:<paymentId>) so the shared
// "payments" list stays small even as full-quality, uncompressed screenshots pile up.
export async function onRequestPost({ request, env, params }) {
  const clientsRaw = await env.Ashishkv.get('clients');
  const clients = clientsRaw ? JSON.parse(clientsRaw) : [];
  const client = clients.find(c => c.token === params.token);
  if (!client) return Response.json({ ok: false, error: 'Invalid link' }, { status: 404 });

  const body = await request.json().catch(() => null);
  if (!body || !body.amount) return Response.json({ ok: false, error: 'amount required' }, { status: 400 });

  const id = body.id || ('pay_' + Date.now());
  if (body.screenshot) {
    await env.Ashishkv.put('shot:' + id, body.screenshot); // full quality, no compression
  }

  const paymentsRaw = await env.Ashishkv.get('payments');
  const payments = paymentsRaw ? JSON.parse(paymentsRaw) : [];
  payments.push({
    id, clientId: client.id, clientName: client.name, videoId: body.videoId || null,
    amount: Number(body.amount), note: body.note || '', status: 'pending',
    ts: body.ts || Date.now(), hasShot: !!body.screenshot
  });
  await env.Ashishkv.put('payments', JSON.stringify(payments));
  return Response.json({ ok: true });
}
