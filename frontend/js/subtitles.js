/**
 * Subtitles Module for ShadowPartner
 * Handles subtitle rendering and synchronization
 */

const SubtitleManager = {
    segments: [],
    currentTime: 0,
    currentSegmentIndex: -1,
    hasWordTimestamps: true,
    contextRange: 2,
    /**
     * Optional hook invoked when the active segment changes.
     * @type {(index: number) => void | null}
     */
    onSegmentChange: null,

    /**
     * Load segments data
     * @param {Array} segments - Subtitle segments
     * @param {boolean} hasWordTimestamps - Whether segments have word-level timestamps
     */
    load(segments, hasWordTimestamps = true) {
        this.segments = segments || [];
        this.hasWordTimestamps = hasWordTimestamps;
        this.currentSegmentIndex = -1;
    },

    /**
     * Update current time and find active segment
     * @param {number} time - Current playback time
     */
    updateTime(time) {
        this.currentTime = time;
        let foundSegment = -1;

        // Find the last segment that starts before current time
        for (let i = this.segments.length - 1; i >= 0; i--) {
            if (time >= this.segments[i].start) {
                foundSegment = i;
                break;
            }
        }

        if (foundSegment !== -1 && foundSegment !== this.currentSegmentIndex) {
            this.currentSegmentIndex = foundSegment;
            if (this.onSegmentChange) {
                this.onSegmentChange(foundSegment);
            }
        }
    },

    /**
     * Get visible segments (current + context)
     * @returns {Array}
     */
    getVisibleSegments() {
        if (!this.segments.length) return [];

        const current = this.currentSegmentIndex === -1 ? 0 : this.currentSegmentIndex;
        const start = Math.max(0, current - this.contextRange);
        const end = Math.min(this.segments.length, current + this.contextRange + 1);

        return this.segments.slice(start, end).map((seg, index) => ({
            ...seg,
            originalIndex: start + index
        }));
    },

    /**
     * Check if a word is currently active
     * @param {object} word - Word object
     * @param {object} segment - Parent segment
     * @returns {boolean}
     */
    isWordActive(word, segment) {
        if (!this.hasWordTimestamps && segment) {
            return this.currentTime >= segment.start && this.currentTime < segment.end;
        }
        return this.currentTime >= word.start && this.currentTime < word.end;
    },

    /**
     * Check if a segment is current
     * @param {number} index - Segment index
     * @returns {boolean}
     */
    isCurrentSegment(index) {
        return index === this.currentSegmentIndex;
    },

    /**
     * Get segment by index
     * @param {number} index - Segment index
     * @returns {object|null}
     */
    getSegment(index) {
        return this.segments[index] || null;
    },

    /**
     * Get total segment count
     * @returns {number}
     */
    getSegmentCount() {
        return this.segments.length;
    }
};

window.SubtitleManager = SubtitleManager;
