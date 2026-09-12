function requireAdmin(request, env) {
  const auth = request.headers.get('Authorization') || '';
  const token = auth.replace('Bearer ', '').trim();
  return token && token === env.ADMIN_TOKEN;
}
async function getClients(env) {
  const raw = await env.Ashishkv.get('clients');
  return raw ? JSON.parse(raw) : [];
}
async function saveClients(env, clients) {
  await env.Ashishkv.put('clients', JSON.stringify(clients));
}

// GET /api/admin/clients -> full list (admin only)
export async function onRequestGet({ request, env }) {
  if (!requireAdmin(request, env)) return Response.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  const clients = await getClients(env);
  return Response.json({ ok: true, clients });
}

// POST /api/admin/clients -> create a client (admin only)
export async function onRequestPost({ request, env }) {
  if (!requireAdmin(request, env)) return Response.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  const body = await request.json().catch(() => null);
  if (!body || !body.name || !body.token) {
    return Response.json({ ok: false, error: 'name and token required' }, { status: 400 });
  }
  const clients = await getClients(env);
  if (clients.some(c => c.token === body.token)) {
    return Response.json({ ok: false, error: 'Token already in use' }, { status: 409 });
  }
  const client = {
    id: 'c_' + Date.now(), token: body.token, name: body.name, greet: body.greet || 'Hello',
    videos: [], advance: 0, messages: [], views: 0, uniques: 0
  };
  clients.push(client);
  await saveClients(env, clients);
  return Response.json({ ok: true, client });
}
