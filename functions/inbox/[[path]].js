// inbox/ holds what the newsdesk was emailed (reader messages included).
// It lives in the repo for the pipeline, not on the website: never serve it.
export function onRequest() {
  return new Response("Not found", { status: 404, headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex" } });
}
