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
     * Build request headers with session IDs
     * @param {string} sessionId - Session ID to include
     * @param {object} options - Options object with optional headers
     * @returns {object} Headers object
     */
    buildHeaders(sessionId, options = {}) {
        const headers = { ...(options.headers || {}) };

        if (sessionId) {
            headers[this.SESSION_HEADER_NAME] = sessionId;
        }

        const adminSid = this.getAdminSessionId();
        if (adminSid) {
            headers[this.ADMIN_SESSION_HEADER_NAME] = adminSid;
        }

        return headers;
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
        const headers = this.buildHeaders(sid, options);
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
        const headers = this.buildHeaders(sid, {
            headers: { 'Content-Type': 'application/json' }
        });
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
     * Store admin session ID
     * @param {string} id - Admin session ID
     */
    setAdminSessionId(id) {
        localStorage.setItem(this.ADMIN_SESSION_STORAGE_KEY, id);
    },

    /**
     * Clear admin session
     */
    clearAdminSession() {
        localStorage.removeItem(this.ADMIN_SESSION_STORAGE_KEY);
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
        const headers = this.buildHeaders(null, {
            headers: { [this.ADMIN_SESSION_HEADER_NAME]: adminSid }
        });
        const response = await fetch(`${this.baseUrl}/api/admin/assets/${assetId}/meta`, {
            headers,
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
        const headers = this.buildHeaders(null, {
            headers: {
                'Content-Type': 'application/json',
                [this.ADMIN_SESSION_HEADER_NAME]: adminSid
            }
        });
        const response = await fetch(`${this.baseUrl}/api/admin/assets/${assetId}/meta`, {
            method: 'PATCH',
            headers,
            body: JSON.stringify(meta),
            credentials: 'include'
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update asset metadata');
        }
        return await response.json();
    },

    // ==================== Playlist Methods ====================

    /**
     * Get playlists (admin only)
     * @returns {Promise<object>}
     */
    async getPlaylists() {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/playlists`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to load playlists');
        }
        return await response.json();
    },

    /**
     * Get playlist by ID (admin only)
     * @param {string} playlistId
     * @returns {Promise<object>}
     */
    async getPlaylist(playlistId) {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/playlists/${playlistId}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to load playlist');
        }
        return await response.json();
    },

    /**
     * Create a new playlist (admin only)
     * @param {object} data
     * @returns {Promise<object>}
     */
    async createPlaylist(data) {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/playlists`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create playlist');
        }
        return await response.json();
    },

    /**
     * Update a playlist (admin only)
     * @param {string} playlistId
     * @param {object} data
     * @returns {Promise<object>}
     */
    async updatePlaylist(playlistId, data) {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/playlists/${playlistId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update playlist');
        }
        return await response.json();
    },

    /**
     * Delete a playlist (admin only)
     * @param {string} playlistId
     * @returns {Promise<void>}
     */
    async deletePlaylist(playlistId) {
        const response = await this.fetchWithAuth(`${this.baseUrl}/api/playlists/${playlistId}`, {
            method: 'DELETE'
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete playlist');
        }
    },

    /**
     * Get playlist items (admin only)
     * @param {string} playlistId
     * @returns {Promise<object>}
     */
    async getPlaylistItems(playlistId) {
        const response = await this.fetchWithAuth(
            `${this.baseUrl}/api/playlists/${playlistId}/items`
        );
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to load playlist items');
        }
        return await response.json();
    },

    /**
     * Add playlist item (admin only)
     * @param {string} playlistId
     * @param {object} data
     * @returns {Promise<object>}
     */
    async addPlaylistItem(playlistId, data) {
        const response = await this.fetchWithAuth(
            `${this.baseUrl}/api/playlists/${playlistId}/items`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            }
        );
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to add playlist item');
        }
        return await response.json();
    },

    /**
     * Update playlist item position (admin only)
     * @param {string} playlistId
     * @param {string} assetId
     * @param {number} position
     * @returns {Promise<object>}
     */
    async updatePlaylistItemPosition(playlistId, assetId, position) {
        const response = await this.fetchWithAuth(
            `${this.baseUrl}/api/playlists/${playlistId}/items/${assetId}`,
            {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ position })
            }
        );
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update playlist item');
        }
        return await response.json();
    },

    /**
     * Remove playlist item (admin only)
     * @param {string} playlistId
     * @param {string} assetId
     * @returns {Promise<void>}
     */
    async removePlaylistItem(playlistId, assetId) {
        const response = await this.fetchWithAuth(
            `${this.baseUrl}/api/playlists/${playlistId}/items/${assetId}`,
            {
                method: 'DELETE'
            }
        );
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to remove playlist item');
        }
    },

    /**
     * Get playlist context for play page (admin only)
     * @param {string} playlistId
     * @param {string} assetId
     * @returns {Promise<object>}
     */
    async getPlaylistContext(playlistId, assetId) {
        const response = await this.fetchWithAuth(
            `${this.baseUrl}/api/playlists/${playlistId}/context?asset_id=${assetId}`
        );
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to load playlist context');
        }
        return await response.json();
    },

    /**
     * Search assets (admin only)
     * @param {string} query
     * @returns {Promise<object>}
     */
    async searchAssets(query) {
        const response = await this.fetchWithAuth(
            `${this.baseUrl}/api/assets/search?q=${encodeURIComponent(query)}`
        );
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to search assets');
        }
        return await response.json();
    }
};

// Export for use in other modules
window.API = API;
