/**
 * Offline Forms Handler for FiCore Africa
 * Handles form submissions when offline and syncs when back online
 */

class OfflineFormsHandler {
    constructor() {
        this.forms = new Map();
        this.init();
    }

    init() {
        this.setupFormHandlers();
        this.setupValidation();
        console.log('Offline Forms Handler initialized');
    }

    setupFormHandlers() {
        // Handle all forms marked as offline-capable
        document.addEventListener('submit', (event) => {
            const form = event.target;
            if (form.hasAttribute('data-offline-capable')) {
                event.preventDefault();
                this.handleFormSubmission(form);
            }
        });

        // Setup form change listeners for auto-save
        document.querySelectorAll('form[data-offline-autosave]').forEach(form => {
            this.setupAutoSave(form);
        });
    }

    async handleFormSubmission(form) {
        const formData = new FormData(form);
        const formObject = Object.fromEntries(formData);
        
        // Add metadata
        formObject._timestamp = Date.now();
        formObject._formId = form.id || `form_${Date.now()}`;
        formObject._actionType = form.dataset.actionType || 'form_submission';

        if (window.offlineManager && window.offlineManager.isOffline()) {
            return await this.handleOfflineSubmission(form, formObject);
        } else {
            return await this.handleOnlineSubmission(form, formObject);
        }
    }

    async handleOfflineSubmission(form, formData) {
        try {
            // Store in offline manager
            const success = await window.offlineManager.storeOfflineAction({
                type: formData._actionType,
                url: form.action,
                method: form.method.toUpperCase(),
                body: JSON.stringify(formData),
                formId: form.id
            });

            if (success) {
                this.showFormSuccess(form, 'Data saved offline. Will sync when online.');
                this.markFormAsOffline(form);
                
                // Store locally for form restoration
                this.saveFormState(form, formData);
                
                // Reset form if specified
                if (form.dataset.resetAfterOffline === 'true') {
                    form.reset();
                }
            } else {
                this.showFormError(form, 'Failed to save data offline.');
            }

            return success;
        } catch (error) {
            console.error('Offline form submission failed:', error);
            this.showFormError(form, 'Failed to save data offline.');
            return false;
        }
    }

    async handleOnlineSubmission(form, formData) {
        try {
            this.showFormLoading(form, true);
            
            const response = await fetch(form.action, {
                method: form.method,
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(formData)
            });

            if (response.ok) {
                const result = await response.json();
                this.showFormSuccess(form, result.message || 'Data saved successfully!');
                
                // Clear any stored offline state
                this.clearFormState(form);
                
                // Reset form if specified
                if (form.dataset.resetAfterSubmit === 'true') {
                    form.reset();
                }
                
                // Redirect if specified
                if (result.redirect) {
                    setTimeout(() => {
                        window.location.href = result.redirect;
                    }, 1500);
                }
                
                return true;
            } else {
                const error = await response.json();
                this.showFormError(form, error.message || 'Failed to save data.');
                return false;
            }
        } catch (error) {
            console.error('Online form submission failed:', error);
            
            // If network error, try offline storage
            if (!navigator.onLine) {
                return await this.handleOfflineSubmission(form, formData);
            }
            
            this.showFormError(form, 'Network error. Please try again.');
            return false;
        } finally {
            this.showFormLoading(form, false);
        }
    }

    setupAutoSave(form) {
        let saveTimeout;
        const saveDelay = parseInt(form.dataset.autosaveDelay) || 2000;

        form.addEventListener('input', () => {
            clearTimeout(saveTimeout);
            saveTimeout = setTimeout(() => {
                this.autoSaveForm(form);
            }, saveDelay);
        });

        // Restore saved data on page load
        this.restoreFormState(form);
    }

    async autoSaveForm(form) {
        const formData = new FormData(form);
        const formObject = Object.fromEntries(formData);
        
        // Only save if form has meaningful data
        if (this.hasFormData(formObject)) {
            this.saveFormState(form, formObject);
            this.showAutoSaveIndicator(form);
        }
    }

    saveFormState(form, data) {
        const key = `form_state_${form.id || form.action}`;
        localStorage.setItem(key, JSON.stringify({
            data,
            timestamp: Date.now()
        }));
    }

