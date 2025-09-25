/**
 * FiCore Offline Manager
 * Handles offline data storage, synchronization, and UI state management
 */

class OfflineManager {
    constructor() {
        this.dbName = 'FiCoreOfflineDB';
        this.dbVersion = 1;
        this.db = null;
        this.isOnline = navigator.onLine;
        this.syncQueue = [];
        this.init();
    }

    async init() {
        try {
            await this.initIndexedDB();
            this.setupEventListeners();
            this.updateOnlineStatus();
            this.registerBackgroundSync();
            console.log('Offline Manager initialized successfully');
        } catch (error) {
            console.error('Failed to initialize Offline Manager:', error);
        }
    }

    // IndexedDB Setup
    async initIndexedDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.dbVersion);
            
            request.onerror = () => reject(request.error);
            request.onsuccess = () => {
                this.db = request.result;
                resolve();
            };
            
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                
                // Store for offline actions (bills, budgets, shopping items, etc.)
                if (!db.objectStoreNames.contains('offlineActions')) {
                    const actionStore = db.createObjectStore('offlineActions', { 
                        keyPath: 'id', 
                        autoIncrement: true 
                    });
                    actionStore.createIndex('timestamp', 'timestamp');
                    actionStore.createIndex('type', 'type');
                    actionStore.createIndex('synced', 'synced');
                }
                
                // Store for cached API responses
                if (!db.objectStoreNames.contains('cachedData')) {
                    const cacheStore = db.createObjectStore('cachedData', { 
                        keyPath: 'key' 
                    });
                    cacheStore.createIndex('timestamp', 'timestamp');
                    cacheStore.createIndex('expiry', 'expiry');
                }
                
                // Store for user preferences and settings
                if (!db.objectStoreNames.contains('userSettings')) {
                    db.createObjectStore('userSettings', { keyPath: 'key' });
                }
            };
        });
    }

    // Event Listeners
    setupEventListeners() {
        // Online/Offline status
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.updateOnlineStatus();
            this.syncOfflineData();
        });
        
        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.updateOnlineStatus();
        });

        // Service Worker messages
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.addEventListener('message', (event) => {
                if (event.data.type === 'SYNC_COMPLETED') {
                    this.showNotification('Data synchronized successfully!', 'success');
                    this.updateSyncStatus();
                }
            });
        }
    }

    // Online Status Management
    updateOnlineStatus() {
        const statusIndicator = document.getElementById('online-status');
        const offlineNotice = document.getElementById('offline-notice');
        
        if (statusIndicator) {
            statusIndicator.className = this.isOnline ? 'online' : 'offline';
            statusIndicator.textContent = this.isOnline ? 'Online' : 'Offline';
        }
        
        if (offlineNotice) {
            offlineNotice.style.display = this.isOnline ? 'none' : 'block';
        }
        
        // Update form behavior
        this.updateFormBehavior();
    }

    updateFormBehavior() {
        const forms = document.querySelectorAll('form[data-offline-capable]');
        forms.forEach(form => {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                if (!this.isOnline) {
                    submitBtn.textContent = submitBtn.dataset.offlineText || 'Save Offline';
                    submitBtn.classList.add('offline-mode');
                } else {
                    submitBtn.textContent = submitBtn.dataset.onlineText || 'Save';
                    submitBtn.classList.remove('offline-mode');
                }
            }
        });
    }

    // Data Storage Methods
    async storeOfflineAction(action) {
        if (!this.db) return false;
        
        const transaction = this.db.transaction(['offlineActions'], 'readwrite');
        const store = transaction.objectStore('offlineActions');
        
        const actionData = {
            ...action,
            timestamp: Date.now(),
            synced: false,
            id: Date.now() + Math.random() // Simple ID generation
        };
        
        try {
            await store.add(actionData);
            this.updateSyncStatus();
            this.showNotification('Action saved offline. Will sync when online.', 'info');
            return true;
        } catch (error) {
            console.error('Failed to store offline action:', error);
            return false;
        }
    }

    async getCachedData(key) {
        if (!this.db) return null;
        
        const transaction = this.db.transaction(['cachedData'], 'readonly');
        const store = transaction.objectStore('cachedData');
        
        try {
            const result = await store.get(key);
            if (result && result.expiry > Date.now()) {
                return result.data;
            }
            return null;
        } catch (error) {
            console.error('Failed to get cached data:', error);
            return null;
        }
    }

    async setCachedData(key, data, ttl = 3600000) { // 1 hour default TTL
        if (!this.db) return false;
        
        const transaction = this.db.transaction(['cachedData'], 'readwrite');
        const store = transaction.objectStore('cachedData');
        
        const cacheData = {
            key,
            data,
            timestamp: Date.now(),
            expiry: Date.now() + ttl
        };
        
        try {
            await store.put(cacheData);
            return true;
        } catch (error) {
            console.error('Failed to cache data:', error);
            return false;
        }
    }

    // Sync Methods
    async syncOfflineData() {
        if (!this.isOnline || !this.db) return;
        
        const transaction = this.db.transaction(['offlineActions'], 'readwrite');
        const store = transaction.objectStore('offlineActions');
        const index = store.index('synced');
        
        try {
            const unsyncedActions = await index.getAll(false);
            
            for (const action of unsyncedActions) {
                try {
                    await this.syncSingleAction(action);
                    
                    // Mark as synced
                    action.synced = true;
                    await store.put(action);
                    
                } catch (error) {
                    console.error('Failed to sync action:', action.id, error);
                }
            }
            
            this.updateSyncStatus();
        } catch (error) {
            console.error('Failed to sync offline data:', error);
        }
    }

    async syncSingleAction(action) {
        const response = await fetch(action.url, {
            method: action.method || 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken(),
                ...action.headers
            },
            body: action.body
        });
        
        if (!response.ok) {
            throw new Error(`Sync failed: ${response.status}`);
        }
        
        return response.json();
    }

    registerBackgroundSync() {
        if ('serviceWorker' in navigator && 'sync' in window.ServiceWorkerRegistration.prototype) {
            navigator.serviceWorker.ready.then(registration => {
                return registration.sync.register('sync-offline-data');
            }).catch(error => {
                console.log('Background sync registration failed:', error);
            });
        }
    }

    // Form Handling
    handleOfflineForm(form, formData) {
        const action = {
            type: form.dataset.actionType || 'form_submission',
            url: form.action,
            method: form.method.toUpperCase(),
            body: JSON.stringify(Object.fromEntries(formData)),
            formId: form.id
        };
        
        return this.storeOfflineAction(action);
    }

    // UI Helper Methods
    updateSyncStatus() {
        if (!this.db) return;
        
        const transaction = this.db.transaction(['offlineActions'], 'readonly');
        const store = transaction.objectStore('offlineActions');
        const index = store.index('synced');
        
        index.count(false).then(count => {
            const syncStatus = document.getElementById('sync-status');
            if (syncStatus) {
                if (count > 0) {
                    syncStatus.textContent = `${count} items pending sync`;
                    syncStatus.style.display = 'block';
                } else {
                    syncStatus.style.display = 'none';
                }
            }
        });
    }

    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `offline-notification ${type}`;
        notification.innerHTML = `
            <div class="notification-content">
                <i class="bi ${this.getNotificationIcon(type)}"></i>
                <span>${message}</span>
                <button class="close-btn" onclick="this.parentElement.parentElement.remove()">×</button>
            </div>
        `;
        
        // Add to page
        document.body.appendChild(notification);
        
        // Auto remove after 5 seconds
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);
    }

    getNotificationIcon(type) {
        const icons = {
            success: 'bi-check-circle-fill',
            error: 'bi-exclamation-circle-fill',
            warning: 'bi-exclamation-triangle-fill',
            info: 'bi-info-circle-fill'
        };
        return icons[type] || icons.info;
    }

    getCSRFToken() {
        return document.querySelector('meta[name="csrf-token"]')?.content || '';
    }

    // Public API Methods
    async saveForLater(data, type) {
        const action = {
            type: `save_${type}`,
            data: data,
            url: `/api/${type}`,
            method: 'POST',
            body: JSON.stringify(data)
        };
        
        return await this.storeOfflineAction(action);
    }

    async getOfflineData(type) {
        return await this.getCachedData(`offline_${type}`);
    }

    isOffline() {
        return !this.isOnline;
    }
}

// Initialize offline manager when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.offlineManager = new OfflineManager();
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = OfflineManager;
}