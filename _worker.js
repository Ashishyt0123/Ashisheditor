// ============================================================
// SINGLE-FILE BACKEND — everything the 14 separate functions/ files did,
// combined into one worker so only 2 files need to be uploaded:
// this file (at the REPO ROOT, named exactly "_worker.js") and index.html.
//
// Needs these set on your Cloudflare Pages project:
//   Binding "Ashishkv"      -> your KV namespace ("Ashishdata")
//   Env var "ADMIN_TOKEN"   -> generated on first admin login (Profile tab)
//   Env var "B2_KEY_ID"
//   Env var "B2_APP_KEY"
//   Env var "B2_BUCKET_NAME" -> "ashish-editor-videos"
// ============================================================

function json(data, status = 200) {
  return Response.json(data, { status });
}
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
async function getPayments(env) {
  const raw = await env.Ashishkv.get('payments');
  return raw ? JSON.parse(raw) : [];
}
async function savePayments(env, payments) {
  await env.Ashishkv.put('payments', JSON.stringify(payments));
}
async function getProjects(env) {
  const raw = await env.Ashishkv.get('projects');
  return raw ? JSON.parse(raw) : [];
}
async function saveProjects(env, projects) {
  await env.Ashishkv.put('projects', JSON.stringify(projects));
}

// ---- Backblaze B2 ----
async function getUploadSlot(env) {
  const authRes = await fetch('https://api.backblazeb2.com/b2api/v2/b2_authorize_account', {
    headers: { Authorization: 'Basic ' + btoa(`${env.B2_KEY_ID}:${env.B2_APP_KEY}`) }
  });
  const auth = await authRes.json();
  if (!authRes.ok) throw new Error('B2 auth failed: ' + (auth.message || authRes.status));

  const listRes = await fetch(`${auth.apiUrl}/b2api/v2/b2_list_buckets`, {
    method: 'POST',
    headers: { Authorization: auth.authorizationToken, 'Content-Type': 'application/json' },
    body: JSON.stringify({ accountId: auth.accountId, bucketName: env.B2_BUCKET_NAME })
  });
  const listData = await listRes.json();
  if (!listRes.ok || !listData.buckets || !listData.buckets.length) {
    throw new Error('B2 bucket not found: ' + env.B2_BUCKET_NAME);
  }
  const bucketId = listData.buckets[0].bucketId;

  const uploadUrlRes = await fetch(`${auth.apiUrl}/b2api/v2/b2_get_upload_url`, {
    method: 'POST',
    headers: { Authorization: auth.authorizationToken, 'Content-Type': 'application/json' },
    body: JSON.stringify({ bucketId })
  });
  const uploadData = await uploadUrlRes.json();
  if (!uploadUrlRes.ok) throw new Error('B2 get_upload_url failed: ' + (uploadData.message || uploadUrlRes.status));

  return {
    uploadUrl: uploadData.uploadUrl,
    uploadAuthToken: uploadData.authorizationToken,
    downloadUrl: auth.downloadUrl,
    bucketName: env.B2_BUCKET_NAME
  };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const p = url.pathname;
    const method = request.method;

    if (!p.startsWith('/api/')) {
      return env.ASSETS.fetch(request);
    }

    try {
      // ---------- PROJECTS (portfolio) ----------
      if (p === '/api/projects' && method === 'GET') {
        return json({ ok: true, projects: await getProjects(env) });
      }
      if (p === '/api/projects' && method === 'POST') {
        if (!requireAdmin(request, env)) return json({ ok: false, error: 'Unauthorized' }, 401);
        const body = await request.json().catch(() => null);
        if (!body || !body.title || !body.video) return json({ ok: false, error: 'title and video required' }, 400);
        const projects = await getProjects(env);
        const project = {
          id: 'proj_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7),
          title: body.title, description: body.description || '', thumbnail: body.thumbnail || '',
          video: body.video, category: body.category || 'Video Editing',
          date: body.date || new Date().toISOString().slice(0, 10),
          featured: !!body.featured, order: body.order ?? (projects.length + 1)
        };
        projects.push(project);
        await saveProjects(env, projects);
        return json({ ok: true, project });
      }
      let m = p.match(/^\/api\/projects\/([^/]+)$/);
      if (m && method === 'DELETE') {
        if (!requireAdmin(request, env)) return json({ ok: false, error: 'Unauthorized' }, 401);
        let projects = await getProjects(env);
        const before = projects.length;
        projects = projects.filter(x => x.id !== m[1]);
        if (projects.length === before) return json({ ok: false, error: 'Not found' }, 404);
        await saveProjects(env, projects);
        return json({ ok: true });
      }

      // ---------- CLIENT (public, token-scoped) ----------
      m = p.match(/^\/api\/client\/([^/]+)$/);
      if (m && method === 'GET') {
        const clients = await getClients(env);
        const client = clients.find(c => c.token === m[1]);
        if (!client) return json({ ok: false, error: 'Invalid link' }, 404);
        const payments = (await getPayments(env)).filter(pm => pm.clientId === client.id);
        return json({ ok: true, client, payments });
      }
      m = p.match(/^\/api\/client\/([^/]+)\/message$/);
      if (m && method === 'POST') {
        const clients = await getClients(env);
        const client = clients.find(c => c.token === m[1]);
        if (!client) return json({ ok: false, error: 'Invalid link' }, 404);
        const body = await request.json().catch(() => null);
        if (!body || !body.text) return json({ ok: false, error: 'text required' }, 400);
        client.messages = client.messages || [];
        client.messages.push({ from: 'client', text: String(body.text).slice(0, 2000), ts: body.ts || Date.now() });
        await saveClients(env, clients);
        return json({ ok: true });
      }
      m = p.match(/^\/api\/client\/([^/]+)\/payment$/);
      if (m && method === 'POST') {
        const clients = await getClients(env);
        const client = clients.find(c => c.token === m[1]);
        if (!client) return json({ ok: false, error: 'Invalid link' }, 404);
        const body = await request.json().catch(() => null);
        if (!body || !body.amount) return json({ ok: false, error: 'amount required' }, 400);
        const id = body.id || ('pay_' + Date.now());
        if (body.screenshot && !body.screenshotUrl) {
          await env.Ashishkv.put('shot:' + id, body.screenshot);
        }
        const payments = await getPayments(env);
        payments.push({
          id, clientId: client.id, clientName: client.name, videoId: body.videoId || null,
          amount: Number(body.amount), note: body.note || '', status: 'pending',
          ts: body.ts || Date.now(), screenshotUrl: body.screenshotUrl || null,
          hasShot: !!(body.screenshot && !body.screenshotUrl)
        });
        await savePayments(env, payments);
        return json({ ok: true });
      }
      m = p.match(/^\/api\/client\/([^/]+)\/review$/);
      if (m && method === 'POST') {
        const clients = await getClients(env);
        const client = clients.find(c => c.token === m[1]);
        if (!client) return json({ ok: false, error: 'Invalid link' }, 404);
        const body = await request.json().catch(() => null);
        if (!body || !body.videoId || !body.review || !body.review.rating) {
          return json({ ok: false, error: 'videoId and review.rating required' }, 400);
        }
        const video = (client.videos || []).find(v => v.id === body.videoId);
        if (!video) return json({ ok: false, error: 'Video not found' }, 404);
        video.review = {
          rating: Math.max(1, Math.min(5, Number(body.review.rating))),
          comment: String(body.review.comment || '').slice(0, 1000),
          ts: body.review.ts || Date.now()
        };
        await saveClients(env, clients);
        return json({ ok: true });
      }
      if (p === '/api/client/b2-upload-url' && method === 'GET') {
        const token = url.searchParams.get('token');
        if (!token) return json({ ok: false, error: 'token required' }, 400);
        const clients = await getClients(env);
        if (!clients.some(c => c.token === token)) return json({ ok: false, error: 'Invalid link' }, 404);
        const slot = await getUploadSlot(env);
        return json({ ok: true, ...slot });
      }

      // ---------- SHOT (screenshot fallback) ----------
      m = p.match(/^\/api\/shot\/([^/]+)$/);
      if (m && method === 'GET') {
        const clientToken = url.searchParams.get('token');
        const isAdmin = requireAdmin(request, env);
        const payments = await getPayments(env);
        const payment = payments.find(pm => pm.id === m[1]);
        if (!payment) return json({ ok: false, error: 'Not found' }, 404);
        if (!isAdmin) {
          const clients = await getClients(env);
          const owner = clients.find(c => c.id === payment.clientId);
          if (!owner || !clientToken || owner.token !== clientToken) return json({ ok: false, error: 'Unauthorized' }, 401);
        }
        const screenshot = await env.Ashishkv.get('shot:' + m[1]);
        if (!screenshot) return json({ ok: false, error: 'No screenshot' }, 404);
        return json({ ok: true, screenshot });
      }

      // ---------- ADMIN ----------
      if (p === '/api/admin/b2-upload-url' && method === 'GET') {
        if (!requireAdmin(request, env)) return json({ ok: false, error: 'Unauthorized' }, 401);
        const slot = await getUploadSlot(env);
        return json({ ok: true, ...slot });
      }
      if (p === '/api/admin/clients' && method === 'GET') {
        if (!requireAdmin(request, env)) return json({ ok: false, error: 'Unauthorized' }, 401);
        return json({ ok: true, clients: await getClients(env) });
      }
      if (p === '/api/admin/clients' && method === 'POST') {
        if (!requireAdmin(request, env)) return json({ ok: false, error: 'Unauthorized' }, 401);
        const body = await request.json().catch(() => null);
        if (!body || !body.name || !body.token) return json({ ok: false, error: 'name and token required' }, 400);
        const clients = await getClients(env);
        if (clients.some(c => c.token === body.token)) return json({ ok: false, error: 'Token already in use' }, 409);
        const client = {
          id: 'c_' + Date.now(), token: body.token, name: body.name, greet: body.greet || 'Hello',
          videos: [], advance: 0, walletLog: [], messages: [], views: 0, uniques: 0
        };
        clients.push(client);
        await saveClients(env, clients);
        return json({ ok: true, client });
      }
      m = p.match(/^\/api\/admin\/clients\/([^/]+)$/);
      if (m && method === 'PUT') {
        if (!requireAdmin(request, env)) return json({ ok: false, error: 'Unauthorized' }, 401);
        const clients = await getClients(env);
        const client = clients.find(c => c.id === m[1]);
        if (!client) return json({ ok: false, error: 'Not found' }, 404);
        const body = await request.json().catch(() => null);
        if (!body || !body.action) return json({ ok: false, error: 'action required' }, 400);

        if (body.action === 'message' && body.message) {
          client.messages = client.messages || [];
          client.messages.push({ from: 'admin', text: String(body.message.text).slice(0, 2000), ts: body.message.ts || Date.now() });
        } else if (body.action === 'addVideo' && body.video) {
          client.videos = client.videos || [];
          client.videos.push({
            id: 'v_' + Date.now(), title: body.video.title, price: Number(body.video.price) || 0,
            paid: 0, status: body.video.status || 'editing', thumb: body.video.thumb || '',
            driveLink: body.video.driveLink || '', videoUrl: body.video.videoUrl || '',
            readyDate: body.video.readyDate || null, review: null, order: client.videos.length
          });
        } else if (body.action === 'updateVideo' && body.videoId && body.video) {
          const v = (client.videos || []).find(x => x.id === body.videoId);
          if (v) {
            if (body.video.title) v.title = body.video.title;
            if (body.video.price != null) v.price = Number(body.video.price);
            if (body.video.status) v.status = body.video.status;
            if (body.video.driveLink != null) v.driveLink = body.video.driveLink;
            if (body.video.videoUrl != null) v.videoUrl = body.video.videoUrl;
            if (body.video.thumb) v.thumb = body.video.thumb;
            if (body.video.readyDate !== undefined) v.readyDate = body.video.readyDate;
          }
        } else if (body.action === 'deleteVideo' && body.videoId) {
          client.videos = (client.videos || []).filter(v => v.id !== body.videoId);
        } else if (body.action === 'update') {
          if (body.name) client.name = body.name;
          if (body.greet) client.greet = body.greet;
        } else if (body.action === 'addWallet' && body.amount) {
          client.advance = (client.advance || 0) + Number(body.amount);
          client.walletLog = client.walletLog || [];
          client.walletLog.push({ type: 'credit', amount: Number(body.amount), note: 'Added by admin', ts: Date.now() });
        } else if (body.action === 'setWallet' && body.balance != null) {
          const diff = Number(body.balance) - (client.advance || 0);
          client.advance = Number(body.balance);
          client.walletLog = client.walletLog || [];
          if (diff !== 0) client.walletLog.push({ type: diff > 0 ? 'credit' : 'debit', amount: Math.abs(diff), note: 'Balance manually set by admin', ts: Date.now() });
        } else {
          return json({ ok: false, error: 'Unknown action' }, 400);
        }
        await saveClients(env, clients);
        return json({ ok: true, client });
      }
      if (m && method === 'DELETE') {
        if (!requireAdmin(request, env)) return json({ ok: false, error: 'Unauthorized' }, 401);
        let clients = await getClients(env);
        const before = clients.length;
        clients = clients.filter(c => c.id !== m[1]);
        if (clients.length === before) return json({ ok: false, error: 'Not found' }, 404);
        await saveClients(env, clients);
        return json({ ok: true });
      }
      if (p === '/api/admin/payments' && method === 'GET') {
        if (!requireAdmin(request, env)) return json({ ok: false, error: 'Unauthorized' }, 401);
        return json({ ok: true, payments: await getPayments(env) });
      }
      m = p.match(/^\/api\/admin\/payments\/([^/]+)$/);
      if (m && method === 'POST') {
        if (!requireAdmin(request, env)) return json({ ok: false, error: 'Unauthorized' }, 401);
        const body = await request.json().catch(() => null);
        if (!body || !['approve', 'reject'].includes(body.action)) return json({ ok: false, error: 'action must be approve or reject' }, 400);
        const payments = await getPayments(env);
        const payment = payments.find(pm => pm.id === m[1]);
        if (!payment || payment.status !== 'pending') return json({ ok: false, error: 'Payment not found or already processed' }, 404);

        if (body.action === 'reject') {
          payment.status = 'rejected';
          payment.decidedTs = Date.now();
          await savePayments(env, payments);
          return json({ ok: true });
        }
        const clients = await getClients(env);
        const client = clients.find(c => c.id === payment.clientId);
        if (client) {
          let remaining = payment.amount;
          const target = payment.videoId ? (client.videos || []).find(v => v.id === payment.videoId) : null;
          if (target) {
            const due = Math.max(0, target.price - target.paid);
            const apply = Math.min(due, remaining);
            target.paid += apply;
            if (target.paid >= target.price && target.status === 'editing') target.status = 'ready';
            remaining -= apply;
          }
          const unpaid = (client.videos || [])
            .filter(v => v.paid < v.price && (v.status === 'ready' || v.status === 'editing'))
            .sort((a, b) => (a.order || 0) - (b.order || 0));
          for (const v of unpaid) {
            if (remaining <= 0) break;
            const due = v.price - v.paid;
            const apply = Math.min(due, remaining);
            v.paid += apply;
            remaining -= apply;
            if (v.paid >= v.price && v.status === 'editing') v.status = 'ready';
          }
          if (remaining > 0) client.advance = (client.advance || 0) + remaining;
          await saveClients(env, clients);
        }
        payment.status = 'approved';
        payment.decidedTs = Date.now();
        await savePayments(env, payments);
        return json({ ok: true });
      }

      return json({ ok: false, error: 'Not found' }, 404);
    } catch (e) {
      return json({ ok: false, error: e.message }, 500);
    }
  }
};
