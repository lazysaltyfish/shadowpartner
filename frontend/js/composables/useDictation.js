/**
 * Dictation/Listening game mode composable.
 * Handles segment navigation, answer checking, and scoring.
 */

/**
 * Normalize Japanese text for comparison.
 * @param {string} str
 * @returns {string}
 */
function normalizeJapanese(str) {
    return str
        .normalize('NFKC')
        .replace(/[\s\u3000]/g, '')
        .replace(/[。、！？「」『』（）・]/g, '');
}

/**
 * Convert katakana to hiragana.
 * @param {string} str
 * @returns {string}
 */
function katakanaToHiragana(str) {
    return str.replace(/[\u30A1-\u30F6]/g, (match) => {
        return String.fromCharCode(match.charCodeAt(0) - 0x60);
    });
}

/**
 * Dictation game mode composable.
 * @returns {Object} Dictation state and methods
 */
function useDictation() {
    const dictation = Vue.reactive({
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

    const targetPauseTime = Vue.ref(null);


    /**
     * Get current dictation text from segment.
     * @param {Object} videoData - Video data with segments
     * @returns {string} Current segment text
     */
    const getCurrentDictationText = (videoData) => {
        const segment = videoData?.segments?.[dictation.segmentIndex];
        if (!segment?.words) return '';
        return segment.words.map(w => w.text).join('');
    };

    /**
     * Get current segment object.
     * @param {Object} videoData - Video data with segments
     * @returns {Object|null} Current segment
     */
    const getCurrentSegment = (videoData) => {
        if (!videoData?.segments) return null;
        return videoData.segments[dictation.segmentIndex];
    };

    /**
     * Get segment text from words.
     * @param {Object} segment - Segment object
     * @returns {string} Segment text
     */
    const getSegmentText = (segment) => {
        if (!segment?.words) return '';
        return segment.words.map(w => w.text).join('');
    };

    /**
     * Generate diff result between correct and user input.
     * @param {string} correct - Correct text
     * @param {string} user - User input
     * @returns {Object} Diff result and score
     */
    const generateDiff = (correct, user) => {
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

    /**
     * Check the user's answer against the correct text.
     * @param {Object} videoData - Video data with segments
     */
    const checkAnswer = (videoData) => {
        const segment = getCurrentSegment(videoData);
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

    /**
     * Go to previous segment.
     */
    const gotoPrevSegment = () => {
        if (dictation.segmentIndex > 0) {
            dictation.segmentIndex--;
            resetDictationInput();
        }
    };

    /**
     * Go to next segment.
     * @param {Object} videoData - Video data with segments
     */
    const gotoNextSegment = (videoData) => {
        if (!videoData?.segments) return;
        if (dictation.segmentIndex < videoData.segments.length - 1) {
            dictation.segmentIndex++;
            resetDictationInput();
        }
    };

    /**
     * Skip current segment.
     * @param {Object} videoData - Video data with segments
     */
    const skipCurrentSegment = (videoData) => {
        dictation.statusByIndex[dictation.segmentIndex] = 'skipped';
        gotoNextSegment(videoData);
    };

    /**
     * Reset dictation input state.
     */
    const resetDictationInput = () => {
        dictation.userInput = '';
        dictation.mode = 'listen';
        dictation.diffResult = [];
        dictation.currentScore = null;
    };

    /**
     * Handle main action (check answer or go to next).
     * @param {Object} videoData - Video data with segments
     */
    const handleDictationMainAction = (videoData) => {
        if (dictation.mode === 'review') {
            gotoNextSegment(videoData);
        } else {
            checkAnswer(videoData);
        }
    };

    /**
     * Handle Enter key in dictation input.
     * @param {Object} videoData - Video data with segments
     */
    const handleDictationEnter = (videoData) => {
        if (dictation.isComposing) return;
        handleDictationMainAction(videoData);
    };

    /**
     * Toggle dictation playback state.
     * @param {Function} playFn - Function to play current segment
     * @param {Function} stopFn - Function to stop playback
     */
    const toggleDictationPlayback = (playFn, stopFn) => {
        if (dictation.isPlaying) {
            stopFn();
        } else {
            playFn();
        }
    };

    /**
     * Calculate progress based on video data.
     * @param {Object} videoData - Video data with segments
     * @returns {number} Progress 0-100
     */
    const getDictationProgress = (videoData) => {
        if (!videoData?.segments?.length) return 0;
        return Math.round((dictation.segmentIndex / videoData.segments.length) * 100);
    };

    /**
     * Reset dictation state when loading new asset.
     */
    const resetDictationState = () => {
        dictation.segmentIndex = 0;
        dictation.mode = 'listen';
        dictation.userInput = '';
        dictation.isPlaying = false;
        dictation.diffResult = [];
        dictation.currentScore = null;
    };

    return {
        // State
        dictation,
        targetPauseTime,

        // Methods
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
        resetDictationState
    };
}

// Attach to global scope for use in app.js
window.useDictation = useDictation;
