#include "recipe_engine_v3.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <math.h>

#define INITIAL_ELEM_CAPACITY 4096
#define INITIAL_PAIR_CAPACITY 262144
#define LOAD_FACTOR_THRESHOLD 0.70
#define MAX_CATALYSTS 32
#define DEFAULT_MAX_DEPTH_DELTA 2

// Known high-valence universal transformer concepts
static const char* INTRINSIC_CATALYST_NAMES[] = {
    "water", "fire", "earth", "wind",
    "life", "human", "death", "god",
    "space", "time", "engine", "robot",
    "philosophy", "love", "magic", "universe",
    "planet", "dragon", "monster", "war",
    "hero", "city", "music", "science",
    "light", "darkness", "electricity", "energy",
    "star", "sun", "moon", "atom", "plant", "metal"
};
static const int INTRINSIC_CATALYST_COUNT = sizeof(INTRINSIC_CATALYST_NAMES) / sizeof(INTRINSIC_CATALYST_NAMES[0]);

// FNV-1a 64-bit string hash
static inline uint64_t hash_string(const char* str) {
    uint64_t hash = 14695981039346656037ULL;
    while (*str) {
        char c = (char)tolower((unsigned char)*str);
        hash ^= (uint64_t)c;
        hash *= 1099511628211ULL;
        str++;
    }
    return hash;
}

// MurmurHash3 64-bit integer finalizer
static inline uint64_t hash_uint64(uint64_t k) {
    k ^= k >> 33;
    k *= 0xff51afd7ed558ccdULL;
    k ^= k >> 33;
    k *= 0xc4ceb9fe1a85ec53ULL;
    k ^= k >> 33;
    return k;
}

static inline uint64_t make_pair_key(int a, int b) {
    uint32_t u = (uint32_t)(a < b ? a : b);
    uint32_t v = (uint32_t)(a < b ? b : a);
    return ((uint64_t)u << 32) | (uint64_t)v;
}

static inline bool str_case_eq(const char* s1, const char* s2) {
    while (*s1 && *s2) {
        if (tolower((unsigned char)*s1) != tolower((unsigned char)*s2)) return false;
        s1++;
        s2++;
    }
    return *s1 == *s2;
}

static bool is_intrinsic_catalyst(const char* name) {
    for (int i = 0; i < INTRINSIC_CATALYST_COUNT; i++) {
        if (str_case_eq(name, INTRINSIC_CATALYST_NAMES[i])) {
            return true;
        }
    }
    return false;
}

// Check if one string is a substring / plural / stem derivative of another
static bool is_morphological_redundant(const char* s1, const char* s2) {
    int len1 = (int)strlen(s1);
    int len2 = (int)strlen(s2);
    if (len1 < 3 || len2 < 3) return false;

    const char* shorter = len1 <= len2 ? s1 : s2;
    const char* longer = len1 <= len2 ? s2 : s1;
    int slen = len1 <= len2 ? len1 : len2;
    int llen = len1 <= len2 ? len2 : len1;

    // Plural check (e.g. "Cat" vs "Cats")
    if (llen == slen + 1 && (longer[llen - 1] == 's' || longer[llen - 1] == 'S')) {
        char buf[MAX_NAME_LEN];
        strncpy(buf, longer, slen);
        buf[slen] = '\0';
        if (str_case_eq(buf, shorter)) return true;
    }

    // Substring stem check (e.g. "Rain" vs "Rainbow", "Earth" vs "Earthquake")
    if (slen >= 4 && llen > slen) {
        char buf[MAX_NAME_LEN];
        strncpy(buf, longer, slen);
        buf[slen] = '\0';
        if (str_case_eq(buf, shorter)) return true;
    }

    return false;
}

// --- Internal Data Structures ---

typedef struct {
    char name[MAX_NAME_LEN];
    int elem_id;
} NameHashEntry;

typedef struct {
    Element* elements;
    int count;
    int capacity;

    NameHashEntry* name_table;
    int name_table_capacity;
    int name_table_count;

    PairEntry* pair_table;
    uint32_t pair_table_capacity;
    uint32_t pair_table_count;
    int in_flight_count;
    int tested_count;
    int pruned_count;

    // Strategy & threshold configuration
    int strategy;
    float min_fertility_threshold;
    int max_depth_delta;
    int catalyst_cap;

    // Top catalyst element IDs
    int catalysts[MAX_CATALYSTS];
    int catalyst_count;

    // Frontier tracking for intelligent exploration
    int* frontier_ids;
    int frontier_head;
    int frontier_tail;
    int frontier_capacity;

    // First discovery tracking queue
    int* first_discovery_ids;
    int fd_head;
    int fd_tail;
    int fd_capacity;
    int fd_catalyst_idx;
    int fd_peer_idx;

    // Self-combine pending queue
    int* self_combine_ids;
    int self_head;
    int self_tail;
    int self_capacity;

    // Catalyst combine cursor
    int catalyst_frontier_idx;
    int catalyst_list_idx;

    // Frontier partner cursor
    int current_frontier_partner;

    // Generation cross-pollination cursor
    int gen_window_head;
    int gen_window_tail;
} EngineState;

static EngineState g_state = {0};
static bool g_initialized = false;

// Forward declarations
static bool resize_name_table(void);
static bool resize_pair_table(void);
static void update_catalysts(void);

