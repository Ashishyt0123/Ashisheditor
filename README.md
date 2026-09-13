# Setup Guide

## 1. Files
- `index.html` — the whole site (public + client portal + admin panel). Works on its own (localStorage) even without deploying the backend below.
- `functions/` — Cloudflare Pages Functions that connect the site to your KV storage (`Ashishkv` binding → `Ashishdata` namespace) so everything (clients, chats, payments, screenshots, portfolio) is saved centrally.

## 2. KV binding
Already set up on your end: variable name `Ashishkv`, namespace `Ashishdata`. Make sure it's attached to this Pages project (Settings → Functions → Bindings).

## 3. Admin login
Built into the page — no password in the code. The first time you log in (any device), whatever ID/password you type becomes your permanent login. It also generates a random sync token shown once — copy it into an environment variable named `ADMIN_TOKEN` on your Pages project (Settings → Environment variables) so admin actions sync to KV. View it again anytime under Profile in admin.

## 4. Redeploy
After setting `ADMIN_TOKEN`, redeploy so the Functions pick it up.

## What's new in this build
- Wallet badge no longer overlaps the nav — sits cleanly below the client's name.
- Paste a Google Drive share link for a client's video: thumbnail is generated automatically, "Watch" plays a smooth in-page preview, and clients can download the **original** file only after leaving a star rating + optional comment (review syncs back to admin).
- Marking a video "Ready" auto-fills today's date; editable anytime.
- Overview tab shows your Top 5 most active clients — click straight into their full detail (info/videos/chat/payments).
- Edit buttons added everywhere a record can be created: client videos and portfolio videos.
- WhatsApp field accepts either a plain number or a full custom `wa.me` link with a prefilled message — no more duplicated digits.
- Admin can add money to a client's wallet manually; new videos auto-deduct from wallet balance; every wallet movement is logged as a transaction (client Info tab).
- Payment screenshot is now required to submit, with a red-highlighted upload box until a file is chosen.
- Live chat now also polls in the admin panel (not just the client portal), and if admin + client tabs are open in the *same* browser, messages sync between them instantly even without the backend deployed.
- Emoji picker button next to both chat inputs.
- Payment screenshots are stored full quality, uncompressed, as their own KV entry per payment (not squeezed into the shared list).
- If the backend isn't deployed yet, everything still works locally (per-browser) as a fallback.
