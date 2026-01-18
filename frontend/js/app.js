/**
 * ShadowPartner Main Application
 * Refactored to use composables for better code organization
 */

const { createApp, ref, reactive, onMounted, onUnmounted, nextTick, computed, watch } = Vue;

createApp({
    setup() {
        // ========================================================================
        // COMPOSABLES - Extracted logic modules
        // ========================================================================

        // Toast notification system
        const {
            toasts,
            showToast,
            removeToast,
            toastIcon,
            toastClasses
        } = useToast();

        // Custom confirm dialog
        const {
            confirmDialog,
            showConfirm,
            handleConfirmOk,
            handleConfirmCancel
        } = useConfirmDialog();

        // Backend and session management
        const {
            apiBaseUrl,
            apiReady,
            backendStatus,
            sessionId,
            appReady,
            resolveApiBaseUrl,
            checkBackendHealth,
            initBackend,
            cleanup: backendCleanup,
            ensureSession,
            buildSessionHeaders,
            fetchWithAuth,
            buildAdminHeaders
        } = useBackend();

        // Home page asset management
        const {
            homeAssets,
            homeLoading,
            homeHasMore,
            loadHomeAssets,
            resetHomeAssets
        } = useHomeAssets();

        // Dictation game mode
        const {
            dictation,
            targetPauseTime,
            getCurrentSegment,
            getSegmentText,
            getCurrentDictationText,
            checkAnswer,
            gotoPrevSegment,
            gotoNextSegment,
            skipCurrentSegment,
            resetDictationInput,
            handleDictationMainAction,
            handleDictationEnter,
            toggleDictationPlayback,
            getDictationProgress,
            resetDictationState,
            validateInputRealtime,
            getInputBorderClass,
            getFocusRingClass
        } = useDictation();

        // Admin panel
        const {
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
        } = useAdminPanel({ apiBaseUrl, buildAdminHeaders, showToast, showConfirm });

        // File upload and processing
        const {
            loading,
            videoUrl,
            videoData,
            selectedFile,
            selectedSubtitleFile,
            warnings,
            assetExists,
            isFileMode,
            taskStatus,
            fileInput,
            subtitleInput,
            handleFileUpload,
            handleFileDrop,
            handleSubtitleUpload,
            clearFile,
            clearSubtitleFile,
            processVideo,
            resetUploadState,
            cleanupPolling
        } = useFileUpload({ apiBaseUrl, fetchWithAuth, showToast });

        // ========================================================================
        // UPLOAD HANDLER - Wrap processVideo with completion logic
        // ========================================================================

        /**
         * Handle video processing with completion callback.
         * This wrapper is needed because useFileUpload.processVideo requires
         * an onCompleted callback to handle navigation after processing.
         */
        const handleProcessVideo = async () => {
            await processVideo(async (result) => {
                console.log('[Debug] Processing completed. Result:', result);

                // Auto-redirect to play page if asset_id is available
                if (result.asset_id) {
                    // For admin uploads, show edit modal first
                    if (isAdminMode.value) {
                        console.log('[Debug] Admin mode: showing edit modal for asset:', result.asset_id);
                        editForm.value = {
                            assetId: result.asset_id,
                            title: result.title || '',
                            description: ''
                        };
                        showEditModal.value = true;
                        return;
                    }
                    console.log('[Debug] Redirecting to play page:', result.asset_id);
                    Router.goToPlay(result.asset_id);
                    return;
                }

                // Fallback: show in current page (for backward compatibility)
                console.log('[Debug] No asset_id, showing in current page');

                // Set warnings BEFORE videoData to ensure modal shows correctly
                if (result.warnings && Array.isArray(result.warnings) && result.warnings.length > 0) {
                    warnings.value = result.warnings;
                } else {
                    warnings.value = [];
                }

                videoData.value = result;

                // Check if segments exist
                if (result.segments && result.segments.length > 0) {
                    console.log(`[Debug] Loaded ${result.segments.length} segments`);
                } else {
                    console.warn('[Debug] No segments found in result');
                }

                // Wait for Vue to update the DOM so that #youtube-player exists
                nextTick(() => {
                    if (isFileMode.value) {
                        initFilePlayer(selectedFile.value);
                    } else {
                        initPlayer(result.video_id);
                    }
                });
            });
        };

        // ========================================================================
        // LOCAL STATE - State not extracted to composables
        // ========================================================================

        // Router state
        const currentRoute = ref('home');
        const playPageData = ref(null);
        const playPageLoading = ref(false);
        const playPageError = ref(null);
        const playlistContext = ref(null);
        const playlistContextLoading = ref(false);

        // Navigation context for Play page
        const navigationContext = reactive({
            source: 'direct',
            playlistId: null,
            playlistTitle: null,
            canGoBack: false
        });

        // Route ready flag - start as true, only false during transitions
        const routeReady = ref(true);

        // Player state
        const player = ref(null);
        const currentTime = ref(0);
        const currentSegmentIndex = ref(-1);
        const segmentRefs = ref({});
        const subtitleContainer = ref(null);

        // Subtitle context range
        const contextRange = ref(2);

        // Admin mode edit modal (for upload flow)
        const showEditModal = ref(false);
        const editForm = ref({ assetId: '', title: '', description: '' });
        const editSaving = ref(false);

        // Debug: Expose global methods for modal troubleshooting
        window.resetConfirmDialog = () => {
            console.log('[Debug] Resetting confirmDialog');
            confirmDialog.value = false;
        };
        window.diagnoseModals = () => {
            console.log('=== Modal States ===');
            console.log('confirmDialog.show:', confirmDialog.value.show);
            console.log('adminShowDeleteModal:', adminShowDeleteModal.value);
            console.log('adminShowEditModal:', adminShowEditModal.value);
            console.log('adminPlaylistModalOpen:', adminPlaylistModalOpen.value);
            console.log('adminPlaylistSearchOpen:', adminPlaylistSearchOpen.value);
            console.log('showEditModal:', showEditModal.value);
            console.log('warnings:', warnings.value);
            console.log('==================');
        };
        window.resetAllModals = () => {
            console.log('[Debug] Resetting all modals');
            confirmDialog.value.show = false;
            adminShowDeleteModal.value = false;
            adminShowEditModal.value = false;
            adminPlaylistModalOpen.value = false;
            adminPlaylistSearchOpen.value = false;
            showEditModal.value = false;
            warnings.value = [];
        };

        // ========================================================================
        // PLAYER LOGIC - YouTube and ArtPlayer initialization
        // ========================================================================

        /**
         * Initialize YouTube player.
         * @param {string} videoId
         */
        const initPlayer = (videoId) => {
            // Check if we can reuse existing YouTube player
            if (player.value && typeof player.value.loadVideoById === 'function') {
                const iframe = player.value.getIframe?.();
                if (iframe && iframe.parentNode) {
                    console.log('[Debug] Reusing existing YouTube player for video:', videoId);
                    player.value.loadVideoById(videoId);
                    return;
                }
                if (typeof player.value.destroy === 'function') {
                    player.value.destroy();
                }
                player.value = null;
            }

            if (player.value) {
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
                playerVars: { 'playsinline': 1 },
                events: {
                    'onReady': onPlayerReady,
                    'onStateChange': onPlayerStateChange
                }
            });
        };

        /**
         * Initialize ArtPlayer for file playback.
         * @param {File} file
         */
        const initFilePlayer = (file) => {
            if (player.value) {
                if (typeof player.value.destroy === 'function') {
                    player.value.destroy();
                }
                player.value = null;
            }

            const container = document.getElementById('youtube-player');
            if (!container) {
                console.error("Player container not found");
                return;
            }

            container.innerHTML = '';
            container.className = "w-full";

            const artContainer = document.createElement('div');
            artContainer.className = 'artplayer-app';
            artContainer.style.width = '100%';
            container.appendChild(artContainer);

            const fileUrl = URL.createObjectURL(file);

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

                if (video.videoWidth === 0 || video.videoHeight === 0) {
                    // Audio-only: compact 60px height
                    artContainer.classList.add('artplayer-audio-only');
                    container.style.height = '60px';
                    container.style.minHeight = '60px';
                    container.style.maxHeight = '60px';
                    artContainer.style.height = '60px';
                    artContainer.style.minHeight = '60px';
                    artContainer.style.maxHeight = '60px';

                    if (art.template.$layer) {
                        art.template.$layer.style.display = 'none';
                    }
                    if (art.template.$mask) {
                        art.template.$mask.style.display = 'none';
                    }
                    console.log('[ArtPlayer] Audio-only mode, using compact controls');
                } else {
                    // Video: use 16:9 aspect ratio
                    const newHeight = containerWidth / (16 / 9);
                    artContainer.classList.remove('artplayer-audio-only');
                    container.style.height = `${newHeight}px`;
                    container.style.minHeight = '';
                    container.style.maxHeight = '';
                    artContainer.style.height = `${newHeight}px`;
                    artContainer.style.minHeight = '';
                    artContainer.style.maxHeight = '';

                    if (art.template.$layer) {
                        art.template.$layer.style.display = '';
                    }
                    if (art.template.$mask) {
                        art.template.$mask.style.display = '';
                    }
                    console.log('[ArtPlayer] Video mode, using 16:9 aspect ratio:', containerWidth, 'x', newHeight);
                }
            });

            art.on('video:timeupdate', () => {
                const time = art.currentTime;
                if (Math.abs(time - currentTime.value) > 0.1) {
                    currentTime.value = time;
                    updateActiveWords();
                }
            });

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
            const data = currentRoute.value === 'play' ? playPageData.value : videoData.value;
            if (!data) return;

            const segments = data.segments;
            let foundSegment = -1;

            for (let i = segments.length - 1; i >= 0; i--) {
                const seg = segments[i];
                if (currentTime.value >= seg.start) {
                    foundSegment = i;
                    break;
                }
            }

            if (foundSegment !== -1 && foundSegment !== currentSegmentIndex.value) {
                currentSegmentIndex.value = foundSegment;
            }
        };

        // ========================================================================
        // COMPUTED PROPERTIES
        // ========================================================================

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
            if (!currentHasWordTimestamps.value && segment) {
                return currentTime.value >= segment.start && currentTime.value < segment.end;
            }
            return currentTime.value >= word.start && currentTime.value < word.end;
        };

        const visibleSegments = computed(() => {
            if (!videoData.value || !videoData.value.segments) return [];

            const segments = videoData.value.segments;
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

        const playPageHasWordTimestamps = computed(() => {
            return playPageData.value?.has_word_timestamps !== false;
        });

        const dictationProgress = computed(() => {
            const data = currentRoute.value === 'play' ? playPageData.value : videoData.value;
            if (!data?.segments?.length) return 0;
            return Math.round((dictation.segmentIndex / data.segments.length) * 100);
        });

        const currentDictationText = computed(() => {
            const data = currentRoute.value === 'play' ? playPageData.value : videoData.value;
            return getCurrentDictationText(data);
        });

        const backButtonLabel = computed(() => {
            switch (navigationContext.source) {
                case 'playlist':
                    return '返回播放列表';
                case 'home':
                    return '返回首页';
                case 'admin':
                    return '返回管理';
                case 'upload':
                    return '返回上传';
                default:
                    return '返回首页';
            }
        });

        const breadcrumbItems = computed(() => {
            const items = [];

            switch (navigationContext.source) {
                case 'admin':
                    items.push({ label: '管理', action: () => Router.goToAdmin() });
                    break;
                case 'upload':
                    items.push({ label: '上传', action: () => Router.goToUpload() });
                    break;
                default:
                    items.push({ label: '首页', action: () => Router.goHome() });
                    break;
            }

            if (navigationContext.playlistTitle && (navigationContext.source === 'home' || navigationContext.source === 'playlist' || navigationContext.source === 'direct')) {
                items.push({
                    label: navigationContext.playlistTitle,
                    action: () => Router.goHome()
                });
            }

            if (playPageData.value) {
                items.push({ label: playPageData.value.title, action: null });
            }

            return items;
        });

        // ========================================================================
        // DICTATION HELPERS
        // ========================================================================

        const getCurrentVideoData = () => {
            return currentRoute.value === 'play' ? playPageData.value : videoData.value;
        };

        const playCurrentSegment = () => {
            const segment = getCurrentSegment(getCurrentVideoData());
            if (!segment) return;

            const startTime = Math.max(0, segment.start - 0.3);

            if (currentRoute.value === 'play') {
                PlayerManager.seekTo(startTime);
                PlayerManager.play();
            } else if (player.value) {
                player.value.seekTo(startTime, true);
                player.value.playVideo();
            }
            dictation.isPlaying = true;
        };

        const stopDictationPlayback = () => {
            if (currentRoute.value === 'play') {
                PlayerManager.pause();
            } else if (player.value) {
                player.value.pauseVideo();
            }
            dictation.isPlaying = false;
        };

        const handleDictationEnterLocal = (event) => {
            handleDictationEnter(getCurrentVideoData());
        };

        const handleDictationMainActionLocal = () => {
            handleDictationMainAction(getCurrentVideoData());
        };

        const gotoPrevSegmentLocal = () => {
            gotoPrevSegment();
        };

        const gotoNextSegmentLocal = () => {
            gotoNextSegment(getCurrentVideoData());
        };

        const skipCurrentSegmentLocal = () => {
            skipCurrentSegment(getCurrentVideoData());
        };

        const toggleDictationPlaybackLocal = () => {
            toggleDictationPlayback(playCurrentSegment, stopDictationPlayback);
        };

        // ========================================================================
        // PLAYER HELPERS
        // ========================================================================

        const seekTo = (time) => {
            if (currentRoute.value === 'play') {
                PlayerManager.seekTo(time);
                PlayerManager.play();
            } else if (player.value) {
                player.value.seekTo(time, true);
                if (player.value.playVideo) player.value.playVideo();
            }
        };

        // ========================================================================
        // ROUTING & NAVIGATION
        // ========================================================================

        const navigateBack = () => {
            Router.goBackToPrevious() || Router.goHome();
        };

        const loadPlaylistContext = async (playlistId, assetId) => {
            playlistContextLoading.value = true;
            try {
                playlistContext.value = await API.getPlaylistContext(playlistId, assetId);
                if (playlistContext.value) {
                    navigationContext.playlistTitle = playlistContext.value.playlist_title;
                }
            } catch (e) {
                console.warn('[Playlist] Failed to load context:', e);
                playlistContext.value = null;
                navigationContext.playlistTitle = null;
            } finally {
                playlistContextLoading.value = false;
            }
        };

        const loadPlayPage = async (assetId, playlistId = null) => {
            console.log('[Router] Loading play page for asset:', assetId);
            playPageLoading.value = true;
            playPageError.value = null;
            playPageData.value = null;
            playlistContext.value = null;
            playlistContextLoading.value = false;
            routeReady.value = true;

            resetDictationState();
            currentTime.value = 0;
            currentSegmentIndex.value = -1;

            try {
                const playlistPromise = playlistId
                    ? loadPlaylistContext(playlistId, assetId)
                    : Promise.resolve();
                const data = await API.getAsset(assetId);
                console.log('[loadPlayPage] Asset data loaded:', data);
                playPageData.value = data;
                playPageLoading.value = false;

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

            const routerContext = Router.getNavigationContext();
            navigationContext.source = routerContext.source;
            navigationContext.playlistId = routerContext.playlistId;
            navigationContext.canGoBack = routerContext.canGoBack;

            PlayerManager.destroy();
            routeReady.value = false;

            if (route === 'play' && params.assetId) {
                loadPlayPage(params.assetId, params.playlistId || null);
            } else if (route === 'upload') {
                playPageData.value = null;
                playPageError.value = null;
                playlistContext.value = null;
                playlistContextLoading.value = false;
                routeReady.value = true;
            } else if (route === 'admin') {
                playPageData.value = null;
                playPageError.value = null;
                playlistContext.value = null;
                playlistContextLoading.value = false;
                if (adminSession.value) {
                    adminLoadData();
                }
                routeReady.value = true;
            } else if (route === 'home') {
                playPageData.value = null;
                playPageError.value = null;
                playlistContext.value = null;
                playlistContextLoading.value = false;
                loadHomeAssets(false);
                routeReady.value = true;
            } else {
                routeReady.value = true;
            }
        };

        // ========================================================================
        // ADMIN UPLOAD EDIT MODAL
        // ========================================================================

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
                showToast('保存失败: ' + e.message, 'error');
            } finally {
                editSaving.value = false;
            }
        };

        const skipEditAndNavigate = () => {
            showEditModal.value = false;
            Router.goToPlay(editForm.value.assetId);
        };

        // ========================================================================
        // INITIALIZATION
        // ========================================================================

        const initApp = () => {
            initBackend();

            Router.onRouteChange = handleRouteChange;
            Router.init();

            window.addEventListener('beforeunload', () => {
                backendCleanup();
                cleanupPolling();
            });
        };

        onMounted(() => {
            initApp();
        });

        onUnmounted(() => {
            backendCleanup();
            cleanupPolling();
            window.removeEventListener('beforeunload', backendCleanup);
        });

        // Watch admin tab changes
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

        // ========================================================================
        // RETURN - Export all state and methods to template
        // ========================================================================

        return {
            // Upload state
            videoUrl,
            loading,
            videoData,
            warnings,
            assetExists,
            closeWarnings: () => { warnings.value = []; },
            visibleSegments,
            contextRange,
            handleProcessVideo,
            isWordActive,
            hasWordTimestamps,
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

            // Backend state
            backendStatus,
            apiBaseUrl,
            checkBackendHealth,
            appReady,
            taskStatus,

            // Dictation state
            dictation,
            targetPauseTime,
            dictationProgress,
            currentDictationText,
            playCurrentSegment,
            stopDictationPlayback,
            toggleDictationPlayback: toggleDictationPlaybackLocal,
            gotoPrevSegment: gotoPrevSegmentLocal,
            gotoNextSegment: gotoNextSegmentLocal,
            skipCurrentSegment: skipCurrentSegmentLocal,
            handleDictationMainAction: handleDictationMainActionLocal,
            handleDictationEnter: handleDictationEnterLocal,

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

            // Navigation context
            navigationContext,
            navigateBack,
            backButtonLabel,
            breadcrumbItems,

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
            adminRemovePlaylistItem,

            // Toast notification system
            toasts,
            showToast,
            removeToast,
            toastIcon,
            toastClasses,

            // Custom confirm dialog
            confirmDialog,
            showConfirm,
            handleConfirmOk,
            handleConfirmCancel
        };
    }
}).mount('#app');
