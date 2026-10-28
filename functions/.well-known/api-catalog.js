/** RFC 9727 API catalog: /.well-known/api-catalog
 *
 * Lists the public, read-only Rochdale Daily APIs so automated clients can
 * find the OpenAPI description, the human docs and the health check. Private
 * newsdesk endpoints (moderation, live desk, newsletter export) are not listed.
 */
const ORIGIN = "https://rochdaledaily.co.uk";
const PROFILE = "https://www.rfc-editor.org/info/rfc9727";

function entry(anchor) {
  return {
    anchor: ORIGIN + anchor,
    "service-desc": [{ href: ORIGIN + "/openapi.json", type: "application/vnd.oai.openapi+json" }],
    "service-doc": [{ href: ORIGIN + "/developers", type: "text/html" }],
    status: [{ href: ORIGIN + "/api/health", type: "application/json" }],
  };
}

export function catalog() {
  return {
    linkset: [
      { ...entry("/api/"), "api-catalog": [{ href: ORIGIN + "/.well-known/api-catalog" }] },
      entry("/articles.json"),
      entry("/weather.json"),
      entry("/api/events"),
      entry("/api/live-updates"),
    ],
  };
}

function headers() {
  return {
    "Content-Type": `application/linkset+json; profile="${PROFILE}"`,
    "Link": `<${ORIGIN}/.well-known/api-catalog>; rel="api-catalog"`,
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "public, max-age=3600",
  };
}

export function onRequestGet() {
  return new Response(JSON.stringify(catalog(), null, 2) + "\n", { status: 200, headers: headers() });
}

export function onRequestHead() {
  return new Response(null, { status: 200, headers: headers() });
}
