/**
 * Toast notification system composable.
 * Provides toast notifications with auto-dismiss and configurable types.
 */

let toastIdCounter = 0;

/**
 * Toast notification composable.
 * @returns {Object} Toast state and methods
 */
function useToast() {
    const toasts = Vue.ref([]);

    /**
     * Show a toast notification.
     * @param {string} message - The message to display
     * @param {string} type - 'success' | 'error' | 'warning' | 'info'
     * @param {number} duration - Auto-dismiss duration in ms (0 for no auto-dismiss)
     * @returns {number} Toast ID
     */
    const showToast = (message, type = 'info', duration = 3000) => {
        const id = toastIdCounter++;
        const toast = { id, message, type, duration };
        toasts.value.push(toast);

        // Auto-dismiss after duration
        if (duration > 0) {
            setTimeout(() => {
                removeToast(id);
            }, duration);
        }

        return id;
    };

    /**
     * Remove a toast notification.
     * @param {number} id - Toast ID to remove
     */
    const removeToast = (id) => {
        const index = toasts.value.findIndex(t => t.id === id);
        if (index !== -1) {
            toasts.value.splice(index, 1);
        }
    };

    /**
     * Get SVG icon for toast type.
     * @param {string} type - Toast type
     * @returns {string} SVG HTML
     */
    const toastIcon = (type) => {
        const icons = {
            success: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>',
            error: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>',
            warning: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>',
            info: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>'
        };
        return icons[type] || icons.info;
    };

    /**
     * Get CSS classes for toast type.
     * @param {string} type - Toast type
     * @returns {string} CSS class string
     */
    const toastClasses = (type) => {
        const baseClasses = 'pointer-events-auto shadow-lg rounded-lg px-4 py-3 flex items-center gap-3 min-w-[300px] max-w-md transition-all';
        const typeClasses = {
            success: 'bg-green-50 border-l-4 border-green-500 text-green-800',
            error: 'bg-red-50 border-l-4 border-red-500 text-red-800',
            warning: 'bg-yellow-50 border-l-4 border-yellow-500 text-yellow-800',
            info: 'bg-blue-50 border-l-4 border-blue-500 text-blue-800'
        };
        return `${baseClasses} ${typeClasses[type] || typeClasses.info}`;
    };

    return {
        toasts,
        showToast,
        removeToast,
        toastIcon,
        toastClasses
    };
}

// Attach to global scope for use in app.js
window.useToast = useToast;
