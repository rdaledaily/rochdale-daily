export async function onRequest(context) {
  const response = await context.next();
  const url = new URL(context.request.url);

  if (!url.pathname.endsWith('/assets/ads.js') || !response.ok) {
    return response;
  }

  const source = await response.text();
  const loader = `\n;(function(){
    var scripts = [
      '/assets/whats-on-community-fix.js?v=20260910-1',
      '/assets/democracy-hover.js?v=20260812-1'
    ];
    scripts.forEach(function(src){
      var s=document.createElement('script');
      s.src=src;
      s.defer=true;
      document.head.appendChild(s);
    });
  }());
;(function(){
    // Most-read counter (9 Nov 2026): one beacon per article open, read by
    // /articles/frontpage.json to lift today's most-read stories from #3 down.
    // Sends only the slug. Writes nothing to the reader's browser. Reloads and
    // back/forward visits are not counted.
    try {
      var m = location.pathname.match(/^\\/articles\\/([a-z0-9][a-z0-9-]{1,198})(?:\\.html)?\\/?$/);
      if (!m || navigator.webdriver) return;
      var nav = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
      if (nav && (nav.type === 'reload' || nav.type === 'back_forward')) return;
      var body = JSON.stringify({ slug: m[1] });
      if (navigator.sendBeacon && navigator.sendBeacon('/api/story-views', new Blob([body], { type: 'application/json' }))) return;
      fetch('/api/story-views', { method: 'POST', headers: { 'content-type': 'application/json' }, body: body, keepalive: true }).catch(function(){});
    } catch (e) {}
  }());\n`;
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
