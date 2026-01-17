/**
 * Simple Hash Router for ShadowPartner
 * Supports routes: / (home), /upload, /admin, and /play/{asset_id}
 */

const Router = {
    routes: {},
    currentRoute: null,
    currentParams: {},
    /**
     * Optional hook invoked after each route change.
     * @type {(route: string, params: object) => void | null}
     */
    onRouteChange: null,

    /**
     * Register a route handler
     * @param {string} name - Route name
     * @param {Function} handler - Handler function(params)
     */
    register(name, handler) {
        this.routes[name] = handler;
    },

    /**
     * Parse current hash and return route info
     * @returns {{ route: string, params: object }}
     */
    parseHash() {
        const hash = window.location.hash.slice(1) || '/';
        const [path, queryString] = hash.split('?');
        const params = new URLSearchParams(queryString || '');
        const playlistId = params.get('playlist_id');

        // Match /play/{asset_id} (UUID format)
        const playMatch = path.match(/^\/play\/([a-f0-9-]{36})$/i);
        if (playMatch) {
            return { route: 'play', params: { assetId: playMatch[1], playlistId } };
        }

        // Match /upload route
        if (path === '/upload') {
            return { route: 'upload', params: {} };
        }

        // Match /admin route
        if (path === '/admin') {
            return { route: 'admin', params: {} };
        }

        // Default route (home page - TODO placeholder)
        return { route: 'home', params: {} };
    },

    /**
     * Normalize URLs that include index.html to keep routes consistent.
     */
    normalizeUrl() {
        if (!window.location.pathname.endsWith('/index.html')) {
            return;
        }

        const normalizedPath = window.location.pathname.replace(/\/index\.html$/, '/');
        const newUrl = normalizedPath + window.location.search + window.location.hash;
        window.history.replaceState(null, '', newUrl);
    },

    /**
     * Navigate to a path
     * @param {string} path - Path to navigate to (e.g., '/play/uuid')
     */
    navigate(path) {
        window.location.hash = path;
    },

    /**
     * Go back to home
     */
    goHome() {
        this.navigate('/');
    },

    /**
     * Go to upload page
     */
    goToUpload() {
        this.navigate('/upload');
    },

    /**
     * Go to admin page
     */
    goToAdmin() {
        this.navigate('/admin');
    },

    /**
     * Go to play page
     * @param {string} assetId - Asset UUID
     */
    goToPlay(assetId, options = {}) {
        const searchParams = new URLSearchParams();
        if (options.playlistId) {
            searchParams.set('playlist_id', options.playlistId);
        }
        const suffix = searchParams.toString();
        const path = suffix ? `/play/${assetId}?${suffix}` : `/play/${assetId}`;
        this.navigate(path);
    },

    /**
     * Handle route change
     */
    handleRoute() {
        const { route, params } = this.parseHash();
        this.currentRoute = route;
        this.currentParams = params;

        console.log('[Router] Route changed:', route, params);

        if (this.routes[route]) {
            this.routes[route](params);
        }

        if (this.onRouteChange) {
            this.onRouteChange(route, params);
        }
    },

    /**
     * Initialize router and start listening for hash changes
     */
    init() {
        this.normalizeUrl();
        window.addEventListener('hashchange', () => this.handleRoute());
        this.handleRoute(); // Handle initial route
    },

    /**
     * Check if current route is play page
     * @returns {boolean}
     */
    isPlayPage() {
        return this.currentRoute === 'play';
    },

    /**
     * Check if current route is home page
     * @returns {boolean}
     */
    isHomePage() {
        return this.currentRoute === 'home';
    },

    /**
     * Check if current route is upload page
     * @returns {boolean}
     */
    isUploadPage() {
        return this.currentRoute === 'upload';
    },

    /**
     * Check if current route is admin page
     * @returns {boolean}
     */
    isAdminPage() {
        return this.currentRoute === 'admin';
    },

    /**
     * Get current asset ID (only valid on play page)
     * @returns {string|null}
     */
    getAssetId() {
        return this.currentParams.assetId || null;
    }
};

// Export for use in other modules
window.Router = Router;
