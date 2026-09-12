// POST /api/client/:token/message -> append a message from this client.
export async function onRequestPost({ request, env, params }) {
  const raw = await env.Ashishkv.get('clients');
  const clients = raw ? JSON.parse(raw) : [];
  const client = clients.find(c => c.token === params.token);
  if (!client) return Response.json({ ok: false, error: 'Invalid link' }, { status: 404 });

  const body = await request.json().catch(() => null);
  if (!body || !body.text) return Response.json({ ok: false, error: 'text required' }, { status: 400 });

  client.messages = client.messages || [];
  client.messages.push({ from: 'client', text: String(body.text).slice(0, 2000), ts: body.ts || Date.now() });
  await env.Ashishkv.put('clients', JSON.stringify(clients));
  return Response.json({ ok: true });
}
