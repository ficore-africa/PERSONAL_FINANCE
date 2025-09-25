const CACHE_VERSION = 'v2.1';
const STATIC_CACHE = `ficore-static-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `ficore-dynamic-${CACHE_VERSION}`;
const API_CACHE = `ficore-api-${CACHE_VERSION}`;

// Static assets that rarely change
const STATIC_ASSETS = [
    '/static/css/styles.css',
    '/static/css/bootstrap-icons.min.css',
    '/static/css/newbasefilelooks.css',
    '/static/css/iconslooks.css',
    '/static/css/newhomepagepersonal.css',
    '/static/css/dark_mode_enhancements.css',
    '/static/css/tool-header-fix.css',
    '/static/js/scripts.js',
    '/static/js/interactivity.js',
    '/static/js/offline-manager.js',
    '/static/manifest.json',
    '/static/img/favicon.ico',
    '/static/img/apple-touch-icon.png',
    '/static/img/favicon-32x32.png',
    '/static/img/favicon-16x16.png',
    '/static/img/default_profile.png',
    '/static/img/ficore_africa_logo.png',
    '/static/img/icons/icon-192x192.png',
    '/static/img/icons/icon-512x512.png'
];

// Routes that should always try network first
const NETWORK_FIRST_ROUTES = [
    '/users/login',
    '/users/logout',
    '/users/signup',
    '/users/forgot_password',
    '/users/reset_password',
    '/users/verify_2fa',
    '/api/notifications/count',
    '/change-language'
];

// API routes that can be cached for offline use
const CACHEABLE_API_ROUTES = [
    '/dashboard/',
    '/bills/',
    '/budget/',
    '/shopping/',
    '/reports/',
    '/settings/profile'
];

// Routes that should be cached after first visit
const CACHE_FIRST_ROUTES = [
    '/general/home',
    '/general/landing',
    '/set-language'
];

self.addEventListener('install', event => {
    console.log('Service Worker installing...');
    event.waitUntil(
        Promise.all([
            caches.open(STATIC_CACHE).then(cache => {
                console.log('Caching static assets...');
                return cache.addAll(STATIC_ASSETS);
            }),
            caches.open(DYNAMIC_CACHE),
            caches.open(API_CACHE)
        ]).then(() => {
            console.log('Service Worker installed successfully');
            self.skipWaiting();
        }).catch(error => {
            console.error('Service Worker installation failed:', error);
        })
    );
});

self.addEventListener('fetch', event => {
    const requestUrl = new URL(event.request.url);
    const pathname = requestUrl.pathname;
    
    // Skip non-GET requests and chrome-extension requests
    if (event.request.method !== 'GET' || requestUrl.protocol === 'chrome-extension:') {
        return;
    }

    // Handle different caching strategies based on route type
    if (NETWORK_FIRST_ROUTES.some(route => pathname.startsWith(route))) {
        event.respondWith(handleNetworkFirst(event.request));
    } else if (CACHEABLE_API_ROUTES.some(route => pathname.startsWith(route))) {
        event.respondWith(handleStaleWhileRevalidate(event.request));
    } else if (CACHE_FIRST_ROUTES.some(route => pathname.startsWith(route))) {
        event.respondWith(handleCacheFirst(event.request));
    } else if (STATIC_ASSETS.some(asset => pathname === asset)) {
        event.respondWith(handleCacheFirst(event.request));
    } else {
        event.respondWith(handleStaleWhileRevalidate(event.request));
    }
});

// Network first strategy - for critical real-time data
async function handleNetworkFirst(request) {
    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        console.log('Network failed, trying cache:', request.url);
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }
        return createOfflineResponse(request);
    }
}

// Cache first strategy - for static assets
async function handleCacheFirst(request) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
        return cachedResponse;
    }
    
    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            const cache = await caches.open(STATIC_CACHE);
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        return createOfflineResponse(request);
    }
}

// Stale while revalidate - for dynamic content
async function handleStaleWhileRevalidate(request) {
    const cachedResponse = await caches.match(request);
    
    const fetchPromise = fetch(request).then(networkResponse => {
        if (networkResponse.ok) {
            const cache = caches.open(
                request.url.includes('/api/') ? API_CACHE : DYNAMIC_CACHE
            );
            cache.then(c => c.put(request, networkResponse.clone()));
        }
        return networkResponse;
    }).catch(() => null);
    
    return cachedResponse || fetchPromise || createOfflineResponse(request);
}

// Create offline response based on request type
function createOfflineResponse(request) {
    const url = new URL(request.url);
    
    if (request.headers.get('accept')?.includes('text/html')) {
        return caches.match('/general/home').then(response => 
            response || new Response(
                createOfflineHTML(),
                { 
                    status: 200, 
                    headers: { 'Content-Type': 'text/html' } 
                }
            )
        );
    }
    
    if (request.headers.get('accept')?.includes('application/json')) {
        return new Response(
            JSON.stringify({ 
                offline: true, 
                message: 'This data is not available offline',
                timestamp: Date.now()
            }),
            { 
                status: 200, 
                headers: { 'Content-Type': 'application/json' } 
            }
        );
    }
    
    return new Response('Offline: Resource not available', { status: 503 });
}

function createOfflineHTML() {
    return `
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>FiCore Africa - Offline</title>
            <style>
                body { font-family: 'Poppins', sans-serif; text-align: center; padding: 50px; background: #F2EFEA; }
                .offline-container { max-width: 400px; margin: 0 auto; }
                .offline-icon { font-size: 4rem; color: #0F3D57; margin-bottom: 20px; }
                h1 { color: #0F3D57; margin-bottom: 20px; }
                p { color: #666; margin-bottom: 30px; }
                .retry-btn { background: #0F3D57; color: white; padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; }
                .retry-btn:hover { background: #0a2d42; }
            </style>
        </head>
        <body>
            <div class="offline-container">
                <div class="offline-icon">📱</div>
                <h1>You're Offline</h1>
                <p>It looks like you've lost your internet connection. Don't worry, you can still access some features of FiCore Africa.</p>
                <button class="retry-btn" onclick="window.location.reload()">Try Again</button>
            </div>
        </body>
        </html>
    `;
}

self.addEventListener('activate', event => {
    console.log('Service Worker activating...');
    const cacheWhitelist = [STATIC_CACHE, DYNAMIC_CACHE, API_CACHE];
    
    event.waitUntil(
        Promise.all([
            // Clean up old caches
            caches.keys().then(cacheNames => {
                return Promise.all(
                    cacheNames.map(cacheName => {
                        if (!cacheWhitelist.includes(cacheName)) {
                            console.log('Deleting old cache:', cacheName);
                            return caches.delete(cacheName);
                        }
                    })
                );
            }),
            // Take control of all clients
            self.clients.claim()
        ]).then(() => {
            console.log('Service Worker activated successfully');
            // Notify all clients about the update
            self.clients.matchAll().then(clients => {
                clients.forEach(client => {
                    client.postMessage({ type: 'SW_UPDATED' });
                });
            });
        })
    );
});

// Handle background sync for offline actions
self.addEventListener('sync', event => {
    console.log('Background sync triggered:', event.tag);
    
    if (event.tag === 'sync-offline-data') {
        event.waitUntil(syncOfflineData());
    }
});

async function syncOfflineData() {
    try {
        // Get offline data from IndexedDB
        const offlineData = await getOfflineDataFromIDB();
        
        for (const item of offlineData) {
            try {
                const response = await fetch(item.url, {
                    method: item.method,
                    headers: item.headers,
                    body: item.body
                });
                
                if (response.ok) {
                    // Remove synced item from offline storage
                    await removeOfflineDataFromIDB(item.id);
                    console.log('Synced offline data:', item.id);
                }
            } catch (error) {
                console.error('Failed to sync item:', item.id, error);
            }
        }
        
        // Notify clients about sync completion
        self.clients.matchAll().then(clients => {
            clients.forEach(client => {
                client.postMessage({ type: 'SYNC_COMPLETED' });
            });
        });
    } catch (error) {
        console.error('Background sync failed:', error);
    }
}

// Placeholder functions for IndexedDB operations
async function getOfflineDataFromIDB() {
    // This will be implemented in the offline manager
    return [];
}

async function removeOfflineDataFromIDB(id) {
    // This will be implemented in the offline manager
    return true;
}
