const { createApp, ref, onMounted, nextTick, computed } = Vue;

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
        const isFileMode = ref(false); // New state to track if we're using file or URL
        const contextRange = ref(2); // Number of segments to show before and after current
        const backendStatus = ref({
            online: false,
            lastCheck: null
        });
        const taskStatus = ref(null); // { status: 'pending', progress: 0, message: '' }
        const apiBaseUrl = ref('http://localhost:8000');

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
                const response = await fetch(`${apiBaseUrl.value}/`, { credentials: 'include' });
                if (response.ok) {
                    backendStatus.value = { online: true, lastCheck: new Date() };
                } else {
                    throw new Error('Backend returned non-200');
                }
            } catch (e) {
                console.error('Backend health check failed:', e);
                backendStatus.value = { online: false, lastCheck: new Date() };
            }
        };

        // Start checking on mount
        onMounted(() => {
            checkBackendHealth();
            // Poll every 30 seconds
            setInterval(checkBackendHealth, 30000);
        });

        // YouTube Player API
        const initPlayer = (videoId) => {
            if (player.value && typeof player.value.loadVideoById === 'function') {
                player.value.loadVideoById(videoId);
                return;
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

        // File Audio/Video Player
        const initFilePlayer = (file) => {
            // Destroy YouTube player if it exists
             if (player.value && typeof player.value.destroy === 'function') {
                 player.value.destroy();
                 player.value = null;
             }
             
             // Clear container
             const container = document.getElementById('youtube-player');
             if (container) {
                 container.innerHTML = '';
                 container.className = "w-full h-full flex items-center justify-center bg-gray-900";

                 // Create Video or Audio element
                 const isVideo = file.type.startsWith('video/');
                 const mediaEl = document.createElement(isVideo ? 'video' : 'audio');
                 mediaEl.src = URL.createObjectURL(file);
                 mediaEl.controls = true;
                 mediaEl.className = "max-w-full max-h-full";
                 mediaEl.style.width = isVideo ? "100%" : "80%"; // Make audio player smaller width
                 
                 container.appendChild(mediaEl);
                 
                 // Wrap into a consistent interface for our app logic
                 player.value = {
                     getCurrentTime: () => mediaEl.currentTime,
                     seekTo: (time, allowSeekAhead) => { mediaEl.currentTime = time; },
                     playVideo: () => mediaEl.play(),
                     pauseVideo: () => mediaEl.pause(),
                     // Custom property to identify as non-YT
                     isNative: true
                 };

                 // Start polling loop manually since no 'onReady' event like YT
                 startPolling();
             } else {
                 console.error("Player container not found");
             }
        };

        const startPolling = () => {
             // Clear existing interval if any
             if (window._pollInterval) clearInterval(window._pollInterval);

             window._pollInterval = setInterval(() => {
                if (player.value && player.value.getCurrentTime) {
                    const time = player.value.getCurrentTime();
                    if (Math.abs(time - currentTime.value) > 0.1) {
                        currentTime.value = time;
                        updateActiveWords();
                    }
                }
            }, 100);
        };

        const onPlayerReady = (event) => {
            startPolling();
        };

        const onPlayerStateChange = (event) => {
            // Can handle play/pause states here
        };

        const updateActiveWords = () => {
            if (!videoData.value) return;

            const segments = videoData.value.segments;
            let foundSegment = -1;

            // Simple search (can be optimized with binary search if needed)
            for (let i = 0; i < segments.length; i++) {
                const seg = segments[i];
                if (!seg.words.length) continue;
                
                const start = seg.words[0].start;
                const end = seg.words[seg.words.length - 1].end;
                
                // Allow a small buffer for segment selection
                if (currentTime.value >= start - 0.5 && currentTime.value <= end + 0.5) {
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

        const isWordActive = (word) => {
            return currentTime.value >= word.start && currentTime.value < word.end;
        };

        const seekTo = (time) => {
            if (player.value) {
                player.value.seekTo(time, true);
                if (player.value.playVideo) player.value.playVideo();
            }
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
            const CHUNK_SIZE = 1 * 1024 * 1024; // 1MB chunks to be safe
            const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
            const apiUrl = `${apiBaseUrl.value}/api`;
            
            // 1. Init
            const initFormData = new FormData();
            initFormData.append('filename', file.name);
            const initRes = await fetch(`${apiUrl}/upload/init`, {
                method: 'POST',
                body: initFormData,
                credentials: 'include'
            });
            if (!initRes.ok) throw new Error("Failed to init upload");
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
                
                const chunkRes = await fetch(`${apiUrl}/upload/chunk`, {
                    method: 'POST',
                    body: chunkFormData,
                    credentials: 'include'
                });
                
                if (!chunkRes.ok) throw new Error(`Failed to upload chunk ${i}`);
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
                
                const subtitleRes = await fetch(`${apiUrl}/upload/subtitle`, {
                    method: 'POST',
                    body: subtitleFormData,
                    credentials: 'include'
                });
                
                if (!subtitleRes.ok) {
                    console.warn('Failed to upload subtitle, continuing without it');
                }
            }
            
            // 3. Complete
            const completeFormData = new FormData();
            completeFormData.append('task_id', task_id);
            completeFormData.append('filename', file.name);
            if (subtitleFile) {
                completeFormData.append('subtitle_filename', subtitleFile.name);
            }
            
            const completeRes = await fetch(`${apiUrl}/upload/complete`, {
                method: 'POST',
                body: completeFormData,
                credentials: 'include'
            });
            
            if (!completeRes.ok) throw new Error("Failed to complete upload");
            return task_id;
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
                        
                        response = await fetch(`${apiUrl}/upload`, {
                            method: 'POST',
                            body: formData,
                            credentials: 'include'
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

                    response = await fetch(`${apiUrl}/process`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ url: videoUrl.value }),
                        credentials: 'include'
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
                        if (isFile) {
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
            
            const check = async () => {
                try {
                    const response = await fetch(`${apiBaseUrl.value}/api/status/${taskId}`, { credentials: 'include' });
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
                        setTimeout(check, pollInterval);
                    }
                } catch (e) {
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
            visibleSegments, // Export this so template can use it
            contextRange,    // Export for potential UI control
            processVideo,
            isWordActive,
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
            taskStatus
        };
    }
}).mount('#app');
