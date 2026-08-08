export async function onRequest(context) {
  const response = await context.next();
  const url = new URL(context.request.url);

  if (!url.pathname.endsWith('/assets/ads.js') || !response.ok) {
    return response;
  }

  const source = await response.text();
  const loader = `\n;(function(){var s=document.createElement('script');s.src='/assets/whats-on-community-fix.js?v=20260808-1';s.defer=true;document.head.appendChild(s);}());\n`;
  const headers = new Headers(response.headers);
  headers.set('Content-Type', 'application/javascript; charset=utf-8');
  headers.set('Cache-Control', 'no-store, no-cache, must-revalidate');
  headers.delete('Content-Length');

  return new Response(source + loader, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}
