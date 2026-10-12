#ifndef RECIPE_ENGINE_V3_H
#define RECIPE_ENGINE_V3_H

#include <stdint.h>
#include <stdbool.h>

#ifdef _WIN32
#define ENGINE_API __declspec(dllexport)
#else
#define ENGINE_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define MAX_NAME_LEN 128
#define MAX_EMOJI_LEN 64

// Status of a recipe pair
#define PAIR_STATUS_EMPTY     0
#define PAIR_STATUS_IN_FLIGHT 1
#define PAIR_STATUS_TESTED    2
#define PAIR_STATUS_SKIPPED   3 // Pruned as obsolete / out-of-bounds

#define RESULT_NOTHING -1

// Strategy flags
#define STRATEGY_SMART_HEURISTIC 0
#define STRATEGY_EXHAUSTIVE       1
#define STRATEGY_FIRST_DISCOVERY_FOCUS 2

typedef struct {
    int id;
    char name[MAX_NAME_LEN];
    char emoji[MAX_EMOJI_LEN];
    bool is_first_discovery;
    int depth;
    int trials_count;       // How many times this element has been combined
    int success_count;      // How many times this element yielded a NEW element
    float fertility;        // Dynamic success probability score
    bool is_catalyst;       // Top highest discovery generator
} Element;

typedef struct {
    uint64_t key;       // (min(a,b) << 32) | max(a,b)
    int32_t elem_a;
    int32_t elem_b;
    int32_t result_id;  // RESULT_NOTHING or element ID
    uint8_t status;     // PAIR_STATUS_*
} PairEntry;

typedef struct {
    int total_elements;
    int total_tested_pairs;
    int total_in_flight_pairs;
    int total_pruned_pairs;
    int total_first_discoveries;
    uint64_t total_possible_pairs;
    int frontier_size;
    float avg_fertility;
} EngineStats;

// Core Engine API
ENGINE_API bool engine_init(void);
ENGINE_API void engine_cleanup(void);
ENGINE_API void engine_reset(void);
ENGINE_API void engine_set_strategy(int strategy);
ENGINE_API void engine_set_prune_threshold(float min_fertility);
ENGINE_API void engine_set_max_depth_delta(int max_delta);
ENGINE_API void engine_set_catalyst_cap(int k);

// Element Management
ENGINE_API int engine_add_element(const char* name, const char* emoji, bool is_first_discovery, int depth);
ENGINE_API int engine_find_element(const char* name);
ENGINE_API bool engine_get_element(int id, Element* out_element);
ENGINE_API int engine_get_element_count(void);

// Recipe Pair Management
ENGINE_API bool engine_record_result(int elem_a, int elem_b, int result_id, bool is_new_element);
ENGINE_API int engine_is_tested(int elem_a, int elem_b); // returns PAIR_STATUS_*
ENGINE_API int engine_get_result(int elem_a, int elem_b); // returns result_id or -2 if untested
ENGINE_API void engine_revert_in_flight(int elem_a, int elem_b);

// Untested Recipe Batch Generation with Depth Bounded BFS & Catalyst Hub Pruning
ENGINE_API int engine_get_untested_batch(int max_count, int* out_a, int* out_b, int* out_count);

// Persistence
ENGINE_API bool engine_save_cache(const char* filepath);
ENGINE_API bool engine_load_cache(const char* filepath);

// Statistics
ENGINE_API void engine_get_stats(EngineStats* out_stats);

#ifdef __cplusplus
}
#endif

#endif // RECIPE_ENGINE_V3_H
