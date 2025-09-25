/**
 * Offline Dashboard Component for FiCore Africa
 * Displays cached data when offline and provides smooth transitions
 */

class OfflineDashboard {
    constructor() {
        this.isOnline = navigator.onLine;
        this.lastUpdate = null;
        this.cachedData = {};
        this.init();
    }

    async init() {
        this.setupEventListeners();
        await this.loadCachedData();
        this.updateDashboard();
        console.log('Offline Dashboard initialized');
    }

    setupEventListeners() {
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.refreshData();
        });

        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.showOfflineIndicators();
        });

        // Refresh button
        const refreshBtn = document.getElementById('refreshDashboard');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.refreshData());
        }
    }

    async loadCachedData() {
        if (!window.offlineManager) return;

        try {
            // Load different types of cached data
            const cacheKeys = [
                'dashboard_summary',
                'recent_bills',
                'budget_overview',
                'shopping_lists'
            ];

            for (const key of cacheKeys) {
                const data = await window.offlineManager.getCachedData(key);
                if (data) {
                    this.cachedData[key] = data;
                }
            }

            this.lastUpdate = new Date(localStorage.getItem('dashboard_last_update') || Date.now());
        } catch (error) {
            console.error('Failed to load cached data:', error);
        }
    }

    async refreshData() {
        if (!this.isOnline) {
            this.showNotification('Cannot refresh while offline', 'warning');
            return;
        }

        try {
            this.showLoading(true);
            
            // Fetch fresh data from API
            const response = await fetch('/api/offline/cache/dashboard_summary', {
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            if (response.ok) {
                const result = await response.json();
                this.cachedData.dashboard_summary = result.data;
                
                // Cache the data
                if (window.offlineManager) {
                    await window.offlineManager.setCachedData('dashboard_summary', result.data);
                }
                
                this.lastUpdate = new Date();
                localStorage.setItem('dashboard_last_update', this.lastUpdate.toISOString());
                
                this.updateDashboard();
                this.showNotification('Dashboard updated successfully', 'success');
            } else {
                throw new Error('Failed to fetch data');
            }
        } catch (error) {
            console.error('Failed to refresh data:', error);
            this.showNotification('Failed to refresh data', 'error');
        } finally {
            this.showLoading(false);
        }
    }

    updateDashboard() {
        this.updateSummaryCards();
        this.updateRecentBills();
        this.updateBudgetOverview();
        this.updateLastUpdateTime();
        this.updateOfflineIndicators();
    }

    updateSummaryCards() {
        const data = this.cachedData.dashboard_summary;
        if (!data) return;

        // Update total bills
        const totalBillsEl = document.getElementById('totalBills');
        if (totalBillsEl && data.total_bills !== undefined) {
            totalBillsEl.textContent = data.total_bills;
        }

        // Update pending bills
        const pendingBillsEl = document.getElementById('pendingBills');
        if (pendingBillsEl && data.pending_bills !== undefined) {
            pendingBillsEl.textContent = data.pending_bills;
        }

        // Update budget amount
        const budgetAmountEl = document.getElementById('budgetAmount');
        if (budgetAmountEl && data.current_budget) {
            const amount = data.current_budget.total_amount || 0;
            budgetAmountEl.textContent = this.formatCurrency(amount);
        }
    }

    updateRecentBills() {
        const data = this.cachedData.dashboard_summary;
        if (!data || !data.recent_bills) return;

        const container = document.getElementById('recentBillsList');
        if (!container) return;

        container.innerHTML = '';

        if (data.recent_bills.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="bi bi-receipt fs-1"></i>
                    <p class="mt-2">No bills found</p>
                </div>
            `;
            return;
        }

        data.recent_bills.forEach(bill => {
            const billEl = this.createBillElement(bill);
            container.appendChild(billEl);
        });
    }

    createBillElement(bill) {
        const div = document.createElement('div');
        div.className = 'bill-item d-flex justify-content-between align-items-center p-3 border-bottom';
        
        const dueDate = new Date(bill.due_date);
        const isOverdue = dueDate < new Date() && bill.status === 'pending';
        const statusClass = isOverdue ? 'text-danger' : bill.status === 'paid' ? 'text-success' : 'text-warning';
        
        div.innerHTML = `
            <div class="bill-info">
                <h6 class="mb-1">${this.escapeHtml(bill.title)}</h6>
                <small class="text-muted">
                    Due: ${this.formatDate(dueDate)}
                    ${bill.category ? ` • ${bill.category}` : ''}
                </small>
            </div>
            <div class="bill-amount text-end">
                <div class="fw-bold">${this.formatCurrency(bill.amount)}</div>
                <small class="${statusClass}">
                    ${isOverdue ? 'Overdue' : bill.status.charAt(0).toUpperCase() + bill.status.slice(1)}
                </small>
            </div>
        `;

        // Add offline indicator if data is from offline storage
        if (!this.isOnline) {
            const offlineIndicator = document.createElement('small');
            offlineIndicator.className = 'data-offline-indicator';
            offlineIndicator.innerHTML = '<i class="bi bi-wifi-off"></i> Offline';
            div.querySelector('.bill-info').appendChild(offlineIndicator);
        }

        return div;
    }

    updateBudgetOverview() {
        const data = this.cachedData.dashboard_summary;
        if (!data || !data.current_budget) return;

        const container = document.getElementById('budgetOverview');
        if (!container) return;

        const budget = data.current_budget;
        const totalAmount = budget.total_amount || 0;
        const spentAmount = budget.spent_amount || 0;
        const remainingAmount = totalAmount - spentAmount;
        const spentPercentage = totalAmount > 0 ? (spentAmount / totalAmount) * 100 : 0;

        container.innerHTML = `
            <div class="budget-summary">
                <div class="d-flex justify-content-between mb-2">
                    <span>Total Budget</span>
                    <span class="fw-bold">${this.formatCurrency(totalAmount)}</span>
                </div>
                <div class="progress mb-2" style="height: 8px;">
                    <div class="progress-bar ${spentPercentage > 90 ? 'bg-danger' : spentPercentage > 70 ? 'bg-warning' : 'bg-success'}" 
                         style="width: ${Math.min(spentPercentage, 100)}%"></div>
                </div>
                <div class="d-flex justify-content-between small text-muted">
                    <span>Spent: ${this.formatCurrency(spentAmount)}</span>
                    <span>Remaining: ${this.formatCurrency(remainingAmount)}</span>
                </div>
            </div>
        `;
    }

    updateLastUpdateTime() {
        const lastUpdateEl = document.getElementById('lastUpdate');
        if (lastUpdateEl && this.lastUpdate) {
            const timeAgo = this.getTimeAgo(this.lastUpdate);
            lastUpdateEl.textContent = `Last updated ${timeAgo}`;
        }
    }

    updateOfflineIndicators() {
        const indicators = document.querySelectorAll('.offline-data-indicator');
        indicators.forEach(indicator => {
            indicator.style.display = this.isOnline ? 'none' : 'inline-flex';
        });
    }

    showOfflineIndicators() {
        // Add offline indicators to data sections
        const sections = document.querySelectorAll('.dashboard-section');
        sections.forEach(section => {
            let indicator = section.querySelector('.section-offline-indicator');
            if (!indicator) {
                indicator = document.createElement('div');
                indicator.className = 'section-offline-indicator alert alert-warning alert-sm mt-2';
                indicator.innerHTML = `
                    <i class="bi bi-wifi-off me-2"></i>
                    <small>Showing cached data from ${this.formatDate(this.lastUpdate)}</small>
                `;
                section.appendChild(indicator);
            }
        });
    }

    showLoading(show) {
        const loadingEl = document.getElementById('dashboardLoading');
        if (loadingEl) {
            loadingEl.style.display = show ? 'block' : 'none';
        }

        const refreshBtn = document.getElementById('refreshDashboard');
        if (refreshBtn) {
            refreshBtn.disabled = show;
            if (show) {
                refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise spin"></i> Refreshing...';
            } else {
                refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Refresh';
            }
        }
    }

    showNotification(message, type) {
        if (window.offlineManager) {
            window.offlineManager.showNotification(message, type);
        }
    }

    // Utility methods
    formatCurrency(amount) {
        return new Intl.NumberFormat('en-NG', {
            style: 'currency',
            currency: 'NGN',
            minimumFractionDigits: 0,
            maximumFractionDigits: 2
        }).format(amount || 0);
    }

    formatDate(date) {
        if (!date) return '';
        const d = new Date(date);
        return d.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: d.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined
        });
    }

    getTimeAgo(date) {
        const now = new Date();
        const diff = now - new Date(date);
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (days > 0) return `${days} day${days > 1 ? 's' : ''} ago`;
        if (hours > 0) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
        if (minutes > 0) return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
        return 'just now';
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    getCSRFToken() {
        return document.querySelector('meta[name="csrf-token"]')?.content || '';
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Only initialize if we're on a dashboard page
    if (document.getElementById('dashboardContainer') || document.querySelector('.dashboard-section')) {
        window.offlineDashboard = new OfflineDashboard();
    }
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = OfflineDashboard;
}