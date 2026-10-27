/* Personal Assist server-driven PWA: never persist HTML, JS, audio or API data.
 * Fetch handler makes installability explicit while keeping every request
 * network-only. Offline fallback is intentionally not provided. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  if (new URL(request.url).origin !== self.location.origin) return;
  event.respondWith(fetch(request, {cache:'no-store'}));
});
