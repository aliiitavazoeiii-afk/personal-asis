/* Personal Assist: online-first shell. No personal data or JS is cached.
 * Installing to Android home screen does not freeze UI versions: every visit
 * requests the latest content from the user's own HTTPS server. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
