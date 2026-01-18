/**
 * File upload and video processing composable.
 * Handles file selection, chunked upload, and YouTube URL processing.
 */

/**
 * File upload composable.
 * @param {Object} options - Options containing apiBaseUrl, fetchWithAuth, showToast
 * @returns {Object} Upload state and methods
 */
function useFileUpload({ apiBaseUrl, fetchWithAuth, showToast }) {
    // Upload state
    const loading = Vue.ref(false);
    const videoUrl = Vue.ref('');
    const videoData = Vue.ref(null);
    const selectedFile = Vue.ref(null);
    const selectedSubtitleFile = Vue.ref(null);
    const warnings = Vue.ref([]);
    const assetExists = Vue.ref(null);
    const isFileMode = Vue.ref(false);
    const taskStatus = Vue.ref(null);

    // Input refs
    const fileInput = Vue.ref(null);
    const subtitleInput = Vue.ref(null);

    // Abort controller for polling
    let abortController = new AbortController();
    let pollTimeoutId = null;

    /**
     * Handle file selection from input.
     * @param {Event} event
     */
    const handleFileUpload = (event) => {
        const file = event.target.files[0];
        if (file) {
            selectedFile.value = file;
            videoUrl.value = '';
        }
    };

    /**
     * Handle file drop on dropzone.
     * @param {Event} event
     */
    const handleFileDrop = (event) => {
        const file = event.dataTransfer.files[0];
        if (file && (file.type.startsWith('audio/') || file.type.startsWith('video/'))) {
            selectedFile.value = file;
            videoUrl.value = '';
        }
    };

    /**
     * Handle subtitle file selection.
     * @param {Event} event
     */
    const handleSubtitleUpload = (event) => {
        const file = event.target.files[0];
        if (file) {
            selectedSubtitleFile.value = file;
        }
    };

    /**
     * Clear selected file.
     */
    const clearFile = () => {
        selectedFile.value = null;
        selectedSubtitleFile.value = null;
        if (fileInput.value) fileInput.value.value = '';
        if (subtitleInput.value) subtitleInput.value.value = '';
    };

    /**
     * Clear subtitle file only.
     */
    const clearSubtitleFile = () => {
        selectedSubtitleFile.value = null;
        if (subtitleInput.value) subtitleInput.value.value = '';
    };

    /**
     * Upload a large file in chunks with optional subtitle.
     * @param {File} file
     * @param {File|null} subtitleFile
     * @returns {Promise<string|null>} Task ID or null if asset exists
     */
    const uploadChunks = async (file, subtitleFile) => {
        try {
            const CHUNK_SIZE = 1 * 1024 * 1024; // 1MB chunks
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

                // Update UI progress
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

            // 2.5. Upload subtitle if provided
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
                if (completeRes.status === 409) {
                    const errorData = await completeRes.json();
                    assetExists.value = {
                        assetId: errorData.detail.asset_id,
                        title: errorData.detail.title || file.name
                    };
                    return null; // Asset already exists
                }
                throw new Error("Failed to complete upload");
            }
            return task_id;
        } catch (error) {
            console.error('Upload error:', error);
            throw error;
        }
    };

    /**
     * Extract YouTube video ID from URL.
     * @param {string} url
     * @returns {string|null} Video ID or null
     */
    const extractYouTubeId = (url) => {
        const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
        const match = url.match(regExp);
        if (!match || match[2].length !== 11) {
            return null;
        }
        return match[2];
    };

    /**
     * Start processing for a YouTube URL or uploaded file.
     * @param {Function} onCompleted - Callback when processing completes
     * @returns {Promise<void>}
     */
    const processVideo = async (onCompleted) => {
        if (!videoUrl.value && !selectedFile.value) return;

        // Check for mock trigger
        if (videoUrl.value === 'mock') {
            console.log('Using Mock Data');
            if (window.MOCK_DATA) {
                loading.value = true;
                videoData.value = window.MOCK_DATA.result;
                loading.value = false;
                return;
            }
            console.error("Mock data not found");
            return;
        }

        loading.value = true;
        videoData.value = null;
        warnings.value = [];
        assetExists.value = null;
        taskStatus.value = { status: 'pending', progress: 0, message: 'Initializing...' };

        try {
            const apiUrl = `${apiBaseUrl.value}/api`;
            let response;
            let isFile = !!selectedFile.value;
            isFileMode.value = isFile;
            let data;

            if (isFile) {
                // Check file size (> 5MB uses chunked upload)
                const MAX_SIZE = 5 * 1024 * 1024;
                if (selectedFile.value.size > MAX_SIZE) {
                    console.log('[Debug] Large file detected, using chunked upload');
                    const taskId = await uploadChunks(selectedFile.value, selectedSubtitleFile.value);
                    if (taskId === null && assetExists.value) {
                        loading.value = false;
                        return;
                    }
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
                        if (response.status === 409) {
                            const errorData = await response.json();
                            assetExists.value = {
                                assetId: errorData.detail.asset_id,
                                title: errorData.detail.title || selectedFile.value.name
                            };
                            loading.value = false;
                            return;
                        }
                        throw new Error(`API Error: ${response.statusText}`);
                    }

                    data = await response.json();
                }
            } else {
                // YouTube URL processing
                const videoId = extractYouTubeId(videoUrl.value);
                if (!videoId) {
                    showToast('无效的 YouTube 链接', 'error');
                    loading.value = false;
                    return;
                }

                response = await fetchWithAuth(`${apiUrl}/process`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: videoUrl.value })
                });

                if (!response.ok) {
                    if (response.status === 409) {
                        const errorData = await response.json();
                        assetExists.value = {
                            assetId: errorData.detail.asset_id,
                            title: errorData.detail.title || videoUrl.value
                        };
                        loading.value = false;
                        return;
                    }
                    throw new Error(`API Error: ${response.statusText}`);
                }

                data = await response.json();
            }

            // Start polling for status
            if (data.task_id) {
                await pollStatus(data.task_id, onCompleted);
            } else {
                // Immediate response (shouldn't happen with current backend)
                videoData.value = data;
                loading.value = false;
            }

        } catch (e) {
            console.error(e);
            showToast(`处理失败: ${e.message}`, 'error');
            loading.value = false;
        }
    };

    /**
     * Poll backend task status until completion or failure.
     * @param {string} taskId
     * @param {Function} onCompleted - Callback when processing completes
     * @returns {Promise<void>}
     */
    const pollStatus = async (taskId, onCompleted) => {
        const pollInterval = 5000;

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

                    if (statusData.result.metrics) {
                        console.log('%c ✨ Metrics ✨', 'color: #22C55E; font-size: 1.2em; font-weight: bold; padding: 5px;');
                        console.table(statusData.result.metrics);
                    }

                    loading.value = false;

                    // Call completion callback
                    if (onCompleted) {
                        await onCompleted(statusData.result);
                    }

                } else if (statusData.status === 'failed') {
                    throw new Error(statusData.error || "Processing failed");
                } else {
                    // Continue polling
                    pollTimeoutId = setTimeout(check, pollInterval);
                }
            } catch (e) {
                if (e.name === 'AbortError') {
                    console.log('[Debug] Polling aborted');
                    return;
                }
                console.error("Polling error:", e);
                showToast(`处理出错: ${e.message}`, 'error');
                loading.value = false;
            }
        };

        check();
    };

    /**
     * Reset upload state.
     */
    const resetUploadState = () => {
        videoUrl.value = '';
        videoData.value = null;
        selectedFile.value = null;
        selectedSubtitleFile.value = null;
        warnings.value = [];
        assetExists.value = null;
        isFileMode.value = false;
        taskStatus.value = null;
        if (fileInput.value) fileInput.value.value = '';
        if (subtitleInput.value) subtitleInput.value.value = '';
    };

    /**
     * Cleanup polling.
     */
    const cleanupPolling = () => {
        abortController.abort();
        if (pollTimeoutId) {
            clearTimeout(pollTimeoutId);
            pollTimeoutId = null;
        }
    };

    return {
        // State
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

        // Methods
        handleFileUpload,
        handleFileDrop,
        handleSubtitleUpload,
        clearFile,
        clearSubtitleFile,
        processVideo,
        resetUploadState,
        cleanupPolling,
        extractYouTubeId
    };
}

// Attach to global scope for use in app.js
window.useFileUpload = useFileUpload;
