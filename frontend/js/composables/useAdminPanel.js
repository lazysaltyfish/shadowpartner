/**
 * Admin panel composable.
 * Handles admin authentication, user/asset/playlist management.
 */

/**
 * Admin panel composable.
 * @param {Object} options - Options containing apiBaseUrl, showToast, showConfirm
 * @returns {Object} Admin state and methods
 */
function useAdminPanel({ apiBaseUrl, buildAdminHeaders, showToast, showConfirm }) {
    // Auth state
    const adminSession = Vue.ref(API.getAdminSessionId());
    const adminLoading = Vue.ref(false);
    const adminError = Vue.ref(null);
    const adminLoginForm = Vue.ref({ username: '', password: '' });

    // Data state
    const adminActiveTab = Vue.ref('users');
    const adminUsers = Vue.ref([]);
    const adminAssets = Vue.ref([]);
    const adminSubtitleTracks = Vue.ref([]);
    const adminPlaylists = Vue.ref([]);

    // Delete modal
    const adminShowDeleteModal = Vue.ref(false);
    const adminDeleteTarget = Vue.ref({ type: '', id: '', identifier: '' });
    const adminDeleting = Vue.ref(false);

    // Edit modal
    const adminShowEditModal = Vue.ref(false);
    const adminEditForm = Vue.ref({ assetId: '', title: '', description: '' });
    const adminEditSaving = Vue.ref(false);

    // Playlist state
    const adminActivePlaylist = Vue.ref(null);
    const adminPlaylistItems = Vue.ref([]);
    const adminPlaylistView = Vue.ref('list');
    const adminPlaylistModalOpen = Vue.ref(false);
    const adminPlaylistForm = Vue.ref({ id: null, title: '', description: '', cover_image: '' });
    const adminPlaylistSaving = Vue.ref(false);
    const adminPlaylistSearchOpen = Vue.ref(false);
    const adminPlaylistSearchQuery = Vue.ref('');
    const adminPlaylistSearchResults = Vue.ref([]);
    const adminPlaylistSearchLoading = Vue.ref(false);

    // Admin mode computed
    const isAdminMode = Vue.computed(() => !!adminSession.value);

    /**
     * Format date for display.
     * @param {string} dateString
     * @returns {string} Formatted date
     */
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

    /**
     * Clear all admin state.
     */
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

    /**
     * Handle admin login.
     */
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

    /**
     * Handle admin logout.
     */
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

    /**
     * Load admin data based on active tab.
     */
    const adminLoadData = async () => {
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
        }
    };

    /**
     * Show delete confirmation modal.
     */
    const adminConfirmDelete = (type, id, identifier) => {
        adminDeleteTarget.value = { type, id, identifier };
        adminShowDeleteModal.value = true;
    };

    /**
     * Execute delete operation.
     */
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
                showToast(errorData.detail || 'Delete failed', 'error');
            }
        } catch (e) {
            console.error('Admin delete error:', e);
            showToast(e.message || 'Delete failed', 'error');
        } finally {
            adminDeleting.value = false;
        }
    };

    /**
     * Open play page for asset.
     */
    const adminOpenPlayPage = (asset) => {
        Router.goToPlay(asset.id);
    };

    /**
     * Go to upload page.
     */
    const adminGoToUpload = () => {
        Router.goToUpload();
    };

    /**
     * Open edit modal for asset.
     */
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

    /**
     * Save asset metadata.
     */
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
            showToast(e.message || 'Failed to save', 'error');
        } finally {
            adminEditSaving.value = false;
        }
    };

    /**
     * Open playlist modal (create or edit).
     */
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

    /**
     * Save playlist (create or update).
     */
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
            showToast(e.message || 'Failed to save', 'error');
        } finally {
            adminPlaylistSaving.value = false;
        }
    };

    /**
     * Open playlist detail view.
     */
    const adminOpenPlaylistDetail = async (playlist) => {
        adminActivePlaylist.value = playlist;
        adminPlaylistView.value = 'detail';
        await adminLoadPlaylistItems(playlist.id);
    };

    /**
     * Play playlist from first item.
     */
    const adminOpenPlaylistPlay = async (playlist) => {
        if (!playlist || !playlist.id) {
            return;
        }
        if (!playlist.item_count) {
            showToast('Playlist is empty', 'warning');
            return;
        }
        try {
            const data = await API.getPlaylistItems(playlist.id);
            const firstItem = data.items?.[0];
            if (!firstItem) {
                showToast('Playlist is empty', 'warning');
                return;
            }
            Router.goToPlay(firstItem.asset_id, { playlistId: playlist.id });
        } catch (e) {
            console.error('Failed to open playlist play page:', e);
            showToast(e.message || 'Failed to open', 'error');
        }
    };

    /**
     * Load playlist items.
     */
    const adminLoadPlaylistItems = async (playlistId) => {
        try {
            const data = await API.getPlaylistItems(playlistId);
            adminPlaylistItems.value = data.items || [];
        } catch (e) {
            console.error('Failed to load playlist items:', e);
            showToast(e.message || 'Failed to load', 'error');
        }
    };

    /**
     * Go back to playlists list view.
     */
    const adminBackToPlaylists = () => {
        adminActivePlaylist.value = null;
        adminPlaylistItems.value = [];
        adminPlaylistView.value = 'list';
    };

    /**
     * Open playlist asset search modal.
     */
    const adminOpenPlaylistSearch = () => {
        adminPlaylistSearchOpen.value = true;
        adminPlaylistSearchQuery.value = '';
        adminPlaylistSearchResults.value = [];
    };

    /**
     * Search assets for playlist.
     */
    const adminSearchPlaylistAssets = async () => {
        adminPlaylistSearchLoading.value = true;
        try {
            const data = await API.searchAssets(adminPlaylistSearchQuery.value || '');
            adminPlaylistSearchResults.value = data.items || [];
        } catch (e) {
            console.error('Playlist search failed:', e);
            showToast(e.message || 'Search failed', 'error');
        } finally {
            adminPlaylistSearchLoading.value = false;
        }
    };

    /**
     * Add asset to playlist.
     */
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
            showToast(e.message || 'Failed to add', 'error');
        }
    };

    /**
     * Move playlist item up or down.
     */
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
            showToast(e.message || 'Failed to reorder', 'error');
        }
    };

    /**
     * Remove item from playlist.
     */
    const adminRemovePlaylistItem = async (item) => {
        if (!adminActivePlaylist.value) {
            return;
        }
        const confirmRemove = await showConfirm({
            title: 'Remove Item',
            message: `Remove "${item.cached_title}" from this playlist?`,
            confirmText: 'Remove',
            cancelText: 'Cancel',
            type: 'danger'
        });
        if (!confirmRemove) {
            return;
        }
        try {
            await API.removePlaylistItem(adminActivePlaylist.value.id, item.asset_id);
            await adminLoadPlaylistItems(adminActivePlaylist.value.id);
        } catch (e) {
            console.error('Failed to remove playlist item:', e);
            showToast(e.message || 'Failed to remove', 'error');
        }
    };

    return {
        // State
        adminSession,
        adminLoading,
        adminError,
        adminActiveTab,
        adminUsers,
        adminAssets,
        adminSubtitleTracks,
        adminPlaylists,
        adminShowDeleteModal,
        adminDeleteTarget,
        adminDeleting,
        adminLoginForm,
        adminShowEditModal,
        adminEditForm,
        adminEditSaving,
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
        isAdminMode,

        // Methods
        adminFormatDate,
        clearAdminState,
        adminHandleLogin,
        adminHandleLogout,
        adminLoadData,
        adminConfirmDelete,
        adminExecuteDelete,
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

// Attach to global scope for use in app.js
window.useAdminPanel = useAdminPanel;