ENGINE_API bool engine_init(void) {
    if (g_initialized) {
        engine_cleanup();
    }

    g_state.capacity = INITIAL_ELEM_CAPACITY;
    g_state.elements = (Element*)calloc(g_state.capacity, sizeof(Element));
    if (!g_state.elements) return false;

    g_state.name_table_capacity = INITIAL_ELEM_CAPACITY * 2;
    g_state.name_table = (NameHashEntry*)calloc(g_state.name_table_capacity, sizeof(NameHashEntry));
    for (int i = 0; i < g_state.name_table_capacity; i++) {
        g_state.name_table[i].elem_id = -1;
    }

    g_state.pair_table_capacity = INITIAL_PAIR_CAPACITY;
    g_state.pair_table = (PairEntry*)calloc(g_state.pair_table_capacity, sizeof(PairEntry));
    for (uint32_t i = 0; i < g_state.pair_table_capacity; i++) {
        g_state.pair_table[i].status = PAIR_STATUS_EMPTY;
    }

    g_state.frontier_capacity = INITIAL_ELEM_CAPACITY;
    g_state.frontier_ids = (int*)malloc(g_state.frontier_capacity * sizeof(int));
    g_state.frontier_head = 0;
    g_state.frontier_tail = 0;

    g_state.fd_capacity = 1024;
    g_state.first_discovery_ids = (int*)malloc(g_state.fd_capacity * sizeof(int));
    g_state.fd_head = 0;
    g_state.fd_tail = 0;
    g_state.fd_catalyst_idx = 0;
    g_state.fd_peer_idx = 0;

    g_state.self_capacity = INITIAL_ELEM_CAPACITY;
    g_state.self_combine_ids = (int*)malloc(g_state.self_capacity * sizeof(int));
    g_state.self_head = 0;
    g_state.self_tail = 0;

    g_state.catalyst_frontier_idx = 0;
    g_state.catalyst_list_idx = 0;
    g_state.current_frontier_partner = 0;

    g_state.strategy = STRATEGY_SMART_HEURISTIC;
    g_state.min_fertility_threshold = 0.04f;
    g_state.max_depth_delta = DEFAULT_MAX_DEPTH_DELTA;
    g_state.catalyst_cap = 24;
    g_state.catalyst_count = 0;

    g_initialized = true;
    return true;
}

ENGINE_API void engine_cleanup(void) {
    if (!g_initialized) return;

    if (g_state.elements) free(g_state.elements);
    if (g_state.name_table) free(g_state.name_table);
    if (g_state.pair_table) free(g_state.pair_table);
    if (g_state.frontier_ids) free(g_state.frontier_ids);
    if (g_state.first_discovery_ids) free(g_state.first_discovery_ids);
    if (g_state.self_combine_ids) free(g_state.self_combine_ids);

    memset(&g_state, 0, sizeof(EngineState));
    g_initialized = false;
}

ENGINE_API void engine_reset(void) {
    int strat = g_state.strategy;
    float thresh = g_state.min_fertility_threshold;
    int delta = g_state.max_depth_delta;
    int cap = g_state.catalyst_cap;

    engine_cleanup();
    engine_init();

    g_state.strategy = strat;
    g_state.min_fertility_threshold = thresh;
    g_state.max_depth_delta = delta;
    g_state.catalyst_cap = cap;
}

ENGINE_API void engine_set_strategy(int strategy) {
    if (g_initialized) {
        g_state.strategy = strategy;
    }
}

ENGINE_API void engine_set_prune_threshold(float min_fertility) {
    if (g_initialized) {
        g_state.min_fertility_threshold = min_fertility;
    }
}

ENGINE_API void engine_set_max_depth_delta(int max_delta) {
    if (g_initialized) {
        g_state.max_depth_delta = max_delta < 1 ? 1 : max_delta;
    }
}

ENGINE_API void engine_set_catalyst_cap(int k) {
    if (g_initialized) {
        g_state.catalyst_cap = k > MAX_CATALYSTS ? MAX_CATALYSTS : (k < 4 ? 4 : k);
    }
}

// Internal Name Hash Table Lookup
static int find_name_slot(const char* name) {
    uint64_t h = hash_string(name);
    uint32_t mask = g_state.name_table_capacity - 1;
    uint32_t idx = (uint32_t)(h & mask);

    while (g_state.name_table[idx].elem_id != -1) {
        if (str_case_eq(g_state.name_table[idx].name, name)) {
            return idx; // Found existing
        }
        idx = (idx + 1) & mask;
    }
    return idx; // Empty slot
}

static bool resize_name_table(void) {
    int old_cap = g_state.name_table_capacity;
    NameHashEntry* old_table = g_state.name_table;

    int new_cap = old_cap * 2;
    NameHashEntry* new_table = (NameHashEntry*)calloc(new_cap, sizeof(NameHashEntry));
    if (!new_table) return false;

    for (int i = 0; i < new_cap; i++) {
        new_table[i].elem_id = -1;
    }

    g_state.name_table = new_table;
    g_state.name_table_capacity = new_cap;

    uint32_t mask = new_cap - 1;
    for (int i = 0; i < old_cap; i++) {
        if (old_table[i].elem_id != -1) {
            uint64_t h = hash_string(old_table[i].name);
            uint32_t idx = (uint32_t)(h & mask);
            while (new_table[idx].elem_id != -1) {
                idx = (idx + 1) & mask;
            }
            new_table[idx] = old_table[i];
        }
    }

    free(old_table);
    return true;
}

