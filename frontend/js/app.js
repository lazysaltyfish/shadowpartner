const { createApp, ref, onMounted, nextTick } = Vue;

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

        // YouTube Player API
        const initPlayer = (videoId) => {
            if (player.value) {
                player.value.loadVideoById(videoId);
                return;
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

        const onPlayerReady = (event) => {
            // Start polling for time
            setInterval(() => {
                if (player.value && player.value.getCurrentTime) {
                    const time = player.value.getCurrentTime();
                    if (Math.abs(time - currentTime.value) > 0.1) { // Only update if significant change
                        currentTime.value = time;
                        updateActiveWords();
                    }
                }
            }, 100);
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
                scrollToSegment(foundSegment);
            }
        };

        const scrollToSegment = (index) => {
            nextTick(() => {
                const el = segmentRefs.value[index];
                if (el && subtitleContainer.value) {
                    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            });
        };

        const isWordActive = (word) => {
            return currentTime.value >= word.start && currentTime.value < word.end;
        };

        const seekTo = (time) => {
            if (player.value) {
                player.value.seekTo(time, true);
                player.value.playVideo();
            }
        };

        const processVideo = async () => {
            if (!videoUrl.value) return;
            
            // Extract Video ID
            const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
            const match = videoUrl.value.match(regExp);
            
            if (!match || match[2].length !== 11) {
                alert('无效的 YouTube 链接');
                return;
            }
            const videoId = match[2];

            loading.value = true;
            videoData.value = null;
            
            try {
                // Determine API URL. Ideally this is configurable.
                // Assuming backend runs on port 8000 on the same host
                const apiUrl = 'http://localhost:8000/api/process';
                
                const response = await fetch(apiUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ url: videoUrl.value })
                });

                if (!response.ok) {
                    throw new Error(`API Error: ${response.statusText}`);
                }
                
                const data = await response.json();
                videoData.value = data;
                initPlayer(videoId);
                
            } catch (e) {
                console.error(e);
                alert(`处理失败: ${e.message}`);
            } finally {
                loading.value = false;
            }
        };

        return {
            videoUrl,
            loading,
            videoData,
            processVideo,
            isWordActive,
            seekTo,
            currentSegmentIndex,
            segmentRefs,
            subtitleContainer
        };
    }
}).mount('#app');

function getMockData(videoId) {
    return {
        video_id: videoId,
        title: "Mock Video",
        segments: [
            {
                translation: "今天天气真好啊。",
                words: [
                    { text: "今日", reading: "きょう", start: 0, end: 0.5 },
                    { text: "は", reading: "は", start: 0.5, end: 0.8 },
                    { text: "いい", reading: "いい", start: 0.8, end: 1.2 },
                    { text: "天気", reading: "てんき", start: 1.2, end: 1.8 },
                    { text: "です", reading: "です", start: 1.8, end: 2.2 },
                    { text: "ね", reading: "ね", start: 2.2, end: 2.5 }
                ]
            },
            {
                translation: "我们去散步吧。",
                words: [
                    { text: "散歩", reading: "さんぽ", start: 3.0, end: 3.5 },
                    { text: "に", reading: "に", start: 3.5, end: 3.7 },
                    { text: "行き", reading: "いき", start: 3.7, end: 4.0 },
                    { text: "ましょう", reading: "ましょう", start: 4.0, end: 4.8 }
                ]
            }
        ]
    };
}
