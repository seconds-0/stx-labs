import { NextRequest, NextResponse } from 'next/server';

type MaybeString = string | null | undefined;

const COOKIE_NAME = '__stx_auth';
const SESSION_TTL_MS = 12 * 60 * 60 * 1000; // 12 hours
const encoder = new TextEncoder();

const passwordHash = process.env.AUTH_PASSWORD_HASH;
const passwordSalt = process.env.AUTH_PASSWORD_SALT ?? '';
const sessionSecret = process.env.AUTH_SESSION_SECRET;

if (!passwordHash) {
  console.warn('AUTH_PASSWORD_HASH is not configured. All requests will be rejected.');
}
if (!sessionSecret) {
  console.warn('AUTH_SESSION_SECRET is not configured. All requests will be rejected.');
}

function htmlResponse(body: string, status = 200) {
  return new NextResponse(body, {
    status,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'no-store'
    }
  });
}

function escapeAttribute(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/'/g, '&#39;');
}

function loginPage(url: string, error = '') {
  const safeMessage = error ? `<p class="error">${error}</p>` : '';
  const safeRedirect = escapeAttribute(url);
  return htmlResponse(`<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Stacks Analytics · Login</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; background: #060b15; color: #f5f6fa; margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.5rem; }
      .card { width: min(360px, 100%); background: #0e1524; border: 1px solid #1f2a44; border-radius: 12px; padding: 2rem; box-shadow: 0 20px 45px rgba(0,0,0,.35); }
      h1 { margin-top: 0; font-size: 1.4rem; }
      label { display: block; font-size: 0.9rem; margin-bottom: 0.35rem; color: #9ca8c7; }
      input[type="password"] { width: 100%; padding: 0.65rem 0.8rem; border-radius: 8px; border: 1px solid #2e3b5c; background: #141d32; color: inherit; font-size: 1rem; }
      button { width: 100%; margin-top: 1rem; padding: 0.65rem; border-radius: 8px; border: none; background: #00b5ff; color: #041428; font-weight: 600; font-size: 1rem; cursor: pointer; }
      .error { color: #ff8a7a; font-size: 0.9rem; margin-top: 0.75rem; }
      .note { font-size: 0.8rem; color: #7f8bb3; margin-top: 0.85rem; }
    </style>
  </head>
  <body>
    <main class="card">
      <h1>Stacks Analytics</h1>
      <form method="POST">
        <input type="hidden" name="redirect" value="${safeRedirect}" />
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required />
        <button type="submit">Continue</button>
        ${safeMessage}
        <p class="note">Access limited to the Stacks analytics team.</p>
      </form>
    </main>
  </body>
</html>`);
}

function bytesToHex(bytes: Uint8Array) {
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function sha256Hex(input: string) {
  const hash = await crypto.subtle.digest('SHA-256', encoder.encode(input));
  return bytesToHex(new Uint8Array(hash));
}

async function signSession(expires: number) {
  const data = encoder.encode(`${expires}.${sessionSecret}`);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return bytesToHex(new Uint8Array(hash));
}

async function verifySession(token: MaybeString) {
  if (!token || !sessionSecret) {
    return false;
  }
  const [expiresStr, signature] = token.split('.');
  if (!expiresStr || !signature) {
    return false;
  }
  const expires = Number(expiresStr);
  if (!Number.isFinite(expires) || expires < Date.now()) {
    return false;
  }
  const expected = await signSession(expires);
  return signature === expected;
}

async function handleLogin(request: NextRequest) {
  if (!passwordHash || !sessionSecret) {
    return htmlResponse('Missing auth configuration', 500);
  }
  const formData = await request.formData();
  const password = formData.get('password');
  const redirect = (formData.get('redirect') as string) || '/';
  const target = redirect.startsWith('/') ? redirect : '/';
  if (typeof password !== 'string' || !password.trim()) {
    return loginPage(target, 'Password is required.');
  }
  const computed = await sha256Hex(`${passwordSalt}:${password}`);
  if (computed !== passwordHash) {
    await new Promise((resolve) => setTimeout(resolve, 150));
    return loginPage(target, 'Incorrect password.');
  }
  const expires = Date.now() + SESSION_TTL_MS;
  const signature = await signSession(expires);
  const response = NextResponse.redirect(new URL(target, request.url));
  response.cookies.set({
    name: COOKIE_NAME,
    value: `${expires}.${signature}`,
    httpOnly: true,
    secure: true,
    sameSite: 'strict',
    expires
  });
  return response;
}

export async function middleware(request: NextRequest) {
  const token = request.cookies.get(COOKIE_NAME)?.value;
  if (await verifySession(token)) {
    return NextResponse.next();
  }
  if (request.method === 'POST') {
    return handleLogin(request);
  }
  return loginPage(request.nextUrl.pathname + request.nextUrl.search);
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|robots.txt).*)']
};