// Internal Pair Table Lookup
static PairEntry* find_pair_entry(uint64_t key) {
    uint32_t mask = g_state.pair_table_capacity - 1;
    uint32_t idx = (uint32_t)(hash_uint64(key) & mask);

    while (g_state.pair_table[idx].status != PAIR_STATUS_EMPTY) {
        if (g_state.pair_table[idx].key == key) {
            return &g_state.pair_table[idx];
        }
        idx = (idx + 1) & mask;
    }
    return &g_state.pair_table[idx];
}

static bool resize_pair_table(void) {
    uint32_t old_cap = g_state.pair_table_capacity;
    PairEntry* old_table = g_state.pair_table;

    uint32_t new_cap = old_cap * 2;
    PairEntry* new_table = (PairEntry*)calloc(new_cap, sizeof(PairEntry));
    if (!new_table) return false;

    for (uint32_t i = 0; i < new_cap; i++) {
        new_table[i].status = PAIR_STATUS_EMPTY;
    }

    g_state.pair_table = new_table;
    g_state.pair_table_capacity = new_cap;

    uint32_t mask = new_cap - 1;
    for (uint32_t i = 0; i < old_cap; i++) {
        if (old_table[i].status != PAIR_STATUS_EMPTY) {
            uint32_t idx = (uint32_t)(hash_uint64(old_table[i].key) & mask);
            while (new_table[idx].status != PAIR_STATUS_EMPTY) {
                idx = (idx + 1) & mask;
            }
            new_table[idx] = old_table[i];
        }
    }

    free(old_table);
    return true;
}

static void push_frontier(int id) {
    if (g_state.frontier_tail >= g_state.frontier_capacity) {
        g_state.frontier_capacity *= 2;
        g_state.frontier_ids = (int*)realloc(g_state.frontier_ids, g_state.frontier_capacity * sizeof(int));
    }
    g_state.frontier_ids[g_state.frontier_tail++] = id;
}

static void push_first_discovery(int id) {
    if (g_state.fd_tail >= g_state.fd_capacity) {
        g_state.fd_capacity *= 2;
        g_state.first_discovery_ids = (int*)realloc(g_state.first_discovery_ids, g_state.fd_capacity * sizeof(int));
    }
    g_state.first_discovery_ids[g_state.fd_tail++] = id;
}

static void push_self_combine(int id) {
    if (g_state.self_tail >= g_state.self_capacity) {
        g_state.self_capacity *= 2;
        g_state.self_combine_ids = (int*)realloc(g_state.self_combine_ids, g_state.self_capacity * sizeof(int));
    }
    g_state.self_combine_ids[g_state.self_tail++] = id;
}

ENGINE_API int engine_find_element(const char* name) {
    if (!g_initialized || !name || !*name) return -1;
    int slot = find_name_slot(name);
    return g_state.name_table[slot].elem_id;
}

ENGINE_API int engine_add_element(const char* name, const char* emoji, bool is_first_discovery, int depth) {
    if (!g_initialized || !name || !*name) return -1;

    int existing = engine_find_element(name);
    if (existing >= 0) {
        if (is_first_discovery && !g_state.elements[existing].is_first_discovery) {
            g_state.elements[existing].is_first_discovery = true;
            push_first_discovery(existing);
        }
        return existing;
    }

    if (g_state.count >= g_state.capacity) {
        g_state.capacity *= 2;
        g_state.elements = (Element*)realloc(g_state.elements, g_state.capacity * sizeof(Element));
    }

    if ((double)(g_state.name_table_count + 1) / g_state.name_table_capacity > LOAD_FACTOR_THRESHOLD) {
        resize_name_table();
    }

    int id = g_state.count++;
    Element* el = &g_state.elements[id];
    el->id = id;
    strncpy(el->name, name, MAX_NAME_LEN - 1);
    el->name[MAX_NAME_LEN - 1] = '\0';
    strncpy(el->emoji, emoji ? emoji : "✨", MAX_EMOJI_LEN - 1);
    el->emoji[MAX_EMOJI_LEN - 1] = '\0';
    el->is_first_discovery = is_first_discovery;
    el->depth = depth;
    el->trials_count = 0;
    el->success_count = 0;

    // Intrinsic catalyst bonus
    bool intrinsic = is_intrinsic_catalyst(name);
    el->fertility = intrinsic ? 0.45f : 0.333f;
    el->is_catalyst = intrinsic;

    // Insert into hash table
    int slot = find_name_slot(name);
    g_state.name_table[slot].elem_id = id;
    strncpy(g_state.name_table[slot].name, name, MAX_NAME_LEN - 1);
    g_state.name_table[slot].name[MAX_NAME_LEN - 1] = '\0';
    g_state.name_table_count++;

    // Add to pending queues
    push_frontier(id);
    push_self_combine(id);
    if (is_first_discovery) {
        push_first_discovery(id);
    }

    return id;
}

