const API_URL = "https://mira-f94e.onrender.com/health";
const WEB_URL = "https://mira-web-q0r6.onrender.com/";

export default {
  async scheduled(event, env, ctx) {
    const results = await Promise.allSettled([
      fetch(API_URL, { method: "GET" }),
      fetch(WEB_URL, { method: "GET" }),
      pingNeon(env.NEON_URL),
    ]);

    const [api, web, db] = results;

    console.log(
      `[keepalive] API: ${api.status === "fulfilled" ? api.value.status : api.reason?.message}`,
      `| Web: ${web.status === "fulfilled" ? web.value.status : web.reason?.message}`,
      `| DB: ${db.status === "fulfilled" ? db.value : db.reason?.message}`
    );
  },
};

async function pingNeon(connStr) {
  if (!connStr) return "no NEON_URL secret";
  const host = new URL(connStr.replace(/^postgresql:\/\//, "https://"));
  const endpoint = `https://${host.hostname}/sql`;
  const res = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "neon-connection-string": connStr,
    },
    body: JSON.stringify({ query: "SELECT 1" }),
  });
  if (!res.ok) return `HTTP ${res.status}`;
  const data = await res.json();
  return data.rows?.[0]?.["?column?"] === 1 ? "ok" : JSON.stringify(data).slice(0, 80);
}
