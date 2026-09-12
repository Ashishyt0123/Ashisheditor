// DELETE /api/projects/:id  -> delete a project (admin only)
function requireAdmin(request, env) {
  const auth = request.headers.get('Authorization') || '';
  const token = auth.replace('Bearer ', '').trim();
  return token && token === env.ADMIN_TOKEN;
}

export async function onRequestDelete({ request, env, params }) {
  if (!requireAdmin(request, env)) {
    return Response.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  const raw = await env.Ashishkv.get('projects');
  let projects = raw ? JSON.parse(raw) : [];
  const before = projects.length;
  projects = projects.filter(p => p.id !== params.id);
  if (projects.length === before) {
    return Response.json({ ok: false, error: 'Not found' }, { status: 404 });
  }
  await env.Ashishkv.put('projects', JSON.stringify(projects));
  return Response.json({ ok: true });
}