ENGINE_API bool engine_get_element(int id, Element* out_element) {
    if (!g_initialized || id < 0 || id >= g_state.count || !out_element) return false;
    *out_element = g_state.elements[id];
    return true;
}

ENGINE_API int engine_get_element_count(void) {
    return g_initialized ? g_state.count : 0;
}

ENGINE_API int engine_is_tested(int elem_a, int elem_b) {
    if (!g_initialized) return PAIR_STATUS_EMPTY;
    uint64_t key = make_pair_key(elem_a, elem_b);
    PairEntry* entry = find_pair_entry(key);
    if (!entry || entry->status == PAIR_STATUS_EMPTY) {
        return PAIR_STATUS_EMPTY;
    }
    return entry->status;
}

ENGINE_API int engine_get_result(int elem_a, int elem_b) {
    if (!g_initialized) return -2;
    uint64_t key = make_pair_key(elem_a, elem_b);
    PairEntry* entry = find_pair_entry(key);
    if (!entry || entry->status != PAIR_STATUS_TESTED) {
        return -2;
    }
    return entry->result_id;
}

// Update catalysts by comprehensive ranking: success yield + fertility + novelty + intrinsic hub (Single pass O(N*K))
static void update_catalysts(void) {
    int n = g_state.count;
    if (n <= 0) return;

    int target_cap = g_state.catalyst_cap;
    if (target_cap > MAX_CATALYSTS) target_cap = MAX_CATALYSTS;
    int top_count = n < target_cap ? n : target_cap;

    float best_scores[MAX_CATALYSTS];
    int best_ids[MAX_CATALYSTS];
    for (int k = 0; k < top_count; k++) {
        best_scores[k] = -1e9f;
        best_ids[k] = -1;
    }

    for (int i = 0; i < n; i++) {
        g_state.elements[i].is_catalyst = false;
        Element* el = &g_state.elements[i];
        float score = (float)el->success_count * 4.0f + el->fertility * 12.0f;
        if (el->is_first_discovery) score += 8.0f;
        if (is_intrinsic_catalyst(el->name)) score += 18.0f;
        if (el->trials_count > 150 && el->fertility < 0.05f) score -= 15.0f;

        if (score > best_scores[top_count - 1]) {
            int pos = top_count - 1;
            while (pos > 0 && score > best_scores[pos - 1]) {
                best_scores[pos] = best_scores[pos - 1];
                best_ids[pos] = best_ids[pos - 1];
                pos--;
            }
            best_scores[pos] = score;
            best_ids[pos] = i;
        }
    }

    for (int k = 0; k < top_count; k++) {
        g_state.catalysts[k] = best_ids[k];
        if (best_ids[k] >= 0) {
            g_state.elements[best_ids[k]].is_catalyst = true;
        }
    }
    g_state.catalyst_count = top_count;
}

ENGINE_API bool engine_record_result(int elem_a, int elem_b, int result_id, bool is_new_element) {
    if (!g_initialized) return false;

    if ((double)(g_state.pair_table_count + 1) / g_state.pair_table_capacity > LOAD_FACTOR_THRESHOLD) {
        resize_pair_table();
    }

    uint64_t key = make_pair_key(elem_a, elem_b);
    PairEntry* entry = find_pair_entry(key);
    if (!entry) return false;

    bool was_in_flight = (entry->status == PAIR_STATUS_IN_FLIGHT);

    entry->key = key;
    entry->elem_a = elem_a < elem_b ? elem_a : elem_b;
    entry->elem_b = elem_a < elem_b ? elem_b : elem_a;
    entry->result_id = result_id;
    entry->status = PAIR_STATUS_TESTED;

    if (was_in_flight) {
        g_state.in_flight_count--;
    } else {
        g_state.pair_table_count++;
    }
    g_state.tested_count++;

    // Update fertility statistics for both elements
    if (elem_a >= 0 && elem_a < g_state.count) {
        Element* ea = &g_state.elements[elem_a];
        ea->trials_count++;
        if (is_new_element) ea->success_count++;
        ea->fertility = (float)(ea->success_count + 1.0f) / (float)(ea->trials_count + 3.0f);
    }
    if (elem_b >= 0 && elem_b < g_state.count && elem_b != elem_a) {
        Element* eb = &g_state.elements[elem_b];
        eb->trials_count++;
        if (is_new_element) eb->success_count++;
        eb->fertility = (float)(eb->success_count + 1.0f) / (float)(eb->trials_count + 3.0f);
    }

    // Refresh catalysts on new discoveries or periodically (avoids bottleneck on large sets)
    if (is_new_element || (g_state.tested_count % 500 == 0)) {
        update_catalysts();
    }

    return true;
}

ENGINE_API void engine_revert_in_flight(int elem_a, int elem_b) {
    if (!g_initialized) return;
    uint64_t key = make_pair_key(elem_a, elem_b);
    PairEntry* entry = find_pair_entry(key);
    if (entry && entry->status == PAIR_STATUS_IN_FLIGHT) {
        entry->status = PAIR_STATUS_EMPTY;
        g_state.in_flight_count--;
        g_state.pair_table_count--;
    }
}

