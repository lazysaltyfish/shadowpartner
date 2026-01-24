/**
 * Backend connection and session management composable.
 * Handles API base URL resolution, health checks, and auth session management.
 */

const SESSION_STORAGE_KEY = 'shadowpartner_session_id';
const SESSION_HEADER_NAME = 'X-Session-Id';

/**
 * Backend and session management composable.
 * @returns {Object} Backend state and methods
 */
function useBackend() {
    const apiBaseUrl = Vue.ref('http://localhost:8000');
    const apiReady = Vue.ref(false);
    const sessionId = Vue.ref(null);

    const backendStatus = Vue.ref({
        online: false,
        lastCheck: null,
        details: null
    });

    // AbortController for canceling requests on page unload
    let abortController = new AbortController();
    let healthCheckIntervalId = null;

    /**
     * Resolve the backend base URL and initialize the API client.
     *
     * Rules:
     * - No port in URL (e.g., https://example.com) -> same-origin deployment
     * - With port (e.g., http://localhost:3000) -> backend on port 8000
     * - Codespaces/Gitpod -> port-swapped backend
     */
    const resolveApiBaseUrl = () => {
        let baseUrl = 'http://localhost:8000';
        const hostname = window.location.hostname;
        const port = window.location.port;
        const hasPort = port !== '';

        console.log('[Debug] Resolving API URL:', { hostname, port, hasPort });

        // Codespaces & Gitpod environment (port-swapped)
        if (hostname.includes('github.dev') || hostname.includes('gitpod.io')) {
            const portRegex = /-([0-9]+)(?=\.app\.github\.dev|\.preview\.app\.github\.dev|\.gitpod\.io)/;
            const match = hostname.match(portRegex);
            if (match) {
                baseUrl = `https://${hostname.replace(`-${match[1]}`, '-8000')}`;
            } else if (hostname.includes('-8080')) {
                baseUrl = `https://${hostname.replace('-8080', '-8000')}`;
            }
        }
        // No explicit port: same-origin deployment (Caddy reverse proxy)
        else if (!hasPort) {
            baseUrl = window.location.origin;
        }
        // Has port: backend on 8000 (dev/LAN setup)
        else if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
            baseUrl = `${window.location.protocol}//${hostname}:8000`;
        }
        // localhost:3000 -> localhost:8000 (default baseUrl)

        console.log('[Debug] Resolved API URL:', baseUrl);
        apiBaseUrl.value = baseUrl;
        API.setBaseUrl(apiBaseUrl.value);
        localStorage.removeItem('shadowpartner_api_url');
        apiReady.value = true;
    };

    /**
     * Update backend health indicator only.
     * @returns {Promise<void>}
     */
    const checkBackendHealth = async () => {
        try {
            console.log('Checking backend health at:', apiBaseUrl.value);
            const response = await fetch(`${apiBaseUrl.value}/health`, {
                credentials: 'include'
            });
            if (response.ok) {
                const healthData = await response.json();
                backendStatus.value = {
                    online: true,
                    lastCheck: new Date(),
                    details: healthData
                };
            } else {
                throw new Error('Backend returned non-200');
            }
        } catch (e) {
            console.error('Backend health check failed:', e);
            backendStatus.value = { online: false, lastCheck: new Date(), details: null };
        }
    };

    /**
     * Get session ID from localStorage.
     * @returns {string|null}
     */
    const getSessionId = () => {
        return localStorage.getItem(SESSION_STORAGE_KEY);
    };

    /**
     * Set session ID in localStorage and state.
     * @param {string} id
     */
    const setSessionId = (id) => {
        localStorage.setItem(SESSION_STORAGE_KEY, id);
        sessionId.value = id;
    };

    /**
     * Clear session from localStorage and state.
     */
    const clearSession = () => {
        localStorage.removeItem(SESSION_STORAGE_KEY);
        sessionId.value = null;
    };

    /**
     * Ensure an active session exists, creating one if needed.
     * @param {boolean} forceRefresh - Force creation of a new session
     * @returns {Promise<string>} Session ID
     */
    const ensureSession = async (forceRefresh = false) => {
        if (!forceRefresh) {
            const existingSession = getSessionId();
            if (existingSession) {
                sessionId.value = existingSession;
                return existingSession;
            }
        } else {
            // Clear existing session before refreshing
            clearSession();
        }

        const response = await fetch(`${apiBaseUrl.value}/api/session`, {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            setSessionId(data.session_id);
            return data.session_id;
        } else {
            throw new Error('Failed to create session');
        }
    };

    /**
     * Handle expired session by clearing and letting caller retry.
     */
    const handleSessionExpired = () => {
        clearSession();
    };

    /**
     * Build headers with session ID.
     * @param {string} sid - Session ID
     * @returns {Object} Headers object
     */
    const buildSessionHeaders = (sid) => {
        const headers = {
            [SESSION_HEADER_NAME]: sid
        };
        // Add admin session header if available
        const adminSid = API.getAdminSessionId();
        if (adminSid) {
            headers[API.ADMIN_SESSION_HEADER_NAME] = adminSid;
        }
        return headers;
    };

    /**
     * Fetch with automatic session refresh on 401.
     * @param {string} url - Request URL
     * @param {Object} options - Fetch options
     * @param {boolean} retryOnAuth - Whether to retry on 401
     * @returns {Promise<Response>}
     */
    const fetchWithAuth = async (url, options = {}, retryOnAuth = true) => {
        const sid = await ensureSession();
        const headers = { ...(options.headers || {}), ...buildSessionHeaders(sid) };
        const response = await fetch(url, { ...options, headers, credentials: 'include' });

        if (response.status === 401 && retryOnAuth) {
            console.log('[Debug] Session expired, refreshing and retrying...');
            await ensureSession(true);
            return fetchWithAuth(url, options, false);
        }
        return response;
    };

    /**
     * Build admin headers if admin session exists.
     * @returns {Object} Headers object
     */
    const buildAdminHeaders = () => {
        const adminSession = API.getAdminSessionId();
        if (!adminSession) {
            return {};
        }
        return { [API.ADMIN_SESSION_HEADER_NAME]: adminSession };
    };

    /**
     * Initialize backend connection and start health checks.
     */
    const initBackend = () => {
        resolveApiBaseUrl();

        // Health check runs in background (non-blocking)
        checkBackendHealth();
        // Poll every 30 seconds
        healthCheckIntervalId = setInterval(checkBackendHealth, 30000);
    };

    /**
     * Cleanup timers and abort in-flight requests.
     */
    const cleanup = () => {
        abortController.abort();
        if (healthCheckIntervalId) clearInterval(healthCheckIntervalId);
    };

    // Cleanup on unmount
    Vue.onUnmounted(() => {
        cleanup();
    });

    const appReady = Vue.computed(() => apiReady.value);

    return {
        // State
        apiBaseUrl,
        apiReady,
        backendStatus,
        sessionId,
        appReady,

        // Methods
        resolveApiBaseUrl,
        checkBackendHealth,
        initBackend,
        cleanup,

        // Session management
        getSessionId,
        setSessionId,
        clearSession,
        ensureSession,
        handleSessionExpired,
        buildSessionHeaders,
        fetchWithAuth,
        buildAdminHeaders
    };
}

// Attach to global scope for use in app.js
window.useBackend = useBackend;
