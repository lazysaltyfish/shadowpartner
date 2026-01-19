/**
 * Player Module for ShadowPartner
 * Unified interface for YouTube and ArtPlayer
 */

const PlayerManager = {
    player: null,
    type: null, // 'youtube' | 'artplayer'
    pollInterval: null,
    onTimeUpdate: null,
    onReady: null,

    /**
     * Destroy current player
     */
    destroy() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
        if (this.player) {
            if (typeof this.player.destroy === 'function') {
                this.player.destroy();
            }
            this.player = null;
        }
        this.type = null;
    },

    /**
     * Initialize YouTube player
     * @param {string} videoId - YouTube video ID
     * @param {HTMLElement} container - Container element
     * @param {object} callbacks - { onTimeUpdate, onReady }
     */
    initYouTube(videoId, container, callbacks = {}) {
        this.destroy();
        this.type = 'youtube';
        this.onTimeUpdate = callbacks.onTimeUpdate;
        this.onReady = callbacks.onReady;

        container.innerHTML = '';
        container.style.height = '';

        const createPlayer = () => {
            this.player = new YT.Player(container.id, {
                height: '100%',
                width: '100%',
                videoId: videoId,
                playerVars: { 'playsinline': 1 },
                events: {
                    'onReady': () => {
                        this.startPolling();
                        if (this.onReady) this.onReady();
                    },
                    'onStateChange': (event) => {
                        // Handle state changes if needed
                    }
                }
            });
        };

        if (!window.YT) {
            const tag = document.createElement('script');
            tag.src = "https://www.youtube.com/iframe_api";
            document.head.appendChild(tag);
            window.onYouTubeIframeAPIReady = createPlayer;
        } else {
            createPlayer();
        }
    },

    /**
     * Initialize ArtPlayer for local/streamed files
     * @param {string} url - Media URL (stream or blob)
     * @param {HTMLElement} container - Container element
     * @param {object} callbacks - { onTimeUpdate, onReady }
     */
    initArtPlayer(url, container, callbacks = {}) {
        this.destroy();
        this.type = 'artplayer';
        this.onTimeUpdate = callbacks.onTimeUpdate;
        this.onReady = callbacks.onReady;

        console.log('[PlayerManager] Initializing ArtPlayer with URL:', url);

        container.innerHTML = '';
        const artContainer = document.createElement('div');
        artContainer.className = 'artplayer-app';
        artContainer.style.width = '100%';
        // Set initial height to prevent black screen
        artContainer.style.height = '100%';
        container.appendChild(artContainer);

        const art = new Artplayer({
            container: artContainer,
            url: url,
            volume: 0.5,
            setting: true,
            playbackRate: true,
            fullscreen: true,
            pip: true,
            theme: '#3B82F6',
            lang: 'zh-cn',
            autoplay: false,
            muted: false,
            crossOrigin: 'anonymous',
        });

        console.log('[PlayerManager] ArtPlayer instance created');

        // Handle aspect ratio and audio-only mode
        art.on('video:loadedmetadata', () => {
            const video = art.video;
            const isAudioOnly = video.videoWidth === 0 || video.videoHeight === 0;

            if (isAudioOnly) {
                // Audio-only mode: set compact height for controls only
                artContainer.classList.add('artplayer-audio-only');
                container.style.height = '60px';
                container.style.minHeight = '60px';
                container.style.maxHeight = '60px';
                artContainer.style.height = '60px';
                artContainer.style.minHeight = '60px';
                artContainer.style.maxHeight = '60px';

                // Hide center play button layer
                if (art.template.$layer) {
                    art.template.$layer.style.display = 'none';
                }
                // Hide mask overlay
                if (art.template.$mask) {
                    art.template.$mask.style.display = 'none';
                }

                console.log('[PlayerManager] Audio-only mode enabled');
            } else {
                // Video: use the container's compact height
                artContainer.classList.remove('artplayer-audio-only');
                container.style.height = '';
                container.style.minHeight = '';
                container.style.maxHeight = '';
                artContainer.style.height = '100%';
                artContainer.style.minHeight = '';
                artContainer.style.maxHeight = '';

                // Show layer and mask for video
                if (art.template.$layer) {
                    art.template.$layer.style.display = '';
                }
                if (art.template.$mask) {
                    art.template.$mask.style.display = '';
                }
            }
        });

        art.on('ready', () => {
            console.log('[PlayerManager] ArtPlayer ready');
            if (this.onReady) this.onReady();
        });

        art.on('video:timeupdate', () => {
            if (this.onTimeUpdate) {
                this.onTimeUpdate(art.currentTime);
            }
        });

        // Error handling
        art.on('error', (error) => {
            console.error('[PlayerManager] ArtPlayer error:', error);
        });

        art.on('video:error', (error) => {
            console.error('[PlayerManager] Video error:', error);
            console.error('[PlayerManager] Video error code:', art.video?.error?.code);
            console.error('[PlayerManager] Video error message:', art.video?.error?.message);
        });

        // Wrap as unified interface
        this.player = {
            getCurrentTime: () => art.currentTime,
            seekTo: (time) => { art.seek = time; },
            playVideo: () => art.play(),
            pauseVideo: () => art.pause(),
            destroy: () => art.destroy(),
            artInstance: art,
            isNative: true
        };
    },

    /**
     * Start time polling (for YouTube)
     */
    startPolling() {
        if (this.pollInterval) clearInterval(this.pollInterval);
        this.pollInterval = setInterval(() => {
            if (this.player && this.player.getCurrentTime && this.onTimeUpdate) {
                const time = this.player.getCurrentTime();
                this.onTimeUpdate(time);
            }
        }, 100);
    },

    // Unified player interface
    /**
     * Get current playback time in seconds.
     * @returns {number}
     */
    getCurrentTime() {
        return this.player?.getCurrentTime?.() || 0;
    },

    /**
     * Seek to a specific time in seconds.
     * @param {number} time
     */
    seekTo(time) {
        if (this.player?.seekTo) {
            this.player.seekTo(time, true);
        }
    },

    /**
     * Start playback.
     */
    play() {
        this.player?.playVideo?.();
    },

    /**
     * Pause playback.
     */
    pause() {
        this.player?.pauseVideo?.();
    }
};

window.PlayerManager = PlayerManager;