static void mark_in_flight(int elem_a, int elem_b) {
    if ((double)(g_state.pair_table_count + 1) / g_state.pair_table_capacity > LOAD_FACTOR_THRESHOLD) {
        resize_pair_table();
    }
    uint64_t key = make_pair_key(elem_a, elem_b);
    PairEntry* entry = find_pair_entry(key);
    if (entry && entry->status == PAIR_STATUS_EMPTY) {
        entry->key = key;
        entry->elem_a = elem_a < elem_b ? elem_a : elem_b;
        entry->elem_b = elem_a < elem_b ? elem_b : elem_a;
        entry->result_id = RESULT_NOTHING;
        entry->status = PAIR_STATUS_IN_FLIGHT;
        g_state.pair_table_count++;
        g_state.in_flight_count++;
    }
}

static void mark_skipped(int elem_a, int elem_b) {
    if ((double)(g_state.pair_table_count + 1) / g_state.pair_table_capacity > LOAD_FACTOR_THRESHOLD) {
        resize_pair_table();
    }
    uint64_t key = make_pair_key(elem_a, elem_b);
    PairEntry* entry = find_pair_entry(key);
    if (entry && entry->status == PAIR_STATUS_EMPTY) {
        entry->key = key;
        entry->elem_a = elem_a < elem_b ? elem_a : elem_b;
        entry->elem_b = elem_a < elem_b ? elem_b : elem_a;
        entry->result_id = RESULT_NOTHING;
        entry->status = PAIR_STATUS_SKIPPED;
        g_state.pair_table_count++;
        g_state.pruned_count++;
    }
}

static inline bool is_barren(const Element* el) {
    if (el->is_catalyst) return false;
    // 12+ trials and 0 success
    if (el->trials_count >= 12 && el->success_count == 0) return true;
    // 25+ trials and very low fertility
    if (el->trials_count >= 25 && el->fertility < g_state.min_fertility_threshold) return true;
    return false;
}

// Check if a pair is obsolete, redundant, or exceeds depth delta bounds
static bool should_prune_pair(int a, int b) {
    if (a == b) return false; // Never prune self-combinations!
    Element* ea = &g_state.elements[a];
    Element* eb = &g_state.elements[b];

    // Catalysts are universal transformers: only prune morphological duplicates
    if (ea->is_catalyst || eb->is_catalyst) {
        return is_morphological_redundant(ea->name, eb->name);
    }

    // 1. Morphological / Substring Redundancy
    if (is_morphological_redundant(ea->name, eb->name)) {
        return true;
    }

    // 2. Barren Pruning
    if (is_barren(ea) || is_barren(eb)) {
        return true;
    }

    // 3. Depth Delta Constraint:
    // Pairing elements with large depth gaps collapses back to simple nouns
    int depth_diff = abs(ea->depth - eb->depth);
    if (depth_diff > g_state.max_depth_delta) {
        return true;
    }

    // 4. Low fertility dual exhaustion
    if (ea->trials_count >= 15 && eb->trials_count >= 15) {
        if (ea->fertility < g_state.min_fertility_threshold && eb->fertility < g_state.min_fertility_threshold) {
            return true;
        }
    }

    return false;
}

