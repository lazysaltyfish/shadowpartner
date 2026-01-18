/**
 * Custom confirm dialog composable.
 * Provides a promise-based confirm dialog replacement for native confirm().
 */

/**
 * Custom confirm dialog composable.
 * @returns {Object} Dialog state and methods
 */
function useConfirmDialog() {
    const confirmDialog = Vue.ref({
        show: false,
        title: '',
        message: '',
        confirmText: 'Confirm',
        cancelText: 'Cancel',
        type: 'danger', // 'danger' | 'info'
        _resolve: null
    });

    /**
     * Show a custom confirm dialog.
     * @param {Object} options - Dialog options
     * @returns {Promise<boolean>} - True if confirmed, false if cancelled
     */
    const showConfirm = (options) => {
        return new Promise((resolve) => {
            console.log('[Debug] showConfirm called with:', options);
            confirmDialog.value = {
                show: true,
                title: options.title || 'Confirm',
                message: options.message || '',
                confirmText: options.confirmText || 'Confirm',
                cancelText: options.cancelText || 'Cancel',
                type: options.type || 'info',
                _resolve: resolve
            };
            console.log('[Debug] confirmDialog.value.show:', confirmDialog.value.show);
        });
    };

    /**
     * Handle confirm button click.
     */
    const handleConfirmOk = () => {
        if (confirmDialog.value._resolve) {
            confirmDialog.value._resolve(true);
        }
        confirmDialog.value.show = false;
    };

    /**
     * Handle cancel button click.
     */
    const handleConfirmCancel = () => {
        if (confirmDialog.value._resolve) {
            confirmDialog.value._resolve(false);
        }
        confirmDialog.value.show = false;
    };

    return {
        confirmDialog,
        showConfirm,
        handleConfirmOk,
        handleConfirmCancel
    };
}

// Attach to global scope for use in app.js
window.useConfirmDialog = useConfirmDialog;
