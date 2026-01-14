const { createApp, ref, reactive, onMounted, onUnmounted, nextTick, computed } = Vue;

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
        const sessionId = ref(null);
        const SESSION_STORAGE_KEY = 'shadowpartner_session_id';
        const SESSION_HEADER_NAME = 'X-Session-Id';

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

        // AbortController for canceling requests on page unload
        let abortController = new AbortController();
        let pollTimeoutId = null;
        let healthCheckIntervalId = null;

        const manualUpdateBaseUrl = () => {
             console.log('Manually updating API Base URL to:', apiBaseUrl.value);
             // Remove trailing slash if present
             if (apiBaseUrl.value.endsWith('/')) {
                 apiBaseUrl.value = apiBaseUrl.value.slice(0, -1);
             }
             localStorage.setItem('shadowpartner_api_url', apiBaseUrl.value);
             checkBackendHealth();
        };

        // Backend Health Check
        const checkBackendHealth = async () => {
            try {
                // If user has manually set a URL, prioritize it
                const storedUrl = localStorage.getItem('shadowpartner_api_url');
                if (storedUrl) {
                     apiBaseUrl.value = storedUrl;
                } else {
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
                }

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

        const buildSessionHeaders = (sid) => ({
            [SESSION_HEADER_NAME]: sid
        });

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

        // Cleanup function
        const cleanup = () => {
            abortController.abort();
            if (healthCheckIntervalId) clearInterval(healthCheckIntervalId);
            if (pollTimeoutId) clearTimeout(pollTimeoutId);
            if (window._pollInterval) clearInterval(window._pollInterval);
        };

        // Start checking on mount
        onMounted(() => {
            checkBackendHealth();
            // Poll every 30 seconds
            healthCheckIntervalId = setInterval(checkBackendHealth, 30000);
            // Cleanup on page refresh/close
            window.addEventListener('beforeunload', cleanup);
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

        const updateActiveWords = () => {
            if (!videoData.value) return;

            const segments = videoData.value.segments;
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

        const isWordActive = (word, segment) => {
            // If we don't have word-level timestamps, highlight all words in the current segment
            if (!hasWordTimestamps.value && segment) {
                return currentTime.value >= segment.start && currentTime.value < segment.end;
            }
            // Otherwise, use precise word-level timing
            return currentTime.value >= word.start && currentTime.value < word.end;
        };

        const seekTo = (time) => {
            if (player.value) {
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
            if (!videoData.value?.segments) return null;
            return videoData.value.segments[dictation.segmentIndex];
        };

        const getSegmentText = (segment) => {
            if (!segment?.words) return '';
            return segment.words.map(w => w.text).join('');
        };

        const playCurrentSegment = () => {
            const segment = getCurrentSegment();
            if (!segment || !player.value) return;
            
            player.value.seekTo(Math.max(0, segment.start - 0.3), true);
            player.value.playVideo();
            dictation.isPlaying = true;
        };

        const stopDictationPlayback = () => {
            if (player.value) {
                player.value.pauseVideo();
            }
            dictation.isPlaying = false;
        };

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
            if (!videoData.value?.segments) return;
            if (dictation.segmentIndex < videoData.value.segments.length - 1) {
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

                        // Set warnings BEFORE videoData to ensure modal shows correctly
                        console.log('[Debug] Processing warnings:', statusData.result.warnings);
                        if (statusData.result.warnings && Array.isArray(statusData.result.warnings) && statusData.result.warnings.length > 0) {
                            warnings.value = statusData.result.warnings;
                            console.log('[Debug] Warnings set to UI:', warnings.value);
                        } else {
                            warnings.value = [];
                        }

                        videoData.value = statusData.result;

                        loading.value = false; // Turn off loading BEFORE initPlayer
                        
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
            manualUpdateBaseUrl,
            checkBackendHealth,
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
            handleDictationEnter
        };
    }
}).mount('#app');