// High-speed candidate batch generator with Depth-Bounded BFS & Catalyst Hub Topology
ENGINE_API int engine_get_untested_batch(int max_count, int* out_a, int* out_b, int* out_count) {
    if (!g_initialized || max_count <= 0 || !out_a || !out_b || !out_count) {
        if (out_count) *out_count = 0;
        return 0;
    }

    int found = 0;
    int total_elems = g_state.count;
    if (total_elems == 0) {
        *out_count = 0;
        return 0;
    }

    // Ensure catalysts are primed
    if (g_state.catalyst_count == 0 && total_elems > 0) {
        update_catalysts();
    }

    // =========================================================================
    // TIER 1: Self-Reflexive Evolution (X + X)
    // Yield: 60-80% discovery hit rate
    // =========================================================================
    while (g_state.self_head < g_state.self_tail && found < max_count) {
        int el_id = g_state.self_combine_ids[g_state.self_head++];
        if (engine_is_tested(el_id, el_id) == PAIR_STATUS_EMPTY) {
            out_a[found] = el_id;
            out_b[found] = el_id;
            mark_in_flight(el_id, el_id);
            found++;
        }
    }

    // =========================================================================
    // TIER 2: First Discovery Fast-Track (Novelty Entropy Focus)
    // Pairs recent First Discoveries against each other and top catalysts
    // Yield: 40-60% discovery hit rate
    // =========================================================================
    if (found < max_count && g_state.fd_head < g_state.fd_tail) {
        while (g_state.fd_head < g_state.fd_tail && found < max_count) {
            int fd_elem = g_state.first_discovery_ids[g_state.fd_head];

            // 2a. FD with other First Discoveries
            while (g_state.fd_peer_idx < g_state.fd_tail && found < max_count) {
                int peer = g_state.first_discovery_ids[g_state.fd_peer_idx++];
                if (peer == fd_elem) continue;
                if (engine_is_tested(fd_elem, peer) == PAIR_STATUS_EMPTY) {
                    if (g_state.strategy == STRATEGY_SMART_HEURISTIC && is_morphological_redundant(g_state.elements[fd_elem].name, g_state.elements[peer].name)) {
                        mark_skipped(fd_elem, peer);
                        continue;
                    }
                    out_a[found] = fd_elem;
                    out_b[found] = peer;
                    mark_in_flight(fd_elem, peer);
                    found++;
                }
            }

            // 2b. FD with top catalysts
            while (g_state.fd_catalyst_idx < g_state.catalyst_count && found < max_count) {
                int cat = g_state.catalysts[g_state.fd_catalyst_idx++];
                if (engine_is_tested(fd_elem, cat) == PAIR_STATUS_EMPTY) {
                    out_a[found] = fd_elem;
                    out_b[found] = cat;
                    mark_in_flight(fd_elem, cat);
                    found++;
                }
            }

            if (g_state.fd_peer_idx >= g_state.fd_tail && g_state.fd_catalyst_idx >= g_state.catalyst_count) {
                g_state.fd_head++;
                g_state.fd_peer_idx = 0;
                g_state.fd_catalyst_idx = 0;
            }
        }
    }

    // =========================================================================
    // TIER 3: Hub-and-Spoke Catalyst Topology (Frontier x Top Catalysts)
    // Limits branching factor to top K catalysts instead of all N elements
    // Yield: 20-35% discovery hit rate
    // =========================================================================
    if (g_state.catalyst_count > 0 && found < max_count) {
        while (g_state.catalyst_frontier_idx < g_state.frontier_tail && found < max_count) {
            int frontier_elem = g_state.frontier_ids[g_state.catalyst_frontier_idx];

            while (g_state.catalyst_list_idx < g_state.catalyst_count && found < max_count) {
                int cat_elem = g_state.catalysts[g_state.catalyst_list_idx++];
                if (engine_is_tested(frontier_elem, cat_elem) == PAIR_STATUS_EMPTY) {
                    if (g_state.strategy == STRATEGY_SMART_HEURISTIC && should_prune_pair(frontier_elem, cat_elem)) {
                        mark_skipped(frontier_elem, cat_elem);
                        continue;
                    }
                    out_a[found] = frontier_elem;
                    out_b[found] = cat_elem;
                    mark_in_flight(frontier_elem, cat_elem);
                    found++;
                }
            }

            if (g_state.catalyst_list_idx >= g_state.catalyst_count) {
                g_state.catalyst_frontier_idx++;
                g_state.catalyst_list_idx = 0;
            }
        }
    }

    // =========================================================================
    // TIER 4: Generation-Clustered Cross-Pollination (Same Epoch Elements)
    // Focus on recent discoveries within depth delta <= 1
    // Yield: 10-20% discovery hit rate
    // =========================================================================
    if (found < max_count && g_state.frontier_tail > 1) {
        int window_size = 40; // look at most recent 40 elements
        int start_idx = g_state.frontier_tail - window_size;
        if (start_idx < 0) start_idx = 0;

        for (int i = start_idx; i < g_state.frontier_tail && found < max_count; i++) {
            int fa = g_state.frontier_ids[i];
            for (int j = i + 1; j < g_state.frontier_tail && found < max_count; j++) {
                int fb = g_state.frontier_ids[j];
                if (engine_is_tested(fa, fb) == PAIR_STATUS_EMPTY) {
                    if (g_state.strategy == STRATEGY_SMART_HEURISTIC && should_prune_pair(fa, fb)) {
                        mark_skipped(fa, fb);
                        continue;
                    }
                    out_a[found] = fa;
                    out_b[found] = fb;
                    mark_in_flight(fa, fb);
                    found++;
                }
            }
        }
    }

    // =========================================================================
    // TIER 5: Depth-Bounded Frontier Exploration
    // Enforces |depth(A) - depth(B)| <= max_depth_delta and skips barren items
    // =========================================================================
    while (g_state.frontier_head < g_state.frontier_tail && found < max_count) {
        int frontier_elem = g_state.frontier_ids[g_state.frontier_head];

        while (g_state.current_frontier_partner < total_elems && found < max_count) {
            int partner = g_state.current_frontier_partner++;
            if (engine_is_tested(frontier_elem, partner) == PAIR_STATUS_EMPTY) {
                if (g_state.strategy == STRATEGY_SMART_HEURISTIC && should_prune_pair(frontier_elem, partner)) {
                    mark_skipped(frontier_elem, partner);
                    continue;
                }
                out_a[found] = frontier_elem;
                out_b[found] = partner;
                mark_in_flight(frontier_elem, partner);
                found++;
            }
        }

        if (g_state.current_frontier_partner >= total_elems) {
            g_state.frontier_head++;
            g_state.current_frontier_partner = 0;
        }
    }

    // =========================================================================
    // TIER 6: Deep Exhaustive Fallback Sweep (if higher tiers are exhausted)
    // =========================================================================
    if (found < max_count) {
        for (int i = 0; i < total_elems && found < max_count; i++) {
            Element* ea = &g_state.elements[i];
            if (g_state.strategy == STRATEGY_SMART_HEURISTIC && is_barren(ea)) {
                continue;
            }

            for (int j = i; j < total_elems && found < max_count; j++) {
                if (engine_is_tested(i, j) == PAIR_STATUS_EMPTY) {
                    if (g_state.strategy == STRATEGY_SMART_HEURISTIC && should_prune_pair(i, j)) {
                        mark_skipped(i, j);
                        continue;
                    }
                    out_a[found] = i;
                    out_b[found] = j;
                    mark_in_flight(i, j);
                    found++;
                }
            }
        }
    }

    *out_count = found;
    return found;
}

