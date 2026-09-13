// Shared helper — not a route (files/folders starting with _ are ignored by
// Cloudflare Pages routing), imported by the b2-upload-url endpoints.
//
// Needs these environment variables set on the Pages project:
//   B2_KEY_ID       - your Backblaze application key ID
//   B2_APP_KEY      - your Backblaze application key
//   B2_BUCKET_NAME  - "ashish-editor-videos"

export async function getUploadSlot(env) {
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
