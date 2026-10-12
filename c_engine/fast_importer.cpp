#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <string_view>
#include <chrono>
#include <cstring>
#include <cstdint>
#include <algorithm>
#include <cctype>

#include "recipe_engine_v3.h"

#pragma pack(push, 1)
typedef struct {
    int32_t a;
    int32_t b;
    int32_t res;
} CachePair;
#pragma pack(pop)

#define CACHE_MAGIC 0x49435242 // "ICRB"
#define CACHE_VERSION 2

// FNV-1a 64-bit hash for strings (case-insensitive)
static inline uint64_t hash_str_ci(std::string_view sv) {
    uint64_t hash = 14695981039346656037ULL;
    for (char c : sv) {
        char lower = (char)std::tolower((unsigned char)c);
        hash ^= (uint64_t)(unsigned char)lower;
        hash *= 1099511628211ULL;
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

static inline bool str_case_eq(std::string_view a, const char* b) {
    size_t blen = std::strlen(b);
    if (a.size() != blen) return false;
    for (size_t i = 0; i < a.size(); ++i) {
        if (std::tolower((unsigned char)a[i]) != std::tolower((unsigned char)b[i])) {
            return false;
        }
    }
    return true;
}

static inline uint64_t make_pair_key(int32_t a, int32_t b) {
    uint32_t u = (uint32_t)(a < b ? a : b);
    uint32_t v = (uint32_t)(a < b ? b : a);
    return ((uint64_t)u << 32) | (uint64_t)v;
}

// String trimming utility
static inline std::string_view trim_sv(std::string_view s) {
    while (!s.empty() && (std::isspace((unsigned char)s.front()) || s.front() == '"' || s.front() == '\'')) {
        s.remove_prefix(1);
    }
    while (!s.empty() && (std::isspace((unsigned char)s.back()) || s.back() == '"' || s.back() == '\'')) {
        s.remove_suffix(1);
    }
    return s;
}

// Fast Open-Addressing Element Hash Table
struct ElementRegistry {
    std::vector<Element> elements;
    
    struct HashSlot {
        uint64_t hash;
        int32_t elem_id; // -1 if empty
    };

    std::vector<HashSlot> table;
    size_t table_capacity;
    size_t table_count;

    ElementRegistry(size_t initial_cap = 1048576) {
        table_capacity = 1;
        while (table_capacity < initial_cap) table_capacity *= 2;
        table.assign(table_capacity, {0, -1});
        table_count = 0;
        elements.reserve(initial_cap / 2);
    }

    void resize_table() {
        size_t new_cap = table_capacity * 2;
        std::vector<HashSlot> new_table(new_cap, {0, -1});
        uint64_t mask = new_cap - 1;

        for (size_t i = 0; i < table_capacity; ++i) {
            if (table[i].elem_id != -1) {
                uint64_t h = table[i].hash;
                size_t idx = (size_t)(h & mask);
                while (new_table[idx].elem_id != -1) {
                    idx = (idx + 1) & mask;
                }
                new_table[idx] = table[i];
            }
        }
        table = std::move(new_table);
        table_capacity = new_cap;
    }

    int32_t find_or_add(std::string_view name, std::string_view emoji = "✨", bool is_first = false, int depth = 1) {
        if (name.empty()) return -1;
        if (name.size() >= 128) {
            name = name.substr(0, 127);
        }

        uint64_t h = hash_str_ci(name);
        uint64_t mask = table_capacity - 1;
        size_t idx = (size_t)(h & mask);

        while (table[idx].elem_id != -1) {
            if (table[idx].hash == h) {
                int32_t existing_id = table[idx].elem_id;
                if (str_case_eq(name, elements[existing_id].name)) {
                    if (is_first && !elements[existing_id].is_first_discovery) {
                        elements[existing_id].is_first_discovery = 1;
                    }
                    return existing_id;
                }
            }
            idx = (idx + 1) & mask;
        }

        // Add new element
        if ((double)(table_count + 1) / table_capacity > 0.65) {
            resize_table();
            mask = table_capacity - 1;
            idx = (size_t)(h & mask);
            while (table[idx].elem_id != -1) {
                idx = (idx + 1) & mask;
            }
        }

        int32_t new_id = (int32_t)elements.size();
        Element el;
        std::memset(&el, 0, sizeof(Element));
        el.id = new_id;
        std::memcpy(el.name, name.data(), name.size());
        el.name[name.size()] = '\0';

        if (emoji.empty()) emoji = "✨";
        size_t em_len = std::min(emoji.size(), (size_t)63);
        std::memcpy(el.emoji, emoji.data(), em_len);
        el.emoji[em_len] = '\0';

        el.is_first_discovery = is_first ? 1 : 0;
        el.depth = depth;
        el.trials_count = 0;
        el.success_count = 0;
        el.fertility = 0.333f;
        el.is_catalyst = 0;

        elements.push_back(el);

        table[idx].hash = h;
        table[idx].elem_id = new_id;
        table_count++;

        return new_id;
    }

    int32_t find(std::string_view name) const {
        if (name.empty()) return -1;
        uint64_t h = hash_str_ci(name);
        uint64_t mask = table_capacity - 1;
        size_t idx = (size_t)(h & mask);

        while (table[idx].elem_id != -1) {
            if (table[idx].hash == h) {
                int32_t id = table[idx].elem_id;
                if (str_case_eq(name, elements[id].name)) {
                    return id;
                }
            }
            idx = (idx + 1) & mask;
        }
        return -1;
    }
};

// Fast Open-Addressing Pair Hash Table
struct PairRegistry {
    struct Slot {
        uint64_t key;       // 0 if empty (since pair keys can't be 0 if min element id > 0 or status used)
        int32_t elem_a;
        int32_t elem_b;
        int32_t result_id;
        uint8_t occupied;
    };

    std::vector<Slot> table;
    size_t capacity;
    size_t count;

    PairRegistry(size_t initial_cap = 2097152) {
        capacity = 1;
        while (capacity < initial_cap) capacity *= 2;
        table.assign(capacity, {0, 0, 0, -1, 0});
        count = 0;
    }

    void resize_table() {
        size_t new_cap = capacity * 2;
        std::vector<Slot> new_table(new_cap, {0, 0, 0, -1, 0});
        uint64_t mask = new_cap - 1;

        for (size_t i = 0; i < capacity; ++i) {
            if (table[i].occupied) {
                uint64_t h = hash_uint64(table[i].key);
                size_t idx = (size_t)(h & mask);
                while (new_table[idx].occupied) {
                    idx = (idx + 1) & mask;
                }
                new_table[idx] = table[i];
            }
        }
        table = std::move(new_table);
        capacity = new_cap;
    }

    bool record_pair(int32_t a, int32_t b, int32_t res) {
        if (a < 0 || b < 0 || res < -1) return false;
        if ((double)(count + 1) / capacity > 0.65) {
            resize_table();
        }

        uint64_t key = make_pair_key(a, b);
        uint64_t mask = capacity - 1;
        size_t idx = (size_t)(hash_uint64(key) & mask);

        while (table[idx].occupied) {
            if (table[idx].key == key) {
                // Already recorded, update result if previously nothing
                if (table[idx].result_id == -1 && res != -1) {
                    table[idx].result_id = res;
                }
                return false; // not a new pair
            }
            idx = (idx + 1) & mask;
        }

        table[idx].key = key;
        table[idx].elem_a = a < b ? a : b;
        table[idx].elem_b = a < b ? b : a;
        table[idx].result_id = res;
        table[idx].occupied = 1;
        count++;
        return true;
    }
};

// Binary Cache Load and Save
bool load_existing_cache(const std::string& path, ElementRegistry& el_reg, PairRegistry& pair_reg) {
    FILE* fp = std::fopen(path.c_str(), "rb");
    if (!fp) return false;

    uint32_t magic = 0, version = 0;
    if (std::fread(&magic, sizeof(uint32_t), 1, fp) != 1 || magic != CACHE_MAGIC) {
        std::fclose(fp);
        return false;
    }
    if (std::fread(&version, sizeof(uint32_t), 1, fp) != 1 || (version != CACHE_VERSION && version != 3)) {
        std::fclose(fp);
        return false;
    }

    int32_t elem_count = 0;
    if (std::fread(&elem_count, sizeof(int32_t), 1, fp) != 1 || elem_count < 0) {
        std::fclose(fp);
        return false;
    }

    std::cout << "📦 Existing cache detected: loading " << elem_count << " elements...\n";
    for (int32_t i = 0; i < elem_count; ++i) {
        Element el;
        if (std::fread(&el, sizeof(Element), 1, fp) != 1) break;
        el_reg.find_or_add(el.name, el.emoji, el.is_first_discovery != 0, el.depth);
    }

    int32_t pair_count = 0;
    if (std::fread(&pair_count, sizeof(int32_t), 1, fp) == 1 && pair_count > 0) {
        std::cout << "📦 Existing cache: loading " << pair_count << " tested pairs...\n";
        std::vector<CachePair> buf(16384);
        int32_t remaining = pair_count;
        while (remaining > 0) {
            int32_t to_read = std::min(remaining, (int32_t)16384);
            int32_t read_now = (int32_t)std::fread(buf.data(), sizeof(CachePair), to_read, fp);
            if (read_now <= 0) break;
            for (int32_t i = 0; i < read_now; ++i) {
                pair_reg.record_pair(buf[i].a, buf[i].b, buf[i].res);
            }
            remaining -= read_now;
        }
    }

    std::fclose(fp);
    std::cout << "   ✓ Loaded cache: " << el_reg.elements.size() << " elements, " << pair_reg.count << " pairs.\n";
    return true;
}

bool save_binary_cache(const std::string& path, const ElementRegistry& el_reg, const PairRegistry& pair_reg) {
    FILE* fp = std::fopen(path.c_str(), "wb");
    if (!fp) {
        std::cerr << "❌ Failed to open output cache for writing: " << path << "\n";
        return false;
    }

    uint32_t magic = CACHE_MAGIC;
    uint32_t version = CACHE_VERSION;
    std::fwrite(&magic, sizeof(uint32_t), 1, fp);
    std::fwrite(&version, sizeof(uint32_t), 1, fp);

    int32_t elem_count = (int32_t)el_reg.elements.size();
    std::fwrite(&elem_count, sizeof(int32_t), 1, fp);
    if (elem_count > 0) {
        std::fwrite(el_reg.elements.data(), sizeof(Element), elem_count, fp);
    }

    int32_t pair_count = (int32_t)pair_reg.count;
    std::fwrite(&pair_count, sizeof(int32_t), 1, fp);

    std::vector<CachePair> buf;
    buf.reserve(16384);

    for (size_t i = 0; i < pair_reg.capacity; ++i) {
        if (pair_reg.table[i].occupied) {
            buf.push_back({pair_reg.table[i].elem_a, pair_reg.table[i].elem_b, pair_reg.table[i].result_id});
            if (buf.size() >= 16384) {
                std::fwrite(buf.data(), sizeof(CachePair), buf.size(), fp);
                buf.clear();
            }
        }
    }
    if (!buf.empty()) {
        std::fwrite(buf.data(), sizeof(CachePair), buf.size(), fp);
    }

    std::fclose(fp);
    return true;
}

// Line Parser: Parses line into (first, second, result, emoji)
bool parse_recipe_line(char* line, std::string_view& out_first, std::string_view& out_second, std::string_view& out_result, std::string_view& out_emoji) {
    out_emoji = "✨";

    // 1. Check for delimiter '=' (e.g. words.csv format: A=B=C or A+B=C)
    char* eq1 = std::strchr(line, '=');
    if (eq1) {
        char* eq2 = std::strchr(eq1 + 1, '=');
        if (eq2) {
            // Format: A=B=C or A=B=C=Emoji
            *eq1 = '\0';
            *eq2 = '\0';
            out_first = trim_sv(std::string_view(line));
            out_second = trim_sv(std::string_view(eq1 + 1));

            char* eq3 = std::strchr(eq2 + 1, '=');
            if (eq3) {
                *eq3 = '\0';
                out_result = trim_sv(std::string_view(eq2 + 1));
                out_emoji = trim_sv(std::string_view(eq3 + 1));
            } else {
                out_result = trim_sv(std::string_view(eq2 + 1));
            }
            return (!out_first.empty() && !out_second.empty() && !out_result.empty());
        }

        // Format: A + B = C (or => / ->)
        char* plus = std::strchr(line, '+');
        if (plus && plus < eq1) {
            *plus = '\0';
            *eq1 = '\0';
            out_first = trim_sv(std::string_view(line));
            out_second = trim_sv(std::string_view(plus + 1));
            out_result = trim_sv(std::string_view(eq1 + 1));
            return (!out_first.empty() && !out_second.empty() && !out_result.empty());
        }
    }

    // 2. Check for arrow '->' or '=>'
    char* arrow = std::strstr(line, "->");
    if (!arrow) arrow = std::strstr(line, "=>");
    if (arrow) {
        char* plus = std::strchr(line, '+');
        if (plus && plus < arrow) {
            *plus = '\0';
            *arrow = '\0';
            out_first = trim_sv(std::string_view(line));
            out_second = trim_sv(std::string_view(plus + 1));
            out_result = trim_sv(std::string_view(arrow + 2));
            return (!out_first.empty() && !out_second.empty() && !out_result.empty());
        }
    }

    // 3. Delimited formats: comma, tab, semicolon, pipe
    char delim = 0;
    for (char d : {',', '\t', ';', '|'}) {
        if (std::strchr(line, d)) {
            delim = d;
            break;
        }
    }

    if (delim != 0) {
        char* d1 = std::strchr(line, delim);
        if (d1) {
            char* d2 = std::strchr(d1 + 1, delim);
            if (d2) {
                *d1 = '\0';
                *d2 = '\0';
                out_first = trim_sv(std::string_view(line));
                out_second = trim_sv(std::string_view(d1 + 1));
                char* d3 = std::strchr(d2 + 1, delim);
                if (d3) {
                    *d3 = '\0';
                    out_result = trim_sv(std::string_view(d2 + 1));
                    out_emoji = trim_sv(std::string_view(d3 + 1));
                } else {
                    out_result = trim_sv(std::string_view(d2 + 1));
                }
                return (!out_first.empty() && !out_second.empty() && !out_result.empty());
            }
        }
    }

    return false;
}

// Header check: returns true if line looks like CSV column header
bool is_csv_header(std::string_view a, std::string_view b, std::string_view res) {
    auto is_h = [](std::string_view s) {
        return str_case_eq(s, "first") || str_case_eq(s, "second") || str_case_eq(s, "result") ||
               str_case_eq(s, "item1") || str_case_eq(s, "item2") || str_case_eq(s, "element1") ||
               str_case_eq(s, "parent1") || str_case_eq(s, "parent2") || str_case_eq(s, "child") ||
               str_case_eq(s, "elem_a") || str_case_eq(s, "elem_b");
    };
    return is_h(a) || is_h(b) || is_h(res);
}

int main(int argc, char* argv[]) {
    // Set console UTF-8 on Windows
    #ifdef _WIN32
    system("chcp 65001 > nul");
    #endif

    if (argc < 2) {
        std::cout << "Usage: fast_importer.exe [--cache <path>] <dataset1.csv> [dataset2.tsv ...]\n";
        return 1;
    }

    std::string cache_path = "data/recipes_cache.bin";
    std::vector<std::string> input_files;

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--cache") == 0 && i + 1 < argc) {
            cache_path = argv[++i];
        } else {
            input_files.push_back(argv[i]);
        }
    }

    if (input_files.empty()) {
        std::cerr << "❌ No input recipe files specified.\n";
        return 1;
    }

    std::cout << "==================================================\n";
    std::cout << "⚡ C++ HIGH-SPEED RECIPE DATASET IMPORTER\n";
    std::cout << "   • Target Cache: " << cache_path << "\n";
    std::cout << "   • Input Files: " << input_files.size() << "\n";
    std::cout << "==================================================\n\n";

    auto t_start = std::chrono::high_resolution_clock::now();

    ElementRegistry el_reg(2097152); // Pre-reserve 2M elements
    PairRegistry pair_reg(33554432); // Pre-reserve 33M pairs for massive sets

    // Load existing cache if present
    load_existing_cache(cache_path, el_reg, pair_reg);

    size_t total_lines_all = 0;
    size_t total_imported_new = 0;

    const size_t IO_BUF_SIZE = 32 * 1024 * 1024; // 32MB read buffer
    std::vector<char> io_buffer(IO_BUF_SIZE);

    for (const auto& file_path : input_files) {
        FILE* fp = std::fopen(file_path.c_str(), "rb");
        if (!fp) {
            std::cerr << "⚠️ Could not open file: " << file_path << "\n";
            continue;
        }

        std::cout << "📖 Streaming file: " << file_path << "...\n";

        char line_buf[2048];
        size_t line_pos = 0;
        size_t file_lines = 0;
        size_t file_imported = 0;
        auto f_start = std::chrono::high_resolution_clock::now();

        size_t bytes_read = 0;
        while ((bytes_read = std::fread(io_buffer.data(), 1, IO_BUF_SIZE, fp)) > 0) {
            for (size_t i = 0; i < bytes_read; ++i) {
                char c = io_buffer[i];
                if (c == '\n' || c == '\r') {
                    if (line_pos > 0) {
                        line_buf[line_pos] = '\0';
                        file_lines++;
                        total_lines_all++;

                        if (line_buf[0] != '#') {
                            std::string_view a, b, res, emoji;
                            if (parse_recipe_line(line_buf, a, b, res, emoji)) {
                                if (file_lines > 1 || !is_csv_header(a, b, res)) {
                                    if (!str_case_eq(res, "nothing")) {
                                        int32_t id_a = el_reg.find_or_add(a);
                                        int32_t id_b = el_reg.find_or_add(b);
                                        int32_t id_res = el_reg.find_or_add(res, emoji, false, 1);

                                        if (id_a >= 0 && id_b >= 0 && id_res >= 0) {
                                            if (pair_reg.record_pair(id_a, id_b, id_res)) {
                                                file_imported++;
                                                total_imported_new++;
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        if (file_lines % 2000000 == 0) {
                            auto now = std::chrono::high_resolution_clock::now();
                            double secs = std::chrono::duration<double>(now - f_start).count();
                            double rate = secs > 0 ? (file_lines / secs) : 0;
                            std::cout << "   ⏳ " << file_lines << " lines processed | Elements: " 
                                      << el_reg.elements.size() << " | Speed: " 
                                      << (int)(rate / 1000.0) << "k lines/s\n";
                        }

                        line_pos = 0;
                    }
                } else {
                    if (line_pos < sizeof(line_buf) - 1) {
                        line_buf[line_pos++] = c;
                    }
                }
            }
        }

        std::fclose(fp);
        auto f_end = std::chrono::high_resolution_clock::now();
        double f_secs = std::chrono::duration<double>(f_end - f_start).count();
        std::cout << "   ✓ Finished " << file_path << ": " << file_lines 
                  << " lines in " << f_secs << "s (" << file_imported << " unique new pairs recorded)\n\n";
    }

    std::cout << "💾 Writing updated binary cache to: " << cache_path << "...\n";
    auto s_start = std::chrono::high_resolution_clock::now();
    if (save_binary_cache(cache_path, el_reg, pair_reg)) {
        auto s_end = std::chrono::high_resolution_clock::now();
        double s_secs = std::chrono::duration<double>(s_end - s_start).count();
        std::cout << "   ✓ Binary cache written successfully in " << s_secs << "s!\n";
    }

    auto t_end = std::chrono::high_resolution_clock::now();
    double total_secs = std::chrono::duration<double>(t_end - t_start).count();

    std::cout << "\n==================================================\n";
    std::cout << "🎉 IMPORT COMPLETE!\n";
    std::cout << "   • Total Lines Scanned: " << total_lines_all << "\n";
    std::cout << "   • Total Unique Elements: " << el_reg.elements.size() << "\n";
    std::cout << "   • Total Tested Pairs in Cache: " << pair_reg.count << "\n";
    std::cout << "   • Total Elapsed Time: " << total_secs << " seconds\n";
    std::cout << "==================================================\n";

    return 0;
}
