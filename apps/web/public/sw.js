/* Skill Garden service worker: Web Push for "Incoming call from Bhima". No fetch handler and no
 * caching on purpose: pages are authenticated and must always come from the network. */

const CALL_PATH = /^\/call\/[0-9a-f-]{36}$/i;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function parse(event) {
  try {
    return event.data ? event.data.json() : null;
  } catch {
    return null;
  }
}

self.addEventListener("push", (event) => {
  const data = parse(event);
  // Push content is data from the network: accept only the one shape we send.
  if (!data || data.type !== "incoming_call" || !CALL_PATH.test(String(data.url || ""))) return;
  const expiresAt = Date.parse(data.expires_at);
  if (!Number.isNaN(expiresAt) && expiresAt <= Date.now()) return;

  const caller = typeof data.caller === "string" ? data.caller.slice(0, 40) : "Bhima";
  event.waitUntil(
    (async () => {
      await self.registration.showNotification(`Incoming call from ${caller}`, {
        body: "Tap to answer. It takes about two minutes.",
        tag: `call-${data.attempt_id}`,
        icon: "/icon.svg",
        badge: "/icon.svg",
        requireInteraction: true,
        renotify: true,
        data: { url: data.url, expiresAt: Number.isNaN(expiresAt) ? null : expiresAt },
      });
      // The call stops ringing after the timeout, so take the notification down with it.
      if (!Number.isNaN(expiresAt)) {
        await new Promise((resolve) =>
          setTimeout(resolve, Math.max(0, Math.min(expiresAt - Date.now(), 120000))),
        );
        const open = await self.registration.getNotifications({ tag: `call-${data.attempt_id}` });
        open.forEach((n) => n.close());
      }
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data && event.notification.data.url;
  if (!url || !CALL_PATH.test(url)) return;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin && "navigate" in client) {
          await client.navigate(url);
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    })(),
  );
});