ENGINE_API void engine_get_stats(EngineStats* out_stats) {
    if (!g_initialized || !out_stats) return;

    out_stats->total_elements = g_state.count;
    out_stats->total_tested_pairs = g_state.tested_count;
    out_stats->total_in_flight_pairs = g_state.in_flight_count;
    out_stats->total_pruned_pairs = g_state.pruned_count;

    int first_disc = 0;
    float sum_fert = 0.0f;
    for (int i = 0; i < g_state.count; i++) {
        if (g_state.elements[i].is_first_discovery) {
            first_disc++;
        }
        sum_fert += g_state.elements[i].fertility;
    }
    out_stats->total_first_discoveries = first_disc;
    out_stats->avg_fertility = g_state.count > 0 ? (sum_fert / (float)g_state.count) : 0.0f;

    uint64_t n = (uint64_t)g_state.count;
    out_stats->total_possible_pairs = n * (n + 1) / 2;
    out_stats->frontier_size = g_state.frontier_tail - g_state.frontier_head;
}

#define CACHE_MAGIC 0x49435242 // "ICRB" (v2 and v3 format)
#define CACHE_VERSION 2
#define LEGACY_CACHE_MAGIC 0x49435241 // "ICRA" (v1)

typedef struct {
    int32_t a;
    int32_t b;
    int32_t res;
} CachePairRecord;

ENGINE_API bool engine_save_cache(const char* filepath) {
    if (!g_initialized || !filepath) return false;

    FILE* fp = fopen(filepath, "wb");
    if (!fp) return false;

    uint32_t magic = CACHE_MAGIC;
    uint32_t version = CACHE_VERSION;
    fwrite(&magic, sizeof(uint32_t), 1, fp);
    fwrite(&version, sizeof(uint32_t), 1, fp);

    // Write elements
    fwrite(&g_state.count, sizeof(int), 1, fp);
    for (int i = 0; i < g_state.count; i++) {
        fwrite(&g_state.elements[i], sizeof(Element), 1, fp);
    }

    // Write tested pairs using large block buffer
    int tested_pairs_to_write = g_state.tested_count;
    fwrite(&tested_pairs_to_write, sizeof(int), 1, fp);

    CachePairRecord pair_buf[16384];
    int buf_idx = 0;

    for (uint32_t i = 0; i < g_state.pair_table_capacity; i++) {
        if (g_state.pair_table[i].status == PAIR_STATUS_TESTED) {
            pair_buf[buf_idx].a = g_state.pair_table[i].elem_a;
            pair_buf[buf_idx].b = g_state.pair_table[i].elem_b;
            pair_buf[buf_idx].res = g_state.pair_table[i].result_id;
            buf_idx++;

            if (buf_idx >= 16384) {
                fwrite(pair_buf, sizeof(CachePairRecord), buf_idx, fp);
                buf_idx = 0;
            }
        }
    }
    if (buf_idx > 0) {
        fwrite(pair_buf, sizeof(CachePairRecord), buf_idx, fp);
    }

    fclose(fp);
    return true;
}

