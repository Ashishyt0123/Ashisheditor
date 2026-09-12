// GET /api/client/:token -> returns ONLY that one client's data.
// This is the security boundary: the full client list lives only in KV
// server-side and is never sent to the browser — only the single record
// whose token matches the URL is returned.

export async function onRequestGet({ env, params }) {
  const raw = await env.Ashishkv.get('clients');
  const clients = raw ? JSON.parse(raw) : [];
  const client = clients.find(c => c.token === params.token);
  if (!client) {
    return Response.json({ ok: false, error: 'Invalid link' }, { status: 404 });
  }
  const paymentsRaw = await env.Ashishkv.get('payments');
  const allPayments = paymentsRaw ? JSON.parse(paymentsRaw) : [];
  const payments = allPayments.filter(p => p.clientId === client.id);
  return Response.json({ ok: true, client, payments });
}
