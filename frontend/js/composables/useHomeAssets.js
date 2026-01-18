/**
 * Home page asset loading composable.
 * Handles asset listing with pagination (infinite scroll).
 */

const HOME_PAGE_SIZE = 20;

/**
 * Home page assets composable.
 * @returns {Object} Home assets state and methods
 */
function useHomeAssets() {
    const homeAssets = Vue.ref([]);
    const homeLoading = Vue.ref(false);
    const homeHasMore = Vue.ref(true);

    /**
     * Load assets for home page grid.
     * @param {boolean} append - If true, append to existing list (infinite scroll)
     * @returns {Promise<void>}
     */
    const loadHomeAssets = async (append = false) => {
        if (homeLoading.value) {
            return;
        }
        homeLoading.value = true;
        try {
            const offset = append ? homeAssets.value.length : 0;
            const data = await API.getAssets(HOME_PAGE_SIZE, offset);
            if (append) {
                homeAssets.value = [...homeAssets.value, ...data.items];
            } else {
                homeAssets.value = data.items;
            }
            homeHasMore.value = homeAssets.value.length < data.total;
        } catch (e) {
            console.error('[Home] Failed to load assets:', e);
        } finally {
            homeLoading.value = false;
        }
    };

    /**
     * Reset home page state.
     */
    const resetHomeAssets = () => {
        homeAssets.value = [];
        homeHasMore.value = true;
    };

    return {
        homeAssets,
        homeLoading,
        homeHasMore,
        loadHomeAssets,
        resetHomeAssets
    };
}

// Attach to global scope for use in app.js
window.useHomeAssets = useHomeAssets;
