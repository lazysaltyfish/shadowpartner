const { createApp, ref, reactive, onMounted, onUnmounted, nextTick, computed, watch } = Vue;

createApp({
    setup() {
        const videoUrl = ref('');
        const loading = ref(false);
        const videoData = ref(null);
        const player = ref(null);
        const currentTime = ref(0);
        const currentSegmentIndex = ref(-1);
        const segmentRefs = ref({});
        const subtitleContainer = ref(null);
        const selectedFile = ref(null);
        const selectedSubtitleFile = ref(null);
        const fileInput = ref(null);
        const subtitleInput = ref(null);
        const warnings = ref([]);
        const isFileMode = ref(false); // New state to track if we're using file or URL
        const contextRange = ref(2); // Number of segments to show before and after current
        const backendStatus = ref({
            online: false,
            lastCheck: null,
            details: null
        });
        const taskStatus = ref(null); // { status: 'pending', progress: 0, message: '' }
        const apiBaseUrl = ref('http://localhost:8000');
        const apiReady = ref(false);
        const routeReady = ref(false);
        const appReady = computed(() => apiReady.value && routeReady.value);
        const sessionId = ref(null);
        const SESSION_STORAGE_KEY = 'shadowpartner_session_id';
        const SESSION_HEADER_NAME = 'X-Session-Id';

        // Router state
        const currentRoute = ref('home'); // 'home' | 'upload' | 'play'
        const playPageData = ref(null); // Asset data for play page
        const playPageLoading = ref(false);
        const playPageError = ref(null);
        const playlistContext = ref(null);
        const playlistContextLoading = ref(false);

        // Home page state
        const homeAssets = ref([]);
        const homeLoading = ref(false);
        const homeHasMore = ref(true);
        const HOME_PAGE_SIZE = 20;

        const dictation = reactive({
            active: false,
            segmentIndex: 0,
            mode: 'listen',
            loop: false,
            userInput: '',
            isComposing: false,
            isPlaying: false,
            answersByIndex: {},
            statusByIndex: {},
            diffResult: [],
            currentScore: null,
            totalAttempts: 0,
            correctCount: 0,
        });
        const targetPauseTime = ref(null);

        // Admin panel state (SPA)
        const adminSession = ref(API.getAdminSessionId());
        const adminLoading = ref(false);
        const adminError = ref(null);
        const adminActiveTab = ref('users');
        const adminUsers = ref([]);
        const adminAssets = ref([]);
        const adminSubtitleTracks = ref([]);
        const adminShowDeleteModal = ref(false);
        const adminDeleteTarget = ref({ type: '', id: '', identifier: '' });
        const adminDeleting = ref(false);
        const adminLoginForm = ref({ username: '', password: '' });
        const adminShowEditModal = ref(false);
        const adminEditForm = ref({ assetId: '', title: '', description: '' });
        const adminEditSaving = ref(false);
        const adminPlaylists = ref([]);
        const adminActivePlaylist = ref(null);
        const adminPlaylistItems = ref([]);
        const adminPlaylistView = ref('list');
        const adminPlaylistModalOpen = ref(false);
        const adminPlaylistForm = ref({ id: null, title: '', description: '', cover_image: '' });
        const adminPlaylistSaving = ref(false);
        const adminPlaylistSearchOpen = ref(false);
        const adminPlaylistSearchQuery = ref('');
        const adminPlaylistSearchResults = ref([]);
        const adminPlaylistSearchLoading = ref(false);

        // Admin mode state
        const isAdminMode = computed(() => !!adminSession.value);
        const showEditModal = ref(false);
        const editForm = ref({ assetId: '', title: '', description: '' });
        const editSaving = ref(false);

        // AbortController for canceling requests on page unload
        let abortController = new AbortController();
        let pollTimeoutId = null;
        let healthCheckIntervalId = null;

        /**
         * Resolve the backend base URL and initialize the API client.
         */
        const resolveApiBaseUrl = () => {
            let baseUrl = 'http://localhost:8000';

            // Codespaces & Remote Environment Handling
            console.log('[Debug] Current Hostname:', window.location.hostname);

            if (window.location.hostname.includes('github.dev') || window.location.hostname.includes('gitpod.io')) {
                // GitHub Codespaces: port 8080 is usually the frontend, backend on 8000
                const currentHost = window.location.hostname;
                console.log('[Debug] Detected Codespace/Gitpod environment');

                // Attempt to replace ANY port number in the hostname with -8000
                // Regex looks for -<digits> followed by the domain suffix or end of string
                // Typical format: name-8080.app.github.dev
                const portRegex = /-([0-9]+)(?=\.app\.github\.dev|\.preview\.app\.github\.dev|\.gitpod\.io)/;
                const match = currentHost.match(portRegex);

                if (match) {
                    const currentPort = match[1];
                    console.log(`[Debug] Detected running on port: ${currentPort}`);
                    baseUrl = `https://${currentHost.replace(`-${currentPort}`, '-8000')}`;
                } else if (currentHost.includes('-8080')) {
                    // Fallback for simple match
                    baseUrl = `https://${currentHost.replace('-8080', '-8000')}`;
                } else {
                    console.warn('[Debug] Codespaces detected but port pattern not matched. Defaulting to localhost:8000. Host:', currentHost);
                }
            } else if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
                // Generic remote handling (e.g. LAN)
                baseUrl = window.location.protocol + '//' + window.location.hostname + ':8000';
            }

            apiBaseUrl.value = baseUrl;
            API.setBaseUrl(apiBaseUrl.value);
            localStorage.removeItem('shadowpartner_api_url');
            apiReady.value = true;
        };

        // Backend Health Check
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

        // Session Management
        const getSessionId = () => {
            return localStorage.getItem(SESSION_STORAGE_KEY);
        };

        const setSessionId = (id) => {
            localStorage.setItem(SESSION_STORAGE_KEY, id);
            sessionId.value = id;
        };

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

        const clearSession = () => {
            localStorage.removeItem(SESSION_STORAGE_KEY);
            sessionId.value = null;
        };

        const handleSessionExpired = () => {
            clearSession();
            // Don't reload page - let the caller handle retry
        };

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

        // Fetch with automatic session refresh on 401
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

        const buildAdminHeaders = () => {
            if (!adminSession.value) {
                return {};
            }
            return { [API.ADMIN_SESSION_HEADER_NAME]: adminSession.value };
        };

        const clearAdminState = () => {
            API.clearAdminSession();
            adminSession.value = null;
            adminUsers.value = [];
            adminAssets.value = [];
            adminSubtitleTracks.value = [];
            adminPlaylists.value = [];
            adminActivePlaylist.value = null;
            adminPlaylistItems.value = [];
            adminPlaylistView.value = 'list';
            adminPlaylistModalOpen.value = false;
            adminPlaylistForm.value = { id: null, title: '', description: '', cover_image: '' };
            adminPlaylistSaving.value = false;
            adminPlaylistSearchOpen.value = false;
            adminPlaylistSearchQuery.value = '';
            adminPlaylistSearchResults.value = [];
            adminPlaylistSearchLoading.value = false;
            adminShowDeleteModal.value = false;
            adminDeleteTarget.value = { type: '', id: '', identifier: '' };
            adminShowEditModal.value = false;
            adminEditForm.value = { assetId: '', title: '', description: '' };
        };

        const adminFormatDate = (dateString) => {
            const date = new Date(dateString);
            return date.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        };

        const adminHandleLogin = async () => {
            adminLoading.value = true;
            adminError.value = null;

            try {
                const response = await fetch(`${apiBaseUrl.value}/api/admin/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(adminLoginForm.value)
                });

                if (response.ok) {
                    const data = await response.json();
                    API.setAdminSessionId(data.session_id);
                    adminSession.value = data.session_id;
                    adminLoginForm.value = { username: '', password: '' };
                    await adminLoadData();
                } else {
                    const errorData = await response.json();
                    adminError.value = errorData.detail || 'Login failed';
                }
            } catch (e) {
                console.error('Admin login error:', e);
                adminError.value = e.message || 'Login failed';
            } finally {
                adminLoading.value = false;
            }
        };

        const adminHandleLogout = async () => {
            try {
                if (adminSession.value) {
                    await fetch(`${apiBaseUrl.value}/api/admin/logout`, {
                        method: 'POST',
                        headers: buildAdminHeaders()
                    });
                }
            } catch (e) {
                console.error('Admin logout error:', e);
            } finally {
                clearAdminState();
                adminError.value = null;
            }
        };

        const adminLoadData = async (markReady = false) => {
            if (!adminSession.value) {
                return;
            }

            adminLoading.value = true;
            adminError.value = null;

            try {
                const headers = buildAdminHeaders();

                if (adminActiveTab.value === 'users') {
                    const response = await fetch(`${apiBaseUrl.value}/api/admin/users`, { headers });
                    if (response.ok) {
                        adminUsers.value = await response.json();
                    } else if (response.status === 401) {
                        clearAdminState();
                    }
                } else if (adminActiveTab.value === 'assets') {
                    const response = await fetch(`${apiBaseUrl.value}/api/admin/assets`, { headers });
                    if (response.ok) {
                        adminAssets.value = await response.json();
                    } else if (response.status === 401) {
                        clearAdminState();
                    }
                } else if (adminActiveTab.value === 'subtitle-tracks') {
                    const response = await fetch(`${apiBaseUrl.value}/api/admin/subtitle-tracks`, { headers });
                    if (response.ok) {
                        adminSubtitleTracks.value = await response.json();
                    } else if (response.status === 401) {
                        clearAdminState();
                    }
                } else if (adminActiveTab.value === 'playlists') {
                    const response = await fetch(`${apiBaseUrl.value}/api/playlists`, { headers });
                    if (response.ok) {
                        const data = await response.json();
                        adminPlaylists.value = data.items || [];
                    } else if (response.status === 401) {
                        clearAdminState();
                    }
                }
            } catch (e) {
                console.error('Admin load data error:', e);
                adminError.value = e.message || 'Failed to load data';
            } finally {
                adminLoading.value = false;
                if (markReady) {
                    routeReady.value = true;
                }
            }
        };

        const adminConfirmDelete = (type, id, identifier) => {
            adminDeleteTarget.value = { type, id, identifier };
            adminShowDeleteModal.value = true;
        };

        const adminExecuteDelete = async () => {
            adminDeleting.value = true;

            try {
                const { type, id } = adminDeleteTarget.value;
                let endpoint = null;

                if (type === 'user') {
                    endpoint = `/api/admin/users/${id}`;
                } else if (type === 'asset') {
                    endpoint = `/api/admin/assets/${id}`;
                } else if (type === 'subtitle-track') {
                    endpoint = `/api/admin/subtitle-tracks/${id}`;
                } else if (type === 'playlist') {
                    endpoint = `/api/playlists/${id}`;
                }

                const response = await fetch(`${apiBaseUrl.value}${endpoint}`, {
                    method: 'DELETE',
                    headers: buildAdminHeaders()
                });

                if (response.ok) {
                    if (type === 'user') {
                        adminUsers.value = adminUsers.value.filter(u => u.id !== id);
                    } else if (type === 'asset') {
                        adminAssets.value = adminAssets.value.filter(a => a.id !== id);
                    } else if (type === 'subtitle-track') {
                        adminSubtitleTracks.value = adminSubtitleTracks.value.filter(t => t.id !== id);
                    } else if (type === 'playlist') {
                        adminPlaylists.value = adminPlaylists.value.filter(p => p.id !== id);
                        if (adminActivePlaylist.value && adminActivePlaylist.value.id === id) {
                            adminActivePlaylist.value = null;
                            adminPlaylistItems.value = [];
                            adminPlaylistView.value = 'list';
                        }
                    }
                    adminShowDeleteModal.value = false;
                } else if (response.status === 401) {
                    clearAdminState();
                } else {
                    const errorData = await response.json();
                    alert(errorData.detail || 'Delete failed');
                }
            } catch (e) {
                console.error('Admin delete error:', e);
                alert(e.message || 'Delete failed');
            } finally {
                adminDeleting.value = false;
            }
        };

        const adminOpenPlayPage = (asset) => {
            const appBaseUrl = new URL('./', window.location.href).href;
            window.open(`${appBaseUrl}#/play/${asset.id}`, '_blank');
        };

        const adminGoToUpload = () => {
            Router.goToUpload();
        };

        const adminOpenEditModal = async (asset) => {
            adminEditForm.value = {
                assetId: asset.id,
                title: '',
                description: ''
            };
            adminShowEditModal.value = true;

            try {
                const data = await API.getAssetMeta(asset.id);
                adminEditForm.value.title = data.title || '';
                adminEditForm.value.description = data.description || '';
            } catch (e) {
                console.error('Failed to fetch asset meta:', e);
            }
        };

        const adminSaveAssetMeta = async () => {
            adminEditSaving.value = true;
            try {
                await API.updateAssetMeta(adminEditForm.value.assetId, {
                    title: adminEditForm.value.title,
                    description: adminEditForm.value.description
                });
                adminShowEditModal.value = false;
                await adminLoadData();
            } catch (e) {
                console.error('Admin save error:', e);
                alert(e.message || 'Failed to save');
            } finally {
                adminEditSaving.value = false;
            }
        };

        const adminOpenPlaylistModal = (playlist = null) => {
            if (playlist) {
                adminPlaylistForm.value = {
                    id: playlist.id,
                    title: playlist.title || '',
                    description: playlist.description || '',
                    cover_image: playlist.cover_image || ''
                };
            } else {
                adminPlaylistForm.value = { id: null, title: '', description: '', cover_image: '' };
            }
            adminPlaylistModalOpen.value = true;
        };

        const adminSavePlaylist = async () => {
            adminPlaylistSaving.value = true;
            try {
                const payload = {
                    title: adminPlaylistForm.value.title,
                    description: adminPlaylistForm.value.description || null,
                    cover_image: adminPlaylistForm.value.cover_image || null
                };
                if (adminPlaylistForm.value.id) {
                    await API.updatePlaylist(adminPlaylistForm.value.id, payload);
                } else {
                    await API.createPlaylist(payload);
                }
                adminPlaylistModalOpen.value = false;
                await adminLoadData();
            } catch (e) {
                console.error('Admin playlist save error:', e);
                alert(e.message || 'Failed to save playlist');
            } finally {
                adminPlaylistSaving.value = false;
            }
        };

        const adminOpenPlaylistDetail = async (playlist) => {
            adminActivePlaylist.value = playlist;
            adminPlaylistView.value = 'detail';
            await adminLoadPlaylistItems(playlist.id);
        };

        const adminOpenPlaylistPlay = async (playlist) => {
            if (!playlist || !playlist.id) {
                return;
            }
            if (!playlist.item_count) {
                alert('Playlist is empty');
                return;
            }
            try {
                const data = await API.getPlaylistItems(playlist.id);
                const firstItem = data.items?.[0];
                if (!firstItem) {
                    alert('Playlist is empty');
                    return;
                }
                Router.goToPlay(firstItem.asset_id, { playlistId: playlist.id });
            } catch (e) {
                console.error('Failed to open playlist play page:', e);
                alert(e.message || 'Failed to open playlist');
            }
        };

        const adminLoadPlaylistItems = async (playlistId) => {
            try {
                const data = await API.getPlaylistItems(playlistId);
                adminPlaylistItems.value = data.items || [];
            } catch (e) {
                console.error('Failed to load playlist items:', e);
                alert(e.message || 'Failed to load playlist items');
            }
        };

        const adminBackToPlaylists = () => {
            adminActivePlaylist.value = null;
            adminPlaylistItems.value = [];
            adminPlaylistView.value = 'list';
        };

        const adminOpenPlaylistSearch = () => {
            adminPlaylistSearchOpen.value = true;
            adminPlaylistSearchQuery.value = '';
            adminPlaylistSearchResults.value = [];
        };

        const adminSearchPlaylistAssets = async () => {
            adminPlaylistSearchLoading.value = true;
            try {
                const data = await API.searchAssets(adminPlaylistSearchQuery.value || '');
                adminPlaylistSearchResults.value = data.items || [];
            } catch (e) {
                console.error('Playlist search failed:', e);
                alert(e.message || 'Search failed');
            } finally {
                adminPlaylistSearchLoading.value = false;
            }
        };

        const adminAddPlaylistAsset = async (asset) => {
            if (!adminActivePlaylist.value) {
                return;
            }
            try {
                await API.addPlaylistItem(adminActivePlaylist.value.id, {
                    asset_id: asset.id
                });
                await adminLoadPlaylistItems(adminActivePlaylist.value.id);
                adminPlaylistSearchOpen.value = false;
            } catch (e) {
                console.error('Failed to add playlist item:', e);
                alert(e.message || 'Failed to add item');
            }
        };

        const adminMovePlaylistItem = async (item, direction) => {
            if (!adminActivePlaylist.value) {
                return;
            }
            const newPosition = item.position + direction;
            if (newPosition < 0 || newPosition >= adminPlaylistItems.value.length) {
                return;
            }
            try {
                await API.updatePlaylistItemPosition(
                    adminActivePlaylist.value.id,
                    item.asset_id,
                    newPosition
                );
                await adminLoadPlaylistItems(adminActivePlaylist.value.id);
            } catch (e) {
                console.error('Failed to move playlist item:', e);
                alert(e.message || 'Failed to reorder item');
            }
        };

        const adminRemovePlaylistItem = async (item) => {
            if (!adminActivePlaylist.value) {
                return;
            }
            const confirmRemove = window.confirm(`Remove "${item.cached_title}"?`);
            if (!confirmRemove) {
                return;
            }
            try {
                await API.removePlaylistItem(adminActivePlaylist.value.id, item.asset_id);
                await adminLoadPlaylistItems(adminActivePlaylist.value.id);
            } catch (e) {
                console.error('Failed to remove playlist item:', e);
                alert(e.message || 'Failed to remove item');
            }
        };

        // Cleanup function
        /**
         * Cleanup timers and abort in-flight requests.
         */
        const cleanup = () => {
            abortController.abort();
            if (healthCheckIntervalId) clearInterval(healthCheckIntervalId);
            if (pollTimeoutId) clearTimeout(pollTimeoutId);
            if (window._pollInterval) clearInterval(window._pollInterval);
        };

        // Route handlers
        /**
         * Load assets for home page grid.
         * @param {boolean} append - If true, append to existing list (infinite scroll)
         */
        const loadHomeAssets = async (append = false, markReady = false) => {
            if (homeLoading.value) {
                if (markReady) {
                    routeReady.value = true;
                }
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
                if (markReady) {
                    routeReady.value = true;
                }
            }
        };

        /**
         * Load asset data for the play page and initialize the player.
         * @param {string} assetId
         * @returns {Promise<void>}
         */
        const loadPlaylistContext = async (playlistId, assetId) => {
            playlistContextLoading.value = true;
            try {
                playlistContext.value = await API.getPlaylistContext(playlistId, assetId);
            } catch (e) {
                console.warn('[Playlist] Failed to load context:', e);
                playlistContext.value = null;
            } finally {
                playlistContextLoading.value = false;
            }
        };

        /**
         * Load asset data for the play page and initialize the player.
         * @param {string} assetId
         * @param {string|null} playlistId
         * @returns {Promise<void>}
         */
        const loadPlayPage = async (assetId, playlistId = null) => {
            console.log('[Router] Loading play page for asset:', assetId);
            playPageLoading.value = true;
            playPageError.value = null;
            playPageData.value = null;
            playlistContext.value = null;
            playlistContextLoading.value = false;
            routeReady.value = true;

            // Reset dictation and playback state when loading new asset
            dictation.segmentIndex = 0;
            dictation.mode = 'listen';
            dictation.userInput = '';
            dictation.isPlaying = false;
            currentTime.value = 0;
            currentSegmentIndex.value = -1;

            try {
                const playlistPromise = playlistId
                    ? loadPlaylistContext(playlistId, assetId)
                    : Promise.resolve();
                const data = await API.getAsset(assetId);
                console.log('[loadPlayPage] Asset data loaded:', data);
                playPageData.value = data;
                playPageLoading.value = false; // Set before nextTick so DOM renders

                // Initialize player after DOM update
                nextTick(() => {
                    console.log('[loadPlayPage] nextTick callback executing');
                    const container = document.getElementById('youtube-player');
                    console.log('[loadPlayPage] Container element:', container);
                    if (!container) {
                        console.error('[loadPlayPage] Container not found!');
                        return;
                    }

                    const onTimeUpdate = (time) => {
                        currentTime.value = time;
                        updateActiveWords();

                        // Handle dictation loop
                        if (dictation.active && dictation.isPlaying) {
                            const segment = playPageData.value?.segments?.[dictation.segmentIndex];
                            if (segment && time >= segment.end) {
                                PlayerManager.seekTo(Math.max(0, segment.start - 0.3));
                                PlayerManager.play();
                            }
                        }
                    };

                    if (data.type === 'youtube') {
                        PlayerManager.initYouTube(data.identifier, container, {
                            onTimeUpdate: onTimeUpdate
                        });
                    } else {
                        const streamUrl = API.getStreamUrl(assetId);
                        console.log('[loadPlayPage] Asset type:', data.type);
                        console.log('[loadPlayPage] Stream URL:', streamUrl);
                        console.log('[loadPlayPage] Container:', container);
                        PlayerManager.initArtPlayer(streamUrl, container, {
                            onTimeUpdate: onTimeUpdate
                        });
                    }
                });
                await playlistPromise;
            } catch (e) {
                console.error('[Router] Failed to load asset:', e);
                playPageError.value = e.message;
                playPageLoading.value = false;
            } finally {
                routeReady.value = true;
            }
        };

        const goToPlaylistAsset = (assetId) => {
            if (playlistContext.value?.playlist_id) {
                Router.goToPlay(assetId, { playlistId: playlistContext.value.playlist_id });
                return;
            }
            Router.goToPlay(assetId);
        };

        const isPlaylistItemActive = (item) => {
            return playPageData.value && playPageData.value.id === item.asset_id;
        };

        const handleRouteChange = (route, params) => {
            currentRoute.value = route;

            // Cleanup previous state
            PlayerManager.destroy();
            routeReady.value = false;

            if (route === 'play' && params.assetId) {
                loadPlayPage(params.assetId, params.playlistId || null);
            } else if (route === 'upload') {
                // Reset play page state when going to upload
                playPageData.value = null;
                playPageError.value = null;
                playlistContext.value = null;
                playlistContextLoading.value = false;
                routeReady.value = true;
            } else if (route === 'admin') {
                // Reset play page state when going to admin
                playPageData.value = null;
                playPageError.value = null;
                playlistContext.value = null;
                playlistContextLoading.value = false;
                if (adminSession.value) {
                    adminLoadData(true);
                } else {
                    routeReady.value = true;
                }
            } else if (route === 'home') {
                // Load home page assets
                playPageData.value = null;
                playPageError.value = null;
                playlistContext.value = null;
                playlistContextLoading.value = false;
                loadHomeAssets(false, true);
            } else {
                routeReady.value = true;
            }
        };

        watch(adminActiveTab, () => {
            if (adminSession.value && currentRoute.value === 'admin') {
                adminLoadData();
            }
            if (adminActiveTab.value !== 'playlists') {
                adminActivePlaylist.value = null;
                adminPlaylistItems.value = [];
                adminPlaylistView.value = 'list';
            }
        });

        const initApp = () => {
            resolveApiBaseUrl();

            // Initialize router after base URL is ready.
            Router.onRouteChange = handleRouteChange;
            Router.init();

            // Cleanup on page refresh/close
            window.addEventListener('beforeunload', cleanup);

            // Health check runs in background (non-blocking)
            checkBackendHealth();
            // Poll every 30 seconds
            healthCheckIntervalId = setInterval(checkBackendHealth, 30000);
        };

        // Start checking on mount
        onMounted(() => {
            initApp();
        });

        // Cleanup on unmount
        onUnmounted(() => {
            cleanup();
            window.removeEventListener('beforeunload', cleanup);
        });

        // YouTube Player API
        const initPlayer = (videoId) => {
            // Check if we can reuse existing YouTube player
            if (player.value && typeof player.value.loadVideoById === 'function') {
                // Verify the player is still attached to DOM
                const iframe = player.value.getIframe?.();
                if (iframe && iframe.parentNode) {
                    console.log('[Debug] Reusing existing YouTube player for video:', videoId);
                    player.value.loadVideoById(videoId);
                    return;
                }
                // Player exists but not in DOM, destroy it
                console.log('[Debug] Player detached from DOM, recreating...');
                if (typeof player.value.destroy === 'function') {
                    player.value.destroy();
                }
                player.value = null;
            }

            // If we have an existing player (even audio), destroy it if switching modes
            if (player.value) {
                // If it's a YT player, destroy it properly
                 if (typeof player.value.destroy === 'function') {
                    player.value.destroy();
                 }
                 player.value = null;
                 document.getElementById('youtube-player').innerHTML = '';
            }

            const container = document.getElementById('youtube-player');
            if (container) {
                container.style.height = '';
            }

            if (!window.YT) {
                const tag = document.createElement('script');
                tag.src = "https://www.youtube.com/iframe_api";
                const firstScriptTag = document.getElementsByTagName('script')[0];
                firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);

                window.onYouTubeIframeAPIReady = () => createPlayer(videoId);
            } else {
                createPlayer(videoId);
            }
        };

        const createPlayer = (videoId) => {
            player.value = new YT.Player('youtube-player', {
                height: '100%',
                width: '100%',
                videoId: videoId,
                playerVars: {
                    'playsinline': 1
                },
                events: {
                    'onReady': onPlayerReady,
                    'onStateChange': onPlayerStateChange
                }
            });
        };

        // File Audio/Video Player using ArtPlayer
        const initFilePlayer = (file) => {
            // Destroy existing player if it exists
            if (player.value) {
                if (typeof player.value.destroy === 'function') {
                    player.value.destroy();
                }
                player.value = null;
            }

            // Clear container
            const container = document.getElementById('youtube-player');
            if (!container) {
                console.error("Player container not found");
                return;
            }

            container.innerHTML = '';
            container.className = "w-full";

            // Create a wrapper div for ArtPlayer
            const artContainer = document.createElement('div');
            artContainer.className = 'artplayer-app';
            artContainer.style.width = '100%';
            // Height will be auto-calculated by ArtPlayer based on video aspect ratio
            container.appendChild(artContainer);

            // Create object URL for the file
            const fileUrl = URL.createObjectURL(file);

            // Initialize ArtPlayer
            const art = new Artplayer({
                container: artContainer,
                url: fileUrl,
                volume: 0.5,
                setting: true,
                playbackRate: true,
                aspectRatio: true,
                fullscreen: true,
                fullscreenWeb: true,
                pip: true,
                autoSize: false,
                autoMini: true,
                theme: '#3B82F6',
                lang: 'zh-cn',
            });

            // Auto-resize container based on video aspect ratio
            art.on('video:loadedmetadata', () => {
                const video = art.video;
                const containerWidth = container.clientWidth;

                // Check if it's audio-only (no video dimensions)
                if (video.videoWidth === 0 || video.videoHeight === 0) {
                    // Audio-only: use 21:9 aspect ratio
                    const newHeight = containerWidth / (21 / 9);
                    container.style.height = `${newHeight}px`;
                    artContainer.style.height = `${newHeight}px`;
                    console.log('[ArtPlayer] Audio-only mode, using 21:9 aspect ratio:', containerWidth, 'x', newHeight);
                } else {
                    // Video: use 16:9 aspect ratio
                    const newHeight = containerWidth / (16 / 9);
                    container.style.height = `${newHeight}px`;
                    artContainer.style.height = `${newHeight}px`;
                    console.log('[ArtPlayer] Video mode, using 16:9 aspect ratio:', containerWidth, 'x', newHeight);
                }
            });

            // Listen for time updates
            art.on('video:timeupdate', () => {
                const time = art.currentTime;
                if (Math.abs(time - currentTime.value) > 0.1) {
                    currentTime.value = time;
                    updateActiveWords();
                }
            });

            // Wrap ArtPlayer into a consistent interface for our app logic
            player.value = {
                getCurrentTime: () => art.currentTime,
                seekTo: (time, allowSeekAhead) => { art.seek = time; },
                playVideo: () => art.play(),
                pauseVideo: () => art.pause(),
                destroy: () => art.destroy(),
                artInstance: art,
                isNative: true
            };

            console.log('[ArtPlayer] Initialized with volume:', art.volume);
            startPolling();
        };

        const startPolling = () => {
             if (window._pollInterval) clearInterval(window._pollInterval);

             window._pollInterval = setInterval(() => {
                if (player.value && player.value.getCurrentTime) {
                    const time = player.value.getCurrentTime();
                    if (Math.abs(time - currentTime.value) > 0.1) {
                        currentTime.value = time;
                        updateActiveWords();
                    }
                    
                    if (dictation.active && dictation.isPlaying) {
                        const segment = videoData.value?.segments?.[dictation.segmentIndex];
                        if (segment && time >= segment.end) {
                            player.value.seekTo(Math.max(0, segment.start - 0.3), true);
                            player.value.playVideo();
                        }
                    }
                }
            }, 100);
        };

        const onPlayerReady = (event) => {
            event.target.setVolume(50);
            startPolling();
        };

        const onPlayerStateChange = (event) => {
            // Can handle play/pause states here
        };

        /**
         * Update active subtitle segment based on current playback time.
         */
        const updateActiveWords = () => {
            // Use playPageData on play page, videoData on home page
            const data = currentRoute.value === 'play' ? playPageData.value : videoData.value;
            if (!data) return;

            const segments = data.segments;
            let foundSegment = -1;

            // Search backwards to find the last matching segment, which is usually the correct one
            for (let i = segments.length - 1; i >= 0; i--) {
                const seg = segments[i];

                const start = seg.start;
                const end = seg.end;

                if (currentTime.value >= start) {
                    foundSegment = i;
                    break;
                }
            }

            if (foundSegment !== -1 && foundSegment !== currentSegmentIndex.value) {
                currentSegmentIndex.value = foundSegment;
            }
        };

        const scrollToSegment = (index) => {
            // Deprecated: automatic view limiting handles visibility
        };

        // Check if we have precise word-level timestamps
        const hasWordTimestamps = computed(() => {
            return videoData.value?.has_word_timestamps !== false;
        });

        const currentHasWordTimestamps = computed(() => {
            if (currentRoute.value === 'play') {
                return playPageData.value?.has_word_timestamps !== false;
            }
            return videoData.value?.has_word_timestamps !== false;
        });

        const isWordActive = (word, segment) => {
            // If we don't have word-level timestamps, highlight all words in the current segment
            if (!currentHasWordTimestamps.value && segment) {
                return currentTime.value >= segment.start && currentTime.value < segment.end;
            }
            // Otherwise, use precise word-level timing
            return currentTime.value >= word.start && currentTime.value < word.end;
        };

        /**
         * Seek playback to a specific time and start playback.
         * @param {number} time
         */
        const seekTo = (time) => {
            // Use PlayerManager on play page, player.value on home page
            if (currentRoute.value === 'play') {
                PlayerManager.seekTo(time);
                PlayerManager.play();
            } else if (player.value) {
                player.value.seekTo(time, true);
                if (player.value.playVideo) player.value.playVideo();
            }
        };

        const dictationProgress = computed(() => {
            if (!videoData.value?.segments?.length) return 0;
            return Math.round((dictation.segmentIndex / videoData.value.segments.length) * 100);
        });

        const currentDictationText = computed(() => {
            const segment = videoData.value?.segments?.[dictation.segmentIndex];
            if (!segment?.words) return '';
            return segment.words.map(w => w.text).join('');
        });

        const getCurrentSegment = () => {
            // Use playPageData on play page, videoData on home page
            const data = currentRoute.value === 'play' ? playPageData.value : videoData.value;
            if (!data?.segments) return null;
            return data.segments[dictation.segmentIndex];
        };

        const getSegmentText = (segment) => {
            if (!segment?.words) return '';
            return segment.words.map(w => w.text).join('');
        };

        /**
         * Play the current dictation segment from a slight pre-roll.
         */
        const playCurrentSegment = () => {
            const segment = getCurrentSegment();
            if (!segment) return;

            const startTime = Math.max(0, segment.start - 0.3);

            // Use PlayerManager on play page, player.value on home page
            if (currentRoute.value === 'play') {
                PlayerManager.seekTo(startTime);
                PlayerManager.play();
            } else if (player.value) {
                player.value.seekTo(startTime, true);
                player.value.playVideo();
            }
            dictation.isPlaying = true;
        };

        /**
         * Pause playback and stop dictation looping.
         */
        const stopDictationPlayback = () => {
            // Use PlayerManager on play page, player.value on home page
            if (currentRoute.value === 'play') {
                PlayerManager.pause();
            } else if (player.value) {
                player.value.pauseVideo();
            }
            dictation.isPlaying = false;
        };

        /**
         * Toggle dictation playback state.
         */
        const toggleDictationPlayback = () => {
            if (dictation.isPlaying) {
                stopDictationPlayback();
            } else {
                playCurrentSegment();
            }
        };

        const gotoPrevSegment = () => {
            if (dictation.segmentIndex > 0) {
                dictation.segmentIndex--;
                resetDictationInput();
            }
        };

        const gotoNextSegment = () => {
            // Use playPageData on play page, videoData on home page
            const data = currentRoute.value === 'play' ? playPageData.value : videoData.value;
            if (!data?.segments) return;
            if (dictation.segmentIndex < data.segments.length - 1) {
                dictation.segmentIndex++;
                resetDictationInput();
            }
        };

        const resetDictationInput = () => {
            dictation.userInput = '';
            dictation.mode = 'listen';
            dictation.diffResult = [];
            dictation.currentScore = null;
        };

        const normalizeJapanese = (str) => {
            return str
                .normalize('NFKC')
                .replace(/[\s\u3000]/g, '')
                .replace(/[。、！？「」『』（）・]/g, '');
        };

        const katakanaToHiragana = (str) => {
            return str.replace(/[\u30A1-\u30F6]/g, (match) => {
                return String.fromCharCode(match.charCodeAt(0) - 0x60);
            });
        };

        const generateDiff = (correct, user) => {
            const normCorrect = katakanaToHiragana(normalizeJapanese(correct));
            const normUser = katakanaToHiragana(normalizeJapanese(user));
            
            const result = [];
            let userIdx = 0;
            
            for (const char of correct) {
                const normChar = katakanaToHiragana(normalizeJapanese(char));
                if (!normChar) {
                    result.push({ text: char, status: 'correct' });
                    continue;
                }
                
                if (userIdx < normUser.length && normUser[userIdx] === normChar) {
                    result.push({ text: char, status: 'correct' });
                    userIdx++;
                } else {
                    result.push({ text: char, status: 'missing' });
                }
            }
            
            const correctCount = result.filter(r => r.status === 'correct').length;
            const totalChars = result.filter(r => normalizeJapanese(r.text)).length;
            const score = totalChars > 0 ? Math.round((correctCount / totalChars) * 100) : 0;
            
            return { diff: result, score };
        };

        const checkAnswer = () => {
            const segment = getCurrentSegment();
            if (!segment) return;
            
            const correctText = getSegmentText(segment);
            const { diff, score } = generateDiff(correctText, dictation.userInput);
            
            dictation.diffResult = diff;
            dictation.currentScore = score;
            dictation.mode = 'review';
            dictation.totalAttempts++;
            
            if (score >= 80) {
                dictation.correctCount++;
                dictation.statusByIndex[dictation.segmentIndex] = 'correct';
            } else {
                dictation.statusByIndex[dictation.segmentIndex] = 'wrong';
            }
            dictation.answersByIndex[dictation.segmentIndex] = dictation.userInput;
        };

        const skipCurrentSegment = () => {
            dictation.statusByIndex[dictation.segmentIndex] = 'skipped';
            gotoNextSegment();
        };

        const handleDictationMainAction = () => {
            if (dictation.mode === 'review') {
                gotoNextSegment();
            } else {
                checkAnswer();
            }
        };

        const handleDictationEnter = (event) => {
            if (dictation.isComposing) return;
            handleDictationMainAction();
        };

        const handleFileUpload = (event) => {
            const file = event.target.files[0];
            if (file) {
                selectedFile.value = file;
                videoUrl.value = ''; // Clear URL if file selected
            }
        };
        
        const handleFileDrop = (event) => {
            const file = event.dataTransfer.files[0];
             if (file && (file.type.startsWith('audio/') || file.type.startsWith('video/'))) {
                selectedFile.value = file;
                videoUrl.value = '';
            }
        };

        const clearFile = () => {
            selectedFile.value = null;
            selectedSubtitleFile.value = null;
            if (fileInput.value) fileInput.value.value = '';
            if (subtitleInput.value) subtitleInput.value.value = '';
        };

        const handleSubtitleUpload = (event) => {
            const file = event.target.files[0];
            if (file) {
                selectedSubtitleFile.value = file;
            }
        };

        const clearSubtitleFile = () => {
            selectedSubtitleFile.value = null;
            if (subtitleInput.value) subtitleInput.value.value = '';
        };

        /**
         * Upload a large file in chunks with optional subtitle upload.
         * @param {File} file
         * @param {File|null} subtitleFile
         * @returns {Promise<string>}
         */
        const uploadChunks = async (file, subtitleFile) => {
            try {
                const CHUNK_SIZE = 1 * 1024 * 1024; // 1MB chunks to be safe
                const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
                const apiUrl = `${apiBaseUrl.value}/api`;

                // 1. Init
                const initFormData = new FormData();
                initFormData.append('filename', file.name);
                initFormData.append('total_chunks', totalChunks);
                initFormData.append('total_size', file.size);
                let initRes = await fetchWithAuth(`${apiUrl}/upload/init`, {
                    method: 'POST',
                    body: initFormData
                });
                if (!initRes.ok) {
                    throw new Error("Failed to init upload");
                }
                const { task_id } = await initRes.json();

                // 2. Upload Chunks
                for (let i = 0; i < totalChunks; i++) {
                    const start = i * CHUNK_SIZE;
                    const end = Math.min(file.size, start + CHUNK_SIZE);
                    const chunk = file.slice(start, end);

                    const chunkFormData = new FormData();
                    chunkFormData.append('task_id', task_id);
                    chunkFormData.append('chunk_index', i);
                    chunkFormData.append('file', chunk);

                    // Update UI progress artificially for upload phase
                    taskStatus.value = {
                        status: 'processing',
                        progress: Math.floor((i / totalChunks) * 100),
                        message: `Uploading part ${i+1}/${totalChunks}...`
                    };

                    const chunkRes = await fetchWithAuth(`${apiUrl}/upload/chunk`, {
                        method: 'POST',
                        body: chunkFormData
                    });

                    if (!chunkRes.ok) {
                        throw new Error(`Failed to upload chunk ${i}`);
                    }
                }
                
                // 2.5. Upload subtitle file if provided (as a single file, not chunked)
                if (subtitleFile) {
                    taskStatus.value = {
                        status: 'processing',
                        progress: 95,
                        message: 'Uploading subtitle file...'
                    };

                    const subtitleFormData = new FormData();
                    subtitleFormData.append('task_id', task_id);
                    subtitleFormData.append('file', subtitleFile);

                    const subtitleRes = await fetchWithAuth(`${apiUrl}/upload/subtitle`, {
                        method: 'POST',
                        body: subtitleFormData
                    });

                    if (!subtitleRes.ok) {
                        console.warn('Failed to upload subtitle, continuing without it');
                    }
                }
                
                // 3. Complete
                const completeFormData = new FormData();
                completeFormData.append('task_id', task_id);
                completeFormData.append('filename', file.name);
                completeFormData.append('total_chunks', totalChunks);
                completeFormData.append('total_size', file.size);
                if (subtitleFile) {
                    completeFormData.append('subtitle_filename', subtitleFile.name);
                }

                const completeRes = await fetchWithAuth(`${apiUrl}/upload/complete`, {
                    method: 'POST',
                    body: completeFormData
                });

                if (!completeRes.ok) {
                    throw new Error("Failed to complete upload");
                }
                return task_id;
        } catch (error) {
            console.error('Upload error:', error);
            throw error;
        }
        };

        /**
         * Start processing for a YouTube URL or uploaded file.
         * @returns {Promise<void>}
         */
        const processVideo = async () => {
            if (!videoUrl.value && !selectedFile.value) return;
            
            // Check for mock trigger
            if (videoUrl.value === 'mock') {
                console.log('Using Mock Data');
                if (window.MOCK_DATA) {
                    loading.value = true;
                    videoData.value = window.MOCK_DATA.result;
                    loading.value = false;
                    nextTick(() => {
                         // Mock video ID for youtube player, or file player logic
                         // Since it's mock, we might not have a real player, but let's try to init player with mock ID
                         initPlayer(window.MOCK_DATA.result.video_id);
                    });
                    return;
                } else {
                    console.error("Mock data not found");
                }
            }
            
            loading.value = true;
            videoData.value = null;
            warnings.value = [];
            taskStatus.value = { status: 'pending', progress: 0, message: 'Initializing...' };
            
            try {
                const apiUrl = `${apiBaseUrl.value}/api`;
                let response;
                let isFile = !!selectedFile.value;
                isFileMode.value = isFile;
                let data;

                if (isFile) {
                    // Check file size (e.g., > 5MB)
                    const MAX_SIZE = 5 * 1024 * 1024;
                    if (selectedFile.value.size > MAX_SIZE) {
                        console.log('[Debug] Large file detected, using chunked upload');
                        const taskId = await uploadChunks(selectedFile.value, selectedSubtitleFile.value);
                        data = { task_id: taskId };
                    } else {
                        console.log('[Debug] Attempting upload to:', `${apiUrl}/upload`);
                        const formData = new FormData();
                        formData.append('file', selectedFile.value);
                        if (selectedSubtitleFile.value) {
                            formData.append('subtitle', selectedSubtitleFile.value);
                        }

                        response = await fetchWithAuth(`${apiUrl}/upload`, {
                            method: 'POST',
                            body: formData
                        });

                        if (!response.ok) {
                            throw new Error(`API Error: ${response.statusText}`);
                        }

                        data = await response.json();
                    }
                } else {
                    // Extract Video ID
                    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
                    const match = videoUrl.value.match(regExp);
                    
                    if (!match || match[2].length !== 11) {
                        alert('无效的 YouTube 链接');
                        loading.value = false;
                        return;
                    }
                    const videoId = match[2];

                    response = await fetchWithAuth(`${apiUrl}/process`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ url: videoUrl.value })
                    });

                    if (!response.ok) {
                        throw new Error(`API Error: ${response.statusText}`);
                    }

                    data = await response.json();
                }
                
                // Start polling for status
                if (data.task_id) {
                     console.log('[Debug] Received task_id:', data.task_id);
                     await pollStatus(data.task_id);
                } else {
                    // Fallback for immediate response (though backend is now async)
                    videoData.value = data;
                    loading.value = false; // Ensure loading is off
                    nextTick(() => {
                        if (isFileMode.value) {
                            initFilePlayer(selectedFile.value);
                        } else {
                            initPlayer(data.video_id);
                        }
                    });
                }
                
            } catch (e) {
                console.error(e);
                alert(`处理失败: ${e.message}`);
                loading.value = false;
            }
        };

        /**
         * Poll backend task status until completion or failure.
         * @param {string} taskId
         * @returns {Promise<void>}
         */
        const pollStatus = async (taskId) => {
            const pollInterval = 5000; // 5 seconds

            // Clear any existing poll timeout
            if (pollTimeoutId) {
                clearTimeout(pollTimeoutId);
                pollTimeoutId = null;
            }

            const check = async () => {
                try {
                    const response = await fetch(`${apiBaseUrl.value}/api/status/${taskId}`, {
                        credentials: 'include',
                        signal: abortController.signal
                    });
                    if (!response.ok) {
                        throw new Error("Failed to get status");
                    }
                    const statusData = await response.json();
                    taskStatus.value = statusData;
                    
                    if (statusData.status === 'completed') {
                        console.log('[Debug] Task completed. Result:', statusData.result);

                        // Log metrics if they exist
                        if (statusData.result.metrics) {
                            console.log('%c ✨ Metrics ✨', 'color: #22C55E; font-size: 1.2em; font-weight: bold; padding: 5px;');
                            console.table(statusData.result.metrics);
                        }

                        loading.value = false;

                        // Auto-redirect to play page if asset_id is available
                        if (statusData.result.asset_id) {
                            // For admin uploads, show edit modal first
                            if (isAdminMode.value) {
                                console.log('[Debug] Admin mode: showing edit modal for asset:', statusData.result.asset_id);
                                editForm.value = {
                                    assetId: statusData.result.asset_id,
                                    title: statusData.result.title || '',
                                    description: ''
                                };
                                showEditModal.value = true;
                                return;
                            }
                            console.log('[Debug] Redirecting to play page:', statusData.result.asset_id);
                            Router.goToPlay(statusData.result.asset_id);
                            return;
                        }

                        // Fallback: show in current page (for backward compatibility)
                        console.log('[Debug] No asset_id, showing in current page');

                        // Set warnings BEFORE videoData to ensure modal shows correctly
                        console.log('[Debug] Processing warnings:', statusData.result.warnings);
                        if (statusData.result.warnings && Array.isArray(statusData.result.warnings) && statusData.result.warnings.length > 0) {
                            warnings.value = statusData.result.warnings;
                            console.log('[Debug] Warnings set to UI:', warnings.value);
                        } else {
                            warnings.value = [];
                        }

                        videoData.value = statusData.result;

                        // Check if segments exist
                        if (statusData.result.segments && statusData.result.segments.length > 0) {
                            console.log(`[Debug] Loaded ${statusData.result.segments.length} segments`);
                        } else {
                            console.warn('[Debug] No segments found in result');
                        }

                        // Wait for Vue to update the DOM so that #youtube-player exists
                        nextTick(() => {
                            if (isFileMode.value) {
                                initFilePlayer(selectedFile.value);
                            } else {
                                initPlayer(statusData.result.video_id);
                            }
                        });
                    } else if (statusData.status === 'failed') {
                         throw new Error(statusData.error || "Processing failed");
                    } else {
                        // Continue polling
                        pollTimeoutId = setTimeout(check, pollInterval);
                    }
                } catch (e) {
                    // Ignore abort errors (page unload)
                    if (e.name === 'AbortError') {
                        console.log('[Debug] Polling aborted');
                        return;
                    }
                    console.error("Polling error:", e);
                    alert(`处理出错: ${e.message}`);
                    loading.value = false;
                }
            };
            
            // Start polling
            check();
        };

        const visibleSegments = computed(() => {
            if (!videoData.value || !videoData.value.segments) return [];

            const segments = videoData.value.segments;
            const current = currentSegmentIndex.value;
            const range = contextRange.value;

            // Determine the window of segments to show
            // If current is -1 (not started), show the beginning
            const centerIndex = current === -1 ? 0 : current;

            const start = Math.max(0, centerIndex - range);
            const end = Math.min(segments.length, centerIndex + range + 1);

            // console.log('[Debug] Computing visibleSegments', { centerIndex, start, end });

            return segments.slice(start, end).map((seg, index) => ({
                ...seg,
                originalIndex: start + index
            }));
        });

        // Visible segments for play page
        const playPageVisibleSegments = computed(() => {
            if (!playPageData.value || !playPageData.value.segments) return [];

            const segments = playPageData.value.segments;
            const current = currentSegmentIndex.value;
            const range = contextRange.value;

            const centerIndex = current === -1 ? 0 : current;
            const start = Math.max(0, centerIndex - range);
            const end = Math.min(segments.length, centerIndex + range + 1);

            return segments.slice(start, end).map((seg, index) => ({
                ...seg,
                originalIndex: start + index
            }));
        });

        // Check if play page has word timestamps
        const playPageHasWordTimestamps = computed(() => {
            return playPageData.value?.has_word_timestamps !== false;
        });

        // Admin edit modal methods
        const saveEditAndNavigate = async () => {
            editSaving.value = true;
            try {
                await API.updateAssetMeta(editForm.value.assetId, {
                    title: editForm.value.title,
                    description: editForm.value.description
                });
                showEditModal.value = false;
                Router.goToPlay(editForm.value.assetId);
            } catch (e) {
                console.error('Failed to save asset meta:', e);
                alert('保存失败: ' + e.message);
            } finally {
                editSaving.value = false;
            }
        };

        const skipEditAndNavigate = () => {
            showEditModal.value = false;
            Router.goToPlay(editForm.value.assetId);
        };

        return {
            videoUrl,
            loading,
            videoData,
            warnings,
            closeWarnings: () => { warnings.value = []; },
            visibleSegments, // Export this so template can use it
            contextRange,    // Export for potential UI control
            processVideo,
            isWordActive,
            hasWordTimestamps, // Export to control highlight mode in template
            seekTo,
            currentSegmentIndex,
            segmentRefs,
            subtitleContainer,
            selectedFile,
            selectedSubtitleFile,
            handleFileUpload,
            handleSubtitleUpload,
            handleFileDrop,
            clearFile,
            clearSubtitleFile,
            fileInput,
            subtitleInput,
            backendStatus,
            apiBaseUrl,
            checkBackendHealth,
            appReady,
            taskStatus,
            dictation,
            targetPauseTime,
            dictationProgress,
            currentDictationText,
            playCurrentSegment,
            stopDictationPlayback,
            toggleDictationPlayback,
            gotoPrevSegment,
            gotoNextSegment,
            skipCurrentSegment,
            handleDictationMainAction,
            handleDictationEnter,
            // Router state
            currentRoute,
            playPageData,
            playPageLoading,
            playPageError,
            playlistContext,
            playlistContextLoading,
            playPageVisibleSegments,
            playPageHasWordTimestamps,
            goHome: () => Router.goHome(),
            goToUpload: () => Router.goToUpload(),
            goToPlay: (assetId, options = {}) => Router.goToPlay(assetId, options),
            goToAdmin: () => Router.goToAdmin(),
            goToPlaylistAsset,
            isPlaylistItemActive,
            // Home page state
            homeAssets,
            homeLoading,
            homeHasMore,
            loadMoreAssets: () => loadHomeAssets(true),
            // Admin mode state
            isAdminMode,
            showEditModal,
            editForm,
            editSaving,
            saveEditAndNavigate,
            skipEditAndNavigate,
            // Admin panel state
            adminSession,
            adminLoading,
            adminError,
            adminActiveTab,
            adminUsers,
            adminAssets,
            adminSubtitleTracks,
            adminPlaylists,
            adminActivePlaylist,
            adminPlaylistItems,
            adminPlaylistView,
            adminPlaylistModalOpen,
            adminPlaylistForm,
            adminPlaylistSaving,
            adminPlaylistSearchOpen,
            adminPlaylistSearchQuery,
            adminPlaylistSearchResults,
            adminPlaylistSearchLoading,
            adminShowDeleteModal,
            adminDeleteTarget,
            adminDeleting,
            adminLoginForm,
            adminShowEditModal,
            adminEditForm,
            adminEditSaving,
            adminHandleLogin,
            adminHandleLogout,
            adminLoadData,
            adminConfirmDelete,
            adminExecuteDelete,
            adminFormatDate,
            adminOpenPlayPage,
            adminGoToUpload,
            adminOpenEditModal,
            adminSaveAssetMeta,
            adminOpenPlaylistModal,
            adminSavePlaylist,
            adminOpenPlaylistDetail,
            adminOpenPlaylistPlay,
            adminLoadPlaylistItems,
            adminBackToPlaylists,
            adminOpenPlaylistSearch,
            adminSearchPlaylistAssets,
            adminAddPlaylistAsset,
            adminMovePlaylistItem,
            adminRemovePlaylistItem
        };
    }
}).mount('#app');
