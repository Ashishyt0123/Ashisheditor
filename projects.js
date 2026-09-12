// GET  /api/projects        -> { ok:true, projects:[...] }  (public)
// POST /api/projects        -> create a project              (admin only)
// Requires KV binding named Ashishkv and env var ADMIN_TOKEN.

async function getProjects(env) {
  const raw = await env.Ashishkv.get('projects');
  return raw ? JSON.parse(raw) : [];
}
async function saveProjects(env, projects) {
  await env.Ashishkv.put('projects', JSON.stringify(projects));
}
function requireAdmin(request, env) {
  const auth = request.headers.get('Authorization') || '';
  const token = auth.replace('Bearer ', '').trim();
  return token && token === env.ADMIN_TOKEN;
}

export async function onRequestGet({ env }) {
  const projects = await getProjects(env);
  return Response.json({ ok: true, projects });
}

export async function onRequestPost({ request, env }) {
  if (!requireAdmin(request, env)) {
    return Response.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  const body = await request.json().catch(() => null);
  if (!body || !body.title || !body.video) {
    return Response.json({ ok: false, error: 'title and video are required' }, { status: 400 });
  }
  const projects = await getProjects(env);
  const project = {
    id: 'proj_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7),
    title: body.title,
    description: body.description || '',
    thumbnail: body.thumbnail || '',
    video: body.video,
    category: body.category || 'Video Editing',
    date: body.date || new Date().toISOString().slice(0, 10),
    featured: !!body.featured,
    order: body.order ?? (projects.length + 1)
  };
  projects.push(project);
  await saveProjects(env, projects);
  return Response.json({ ok: true, project });
}
