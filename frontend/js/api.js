/**
 * API Module for ShadowPartner
 * Encapsulates all API calls and session management
 */

const API = {
    baseUrl: 'http://localhost:8000',
    sessionId: null,
    SESSION_STORAGE_KEY: 'shadowpartner_session_id',
    SESSION_HEADER_NAME: 'X-Session-Id',
    ADMIN_SESSION_STORAGE_KEY: 'shadowpartner_admin_session_id',
    ADMIN_SESSION_HEADER_NAME: 'X-Admin-Session-Id',

    /**
     * Set API base URL
     * @param {string} url - Base URL
     */
    setBaseUrl(url) {
        this.baseUrl = url.replace(/\/$/, '');
    },

    /**
     * Get stored session ID
     * @returns {string|null}
     */
    getSessionId() {
        return localStorage.getItem(this.SESSION_STORAGE_KEY);
    },

    /**
     * Store session ID
     * @param {string} id - Session ID
     */
    setSessionId(id) {
        localStorage.setItem(this.SESSION_STORAGE_KEY, id);
        this.sessionId = id;
    },

    /**
     * Clear session
     */
    clearSession() {
        localStorage.removeItem(this.SESSION_STORAGE_KEY);
        this.sessionId = null;
    },

    /**
     * Ensure session exists, create if needed
     * @param {boolean} forceRefresh - Force create new session
     * @returns {Promise<string>} Session ID
     */
    async ensureSession(forceRefresh = false) {
        if (!forceRefresh) {
            const existing = this.getSessionId();
            if (existing) {
                this.sessionId = existing;
                return existing;
            }
        } else {
            this.clearSession();
        }

        const response = await fetch(`${this.baseUrl}/api/session`, {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            this.setSessionId(data.session_id);
            return data.session_id;
        }
        throw new Error('Failed to create session');
    },

    /**
     * Fetch with automatic session handling
     * @param {string} url - URL to fetch
     * @param {object} options - Fetch options
     * @param {boolean} retryOnAuth - Retry on 401
     * @returns {Promise<Response>}
     */
    async fetchWithAuth(url, options = {}, retryOnAuth = true) {
        const sid = await this.ensureSession();
        const headers = {
            ...(options.headers || {}),
            [this.SESSION_HEADER_NAME]: sid
        };
        // Add admin session header if available
        const adminSid = this.getAdminSessionId();
        if (adminSid) {
            headers[this.ADMIN_SESSION_HEADER_NAME] = adminSid;
        }
        const response = await fetch(url, { ...options, headers, credentials: 'include' });

        if (response.status === 401 && retryOnAuth) {
            console.log('[API] Session expired, refreshing...');
            await this.ensureSession(true);
            return this.fetchWithAuth(url, options, false);
        }
        return response;
    },

    /**
     * Check backend health
     * @returns {Promise<object>}
     */
    async checkHealth() {
        const response = await fetch(`${this.baseUrl}/health`, { credentials: 'include' });
        if (response.ok) {
            return await response.json();
        }
        throw new Error('Backend health check failed');
    },

    /**
     * Get asset details (public endpoint for play page)
     * @param {string} assetId - Asset UUID
     * @returns {Promise<object>}
     */
    async getAsset(assetId) {
        const response = await fetch(`${this.baseUrl}/api/assets/${assetId}`);
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('Asset not found');
            }
            throw new Error(`Failed to load asset: ${response.status}`);
        }
        return await response.json();
    },

    /**
     * Get list of processed assets for home page
     * @param {number} limit - Max items to return
     * @param {number} offset - Items to skip
     * @returns {Promise<{items: Array, total: number}>}
     */
    async getAssets(limit = 20, offset = 0) {
        const response = await fetch(
            `${this.baseUrl}/api/assets/list?limit=${limit}&offset=${offset}`
        );
        if (!response.ok) {
            throw new Error(`Failed to load assets: ${response.status}`);
        }
        return await response.json();
    },

    /**
     * Get stream URL for uploaded assets
     * @param {string} assetId - Asset UUID
     * @returns {string}
     */
    getStreamUrl(assetId) {
        return `${this.baseUrl}/api/assets/${assetId}/stream`;
    },

    /**
     * Get task status
     * @param {string} taskId - Task ID
     * @returns {Promise<object>}
     */
    async getTaskStatus(taskId) {
        const response = await fetch(`${this.baseUrl}/api/status/${taskId}`);
        if (!response.ok) {
            throw new Error(`Task not found: ${taskId}`);
        }
        return await response.json();
    },

    /**
     * Process YouTube video
     * @param {string} url - YouTube URL
     * @returns {Promise<object>}
     */
    async processVideo(url) {
        const sid = await this.ensureSession();
        const headers = {
            'Content-Type': 'application/json',
            [this.SESSION_HEADER_NAME]: sid
        };
        // Add admin session header if available
        const adminSid = this.getAdminSessionId();
        if (adminSid) {
            headers[this.ADMIN_SESSION_HEADER_NAME] = adminSid;
        }
        const response = await fetch(`${this.baseUrl}/api/process`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ url }),
            credentials: 'include'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to process video');
        }
        return await response.json();
    },

    // ==================== Admin Session Methods ====================

    /**
     * Get stored admin session ID
     * @returns {string|null}
     */
    getAdminSessionId() {
        return localStorage.getItem(this.ADMIN_SESSION_STORAGE_KEY);
    },

    /**
     * Check if admin session exists
     * @returns {boolean}
     */
    hasAdminSession() {
        return !!this.getAdminSessionId();
    },

    /**
     * Get asset metadata (admin only)
     * @param {string} assetId - Asset UUID
     * @returns {Promise<object>}
     */
    async getAssetMeta(assetId) {
        const adminSid = this.getAdminSessionId();
        if (!adminSid) {
            throw new Error('Admin session required');
        }
        const response = await fetch(`${this.baseUrl}/api/admin/assets/${assetId}/meta`, {
            headers: {
                [this.ADMIN_SESSION_HEADER_NAME]: adminSid
            },
            credentials: 'include'
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to get asset metadata');
        }
        return await response.json();
    },

    /**
     * Update asset metadata (admin only)
     * @param {string} assetId - Asset UUID
     * @param {object} meta - Metadata to update (title, description)
     * @returns {Promise<object>}
     */
    async updateAssetMeta(assetId, meta) {
        const adminSid = this.getAdminSessionId();
        if (!adminSid) {
            throw new Error('Admin session required');
        }
        const response = await fetch(`${this.baseUrl}/api/admin/assets/${assetId}/meta`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                [this.ADMIN_SESSION_HEADER_NAME]: adminSid
            },
            body: JSON.stringify(meta),
            credentials: 'include'
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update asset metadata');
        }
        return await response.json();
    }
};

// Export for use in other modules
window.API = API;