ENGINE_API bool engine_load_cache(const char* filepath) {
    if (!g_initialized || !filepath) return false;

    FILE* fp = fopen(filepath, "rb");
    if (!fp) return false;

    uint32_t magic = 0, version = 0;
    if (fread(&magic, sizeof(uint32_t), 1, fp) != 1) {
        fclose(fp);
        return false;
    }

    if (magic == LEGACY_CACHE_MAGIC) {
        if (fread(&version, sizeof(uint32_t), 1, fp) != 1) { fclose(fp); return false; }
        int elem_count = 0;
        if (fread(&elem_count, sizeof(int), 1, fp) != 1) { fclose(fp); return false; }
        for (int i = 0; i < elem_count; i++) {
            struct { int id; char name[128]; char emoji[64]; bool is_first; int depth; } v1_el;
            if (fread(&v1_el, sizeof(v1_el), 1, fp) != 1) break;
            engine_add_element(v1_el.name, v1_el.emoji, v1_el.is_first, v1_el.depth);
        }
        int pair_count = 0;
        if (fread(&pair_count, sizeof(int), 1, fp) == 1) {
            for (int i = 0; i < pair_count; i++) {
                int32_t a = 0, b = 0, res = 0;
                if (fread(&a, sizeof(int32_t), 1, fp) != 1) break;
                if (fread(&b, sizeof(int32_t), 1, fp) != 1) break;
                if (fread(&res, sizeof(int32_t), 1, fp) != 1) break;
                engine_record_result(a, b, res, false);
            }
        }
        fclose(fp);
        update_catalysts();
        return true;
    }

    if (magic != CACHE_MAGIC) {
        fclose(fp);
        return false;
    }

    if (fread(&version, sizeof(uint32_t), 1, fp) != 1 || (version != CACHE_VERSION && version != 3)) {
        fclose(fp);
        return false;
    }

    int elem_count = 0;
    if (fread(&elem_count, sizeof(int), 1, fp) != 1) {
        fclose(fp);
        return false;
    }

    if (elem_count > 0) {
        // Pre-size element array
        if (elem_count > g_state.capacity) {
            int new_elem_cap = g_state.capacity;
            while (new_elem_cap < elem_count) new_elem_cap *= 2;
            g_state.elements = (Element*)realloc(g_state.elements, new_elem_cap * sizeof(Element));
            g_state.capacity = new_elem_cap;
        }

        // Pre-size name table
        uint32_t needed_name_cap = (uint32_t)g_state.name_table_capacity;
        while ((double)elem_count / needed_name_cap > LOAD_FACTOR_THRESHOLD) {
            needed_name_cap *= 2;
        }
        if (needed_name_cap > (uint32_t)g_state.name_table_capacity) {
            free(g_state.name_table);
            g_state.name_table = (NameHashEntry*)calloc(needed_name_cap, sizeof(NameHashEntry));
            for (uint32_t i = 0; i < needed_name_cap; i++) g_state.name_table[i].elem_id = -1;
            g_state.name_table_capacity = (int)needed_name_cap;
            g_state.name_table_count = 0;
        }

        // Pre-size queues
        if (elem_count > g_state.frontier_capacity) {
            g_state.frontier_capacity = elem_count + 1024;
            g_state.frontier_ids = (int*)realloc(g_state.frontier_ids, g_state.frontier_capacity * sizeof(int));
        }
        if (elem_count > g_state.self_capacity) {
            g_state.self_capacity = elem_count + 1024;
            g_state.self_combine_ids = (int*)realloc(g_state.self_combine_ids, g_state.self_capacity * sizeof(int));
        }

        uint32_t name_mask = (uint32_t)g_state.name_table_capacity - 1;

        // Block read of all elements
        int loaded_elems = (int)fread(&g_state.elements[0], sizeof(Element), elem_count, fp);
        g_state.count = loaded_elems;

        for (int i = 0; i < loaded_elems; i++) {
            Element* el = &g_state.elements[i];
            el->id = i;
            uint64_t h = hash_string(el->name);
            uint32_t idx = (uint32_t)(h & name_mask);
            while (g_state.name_table[idx].elem_id != -1) {
                idx = (idx + 1) & name_mask;
            }
            g_state.name_table[idx].elem_id = i;
            strncpy(g_state.name_table[idx].name, el->name, MAX_NAME_LEN - 1);
            g_state.name_table[idx].name[MAX_NAME_LEN - 1] = '\0';
            g_state.name_table_count++;

            g_state.frontier_ids[g_state.frontier_tail++] = i;
            g_state.self_combine_ids[g_state.self_tail++] = i;
            if (el->is_first_discovery) {
                push_first_discovery(i);
            }
        }
    }

    int pair_count = 0;
    if (fread(&pair_count, sizeof(int), 1, fp) == 1 && pair_count > 0) {
        // Pre-grow pair table capacity to avoid collision clustering
        uint32_t needed_cap = g_state.pair_table_capacity;
        while ((double)(g_state.pair_table_count + pair_count) / needed_cap > 0.45) {
            needed_cap *= 2;
        }
        if (needed_cap > g_state.pair_table_capacity) {
            PairEntry* new_table = (PairEntry*)calloc(needed_cap, sizeof(PairEntry));
            if (new_table) {
                uint32_t mask = needed_cap - 1;
                for (uint32_t i = 0; i < g_state.pair_table_capacity; i++) {
                    if (g_state.pair_table[i].status != PAIR_STATUS_EMPTY) {
                        uint32_t idx = (uint32_t)(hash_uint64(g_state.pair_table[i].key) & mask);
                        while (new_table[idx].status != PAIR_STATUS_EMPTY) {
                            idx = (idx + 1) & mask;
                        }
                        new_table[idx] = g_state.pair_table[i];
                    }
                }
                free(g_state.pair_table);
                g_state.pair_table = new_table;
                g_state.pair_table_capacity = needed_cap;
            }
        }

        // Fast block reading and direct insertion of pairs
        CachePairRecord pair_buf[65536];
        int remaining = pair_count;
        uint32_t mask = g_state.pair_table_capacity - 1;

        while (remaining > 0) {
            int to_read = remaining < 65536 ? remaining : 65536;
            int read_now = (int)fread(pair_buf, sizeof(CachePairRecord), to_read, fp);
            if (read_now <= 0) break;

            for (int i = 0; i < read_now; i++) {
                int32_t a = pair_buf[i].a;
                int32_t b = pair_buf[i].b;
                int32_t res = pair_buf[i].res;
                uint64_t key = make_pair_key(a, b);
                uint32_t idx = (uint32_t)(hash_uint64(key) & mask);

                while (g_state.pair_table[idx].status != PAIR_STATUS_EMPTY) {
                    if (g_state.pair_table[idx].key == key) {
                        g_state.pair_table[idx].result_id = res;
                        goto next_pair;
                    }
                    idx = (idx + 1) & mask;
                }

                g_state.pair_table[idx].key = key;
                g_state.pair_table[idx].elem_a = a < b ? a : b;
                g_state.pair_table[idx].elem_b = a < b ? b : a;
                g_state.pair_table[idx].result_id = res;
                g_state.pair_table[idx].status = PAIR_STATUS_TESTED;
                g_state.pair_table_count++;
                g_state.tested_count++;

            next_pair:;
            }
            remaining -= read_now;
        }
    }

    fclose(fp);
    update_catalysts();
    return true;
}
