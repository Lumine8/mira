const WEB_HOST = "mira-web-q0r6.onrender.com";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = new URL(url);
    target.hostname = WEB_HOST;
    target.protocol = "https:";
    target.port = "443";

    const headers = new Headers(request.headers);
    headers.set("Host", WEB_HOST);
    headers.set("X-Forwarded-Host", url.hostname);
    headers.set("X-Forwarded-Proto", "https");

    return fetch(new Request(target.toString(), {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual",
    }));
  },
};