    restoreFormState(form) {
        const key = `form_state_${form.id || form.action}`;
        const saved = localStorage.getItem(key);
        
        if (saved) {
            try {
                const { data, timestamp } = JSON.parse(saved);
                
                // Only restore if saved within last 24 hours
                if (Date.now() - timestamp < 24 * 60 * 60 * 1000) {
                    this.populateForm(form, data);
                    this.showFormRestored(form);
                }
            } catch (error) {
                console.error('Failed to restore form state:', error);
            }
        }
    }

    clearFormState(form) {
        const key = `form_state_${form.id || form.action}`;
        localStorage.removeItem(key);
    }

    populateForm(form, data) {
        Object.entries(data).forEach(([key, value]) => {
            if (key.startsWith('_')) return; // Skip metadata
            
            const field = form.querySelector(`[name="${key}"]`);
            if (field) {
                if (field.type === 'checkbox' || field.type === 'radio') {
                    field.checked = value === field.value;
                } else {
                    field.value = value;
                }
            }
        });
    }

    hasFormData(data) {
        return Object.values(data).some(value => 
            value && value.toString().trim().length > 0
        );
    }

    // UI Feedback Methods
    showFormLoading(form, loading) {
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
            if (loading) {
                submitBtn.disabled = true;
                submitBtn.dataset.originalText = submitBtn.textContent;
                submitBtn.innerHTML = '<i class="bi bi-arrow-clockwise spin"></i> Saving...';
            } else {
                submitBtn.disabled = false;
                submitBtn.textContent = submitBtn.dataset.originalText || 'Save';
            }
        }
    }

    showFormSuccess(form, message) {
        this.showFormMessage(form, message, 'success');
    }

    showFormError(form, message) {
        this.showFormMessage(form, message, 'error');
    }

    showFormMessage(form, message, type) {
        // Remove existing messages
        const existingMessage = form.querySelector('.form-message');
        if (existingMessage) {
            existingMessage.remove();
        }

        // Create new message
        const messageEl = document.createElement('div');
        messageEl.className = `form-message alert alert-${type === 'error' ? 'danger' : type}`;
        messageEl.innerHTML = `
            <i class="bi ${this.getMessageIcon(type)}"></i>
            <span>${message}</span>
        `;

        // Insert at top of form
        form.insertBefore(messageEl, form.firstChild);

        // Auto remove after 5 seconds
        setTimeout(() => {
            if (messageEl.parentElement) {
                messageEl.remove();
            }
        }, 5000);
    }

    showAutoSaveIndicator(form) {
        let indicator = form.querySelector('.autosave-indicator');
        if (!indicator) {
            indicator = document.createElement('div');
            indicator.className = 'autosave-indicator';
            indicator.innerHTML = '<i class="bi bi-check-circle"></i> Auto-saved';
            form.appendChild(indicator);
        }

        indicator.style.display = 'block';
        setTimeout(() => {
            indicator.style.display = 'none';
        }, 2000);
    }

    showFormRestored(form) {
        this.showFormMessage(form, 'Previous data restored from auto-save', 'info');
    }

    markFormAsOffline(form) {
        form.classList.add('form-offline-mode');
        setTimeout(() => {
            form.classList.remove('form-offline-mode');
        }, 3000);
    }

    getMessageIcon(type) {
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

    setupValidation() {
        // Add client-side validation for offline forms
        document.querySelectorAll('form[data-offline-capable]').forEach(form => {
            form.addEventListener('submit', (event) => {
                if (!this.validateForm(form)) {
                    event.preventDefault();
                    event.stopPropagation();
                }
            });
        });
    }

    validateForm(form) {
        let isValid = true;
        const requiredFields = form.querySelectorAll('[required]');
        
        requiredFields.forEach(field => {
            if (!field.value.trim()) {
                this.showFieldError(field, 'This field is required');
                isValid = false;
            } else {
                this.clearFieldError(field);
            }
        });

        return isValid;
    }

    showFieldError(field, message) {
        this.clearFieldError(field);
        
        const errorEl = document.createElement('div');
        errorEl.className = 'field-error text-danger small';
        errorEl.textContent = message;
        
        field.classList.add('is-invalid');
        field.parentNode.appendChild(errorEl);
    }

    clearFieldError(field) {
        field.classList.remove('is-invalid');
        const errorEl = field.parentNode.querySelector('.field-error');
        if (errorEl) {
            errorEl.remove();
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.offlineFormsHandler = new OfflineFormsHandler();
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = OfflineFormsHandler;
}