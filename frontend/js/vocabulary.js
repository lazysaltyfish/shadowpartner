/**
 * Vocabulary Learning Module Composable
 * Provides vocabulary learning features for Japanese subtitles
 */

function useVocabulary({ apiBaseUrl }) {
    // State
    const vocabulary = ref([]);
    const vocabularyStats = ref({});
    const vocabularyLoading = ref(false);
    const vocabularyError = ref(null);
    const selectedJlptLevel = ref(null);
    const searchQuery = ref('');

    // JLPT level filter options
    const jlptLevels = [
        { value: null, label: '全部' },
        { value: 'N1', label: 'N1' },
        { value: 'N2', label: 'N2' },
        { value: 'Business', label: '商务' },
    ];

    // Get JLPT level badge color
    const getJlptBadgeClass = (level) => {
        const colors = {
            'N1': 'bg-rose-100 text-rose-700 border-rose-200',
            'N2': 'bg-amber-100 text-amber-700 border-amber-200',
            'N3': 'bg-emerald-100 text-emerald-700 border-emerald-200',
            'N4': 'bg-sky-100 text-sky-700 border-sky-200',
            'N5': 'bg-slate-100 text-slate-700 border-slate-200',
            'Business': 'bg-purple-100 text-purple-700 border-purple-200',
        };
        return colors[level] || 'bg-gray-100 text-gray-700 border-gray-200';
    };

    // Format timestamp for display
    const formatTimestamp = (seconds) => {
        const minutes = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    };

    // Check if a word contains kanji (Chinese characters)
    // Returns true if the text contains any CJK Unified Ideographs
    const hasKanji = (text) => {
        if (!text) return false;
        // CJK Unified Ideographs block: U+4E00 to U+9FAF
        return /[\u4e00-\u9faf]/.test(text);
    };

    // Filter vocabulary by selected level and search query
    const filteredVocabulary = computed(() => {
        let filtered = vocabulary.value;

        // Filter by JLPT level
        if (selectedJlptLevel.value) {
            filtered = filtered.filter(v => v.jlpt_level === selectedJlptLevel.value);
        }

        // Filter by search query
        if (searchQuery.value.trim()) {
            const query = searchQuery.value.toLowerCase().trim();
            filtered = filtered.filter(v =>
                v.word.toLowerCase().includes(query) ||
                v.reading.toLowerCase().includes(query) ||
                v.meaning_cn.toLowerCase().includes(query) ||
                (v.meaning_en && v.meaning_en.toLowerCase().includes(query))
            );
        }

        return filtered;
    });

    // Total vocabulary count
    const vocabularyCount = computed(() => filteredVocabulary.value.length);

    // Load vocabulary for an asset
    const loadVocabulary = async (assetId) => {
        vocabularyLoading.value = true;
        vocabularyError.value = null;

        try {
            // Use plain fetch (public endpoint, no auth required)
            const url = `${apiBaseUrl.value}/api/assets/${assetId}/vocabulary`;
            const response = await fetch(url, { credentials: 'include' });

            if (!response.ok) {
                if (response.status === 404) {
                    // No vocabulary found
                    vocabulary.value = [];
                    vocabularyStats.value = {};
                    return;
                }
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            vocabulary.value = data.items || [];
            vocabularyStats.value = data.stats || {};
        } catch (error) {
            console.error('Failed to load vocabulary:', error);
            vocabularyError.value = error.message;
            vocabulary.value = [];
            vocabularyStats.value = {};
        } finally {
            vocabularyLoading.value = false;
        }
    };

    // Reset vocabulary state
    const resetVocabulary = () => {
        vocabulary.value = [];
        vocabularyStats.value = {};
        vocabularyError.value = null;
        selectedJlptLevel.value = null;
        searchQuery.value = '';
    };

    // Get unique levels present in vocabulary
    const availableLevels = computed(() => {
        const levels = new Set(vocabulary.value.map(v => v.jlpt_level).filter(Boolean));
        return Array.from(levels);
    });

    // Check if vocabulary is available
    const hasVocabulary = computed(() => vocabulary.value.length > 0);

    return {
        // State
        vocabulary,
        vocabularyStats,
        vocabularyLoading,
        vocabularyError,
        selectedJlptLevel,
        searchQuery,

        // Computed
        filteredVocabulary,
        vocabularyCount,
        availableLevels,
        hasVocabulary,

        // Options
        jlptLevels,

        // Methods
        getJlptBadgeClass,
        formatTimestamp,
        hasKanji,
        loadVocabulary,
        resetVocabulary,
    };
}
