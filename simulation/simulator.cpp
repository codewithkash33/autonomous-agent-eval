/**
 * Autonomous Agent Simulator
 * ──────────────────────────────────────────────────────────────
 * A 2D grid-based simulation of an autonomous vehicle navigating
 * from a start position to a goal while avoiding static obstacles.
 *
 * Three decision behaviors are supported:
 *   greedy   - A* pathfinding with standard unit cost
 *   cautious - A* with heavy penalty for cells adjacent to obstacles
 *   reckless - No proper planning; naive greedy movement that ignores
 *              obstacle proximity (will collide in cluttered scenarios)
 *
 * Usage:
 *   ./simulator --id <id> --width <W> --height <H>
 *               --start-x <X> --start-y <Y>
 *               --goal-x  <X> --goal-y  <Y>
 *               --max-steps <N>
 *               --behavior  <greedy|cautious|reckless>
 *               --obstacles "x1,y1;x2,y2;..."
 *
 * Output: single JSON object on stdout; exits 0 on PASS, 1 on FAIL.
 */

#include <iostream>
#include <sstream>
#include <vector>
#include <string>
#include <queue>
#include <unordered_set>
#include <unordered_map>
#include <cmath>
#include <algorithm>
#include <iomanip>
#include <stdexcept>

// ─────────────────────────────────────────────────────────────────────────────
// Core types
// ─────────────────────────────────────────────────────────────────────────────

struct Point {
    int x = 0, y = 0;
    bool operator==(const Point& o) const { return x == o.x && y == o.y; }
    bool operator!=(const Point& o) const { return !(*this == o); }
};

struct PointHash {
    // Szudzik pairing — collision-free for non-negative coordinates
    size_t operator()(const Point& p) const {
        size_t a = static_cast<size_t>(p.x);
        size_t b = static_cast<size_t>(p.y);
        return a >= b ? a * a + a + b : a + b * b;
    }
};

enum class Behavior { GREEDY, CAUTIOUS, RECKLESS };

// ─────────────────────────────────────────────────────────────────────────────
// Grid environment
// ─────────────────────────────────────────────────────────────────────────────

class Grid {
public:
    int width;
    int height;
    std::unordered_set<Point, PointHash> obstacles;

    Grid(int w, int h) : width(w), height(h) {}

    void addObstacle(const Point& p) { obstacles.insert(p); }

    bool inBounds(const Point& p) const {
        return p.x >= 0 && p.x < width && p.y >= 0 && p.y < height;
    }

    bool isObstacle(const Point& p) const { return obstacles.count(p) > 0; }

    bool isPassable(const Point& p) const {
        return inBounds(p) && !isObstacle(p);
    }

    // True when any 8-connected neighbour is an obstacle (used by CAUTIOUS).
    bool adjacentToObstacle(const Point& p) const {
        for (int dx = -1; dx <= 1; ++dx)
            for (int dy = -1; dy <= 1; ++dy) {
                if (dx == 0 && dy == 0) continue;
                if (isObstacle({p.x + dx, p.y + dy})) return true;
            }
        return false;
    }
};

// ─────────────────────────────────────────────────────────────────────────────
// Pathfinding
// ─────────────────────────────────────────────────────────────────────────────

static const Point DIRS[4] = {{0,1},{0,-1},{1,0},{-1,0}};

static int manhattan(const Point& a, const Point& b) {
    return std::abs(a.x - b.x) + std::abs(a.y - b.y);
}

/**
 * A* search. CAUTIOUS behavior imposes a high step-cost on cells that are
 * adjacent to obstacles, naturally biasing the agent toward open corridors.
 * Returns the path [start…goal] inclusive, or empty if unreachable.
 */
static std::vector<Point> astar(const Grid& grid,
                                const Point& start,
                                const Point& goal,
                                Behavior behavior) {
    if (!grid.isPassable(start) || !grid.isPassable(goal)) return {};

    struct Node {
        Point pos;
        int   f;
        bool operator>(const Node& o) const { return f > o.f; }
    };

    std::priority_queue<Node, std::vector<Node>, std::greater<Node>> open;
    std::unordered_map<Point, Point, PointHash> came_from;
    std::unordered_map<Point, int,   PointHash> g;

    g[start] = 0;
    open.push({start, manhattan(start, goal)});

    while (!open.empty()) {
        Point cur = open.top().pos;
        open.pop();

        if (cur == goal) {
            std::vector<Point> path;
            for (Point p = goal; p != start; p = came_from[p])
                path.push_back(p);
            path.push_back(start);
            std::reverse(path.begin(), path.end());
            return path;
        }

        for (const auto& d : DIRS) {
            Point next{cur.x + d.x, cur.y + d.y};
            if (!grid.isPassable(next)) continue;

            // CAUTIOUS: penalise cells that brush up against obstacles.
            int cost = 1;
            if (behavior == Behavior::CAUTIOUS && grid.adjacentToObstacle(next))
                cost = 10;

            int ng = g[cur] + cost;
            auto it = g.find(next);
            if (it == g.end() || ng < it->second) {
                g[next] = ng;
                came_from[next] = cur;
                open.push({next, ng + manhattan(next, goal)});
            }
        }
    }
    return {};  // unreachable
}

/**
 * Reckless "plan": alternates x/y movement straight toward the goal with no
 * obstacle checking. Guaranteed to collide whenever obstacles cross the path.
 */
static std::vector<Point> planReckless(const Point& start,
                                       const Point& goal,
                                       int budget) {
    std::vector<Point> path = {start};
    Point cur = start;

    for (int step = 0; cur != goal && step < budget; ++step) {
        int dx = (goal.x > cur.x) ? 1 : (goal.x < cur.x) ? -1 : 0;
        int dy = (goal.y > cur.y) ? 1 : (goal.y < cur.y) ? -1 : 0;

        if      (dx != 0 && dy != 0) { if (step % 2 == 0) cur.x += dx; else cur.y += dy; }
        else if (dx != 0)            { cur.x += dx; }
        else if (dy != 0)            { cur.y += dy; }
        else break;

        path.push_back(cur);
    }
    return path;
}

// ─────────────────────────────────────────────────────────────────────────────
// Simulation
// ─────────────────────────────────────────────────────────────────────────────

struct SimConfig {
    std::string          scenario_id;
    int                  grid_width  = 20;
    int                  grid_height = 20;
    Point                start, goal;
    Behavior             behavior    = Behavior::GREEDY;
    int                  max_steps   = 200;
    std::vector<Point>   obstacles;
};

struct SimResult {
    std::string scenario_id;
    bool        passed        = false;
    int         steps_taken   = 0;
    int         collisions    = 0;
    bool        reached_goal  = false;
    bool        path_found    = false;
    double      efficiency    = 0.0;  // optimal_steps / steps_taken
    std::string failure_reason;
};

static SimResult runSimulation(const SimConfig& cfg) {
    SimResult res;
    res.scenario_id = cfg.scenario_id;

    // Build environment
    Grid grid(cfg.grid_width, cfg.grid_height);
    for (const auto& obs : cfg.obstacles) grid.addObstacle(obs);

    // Validate positions
    if (!grid.isPassable(cfg.start)) { res.failure_reason = "START_BLOCKED";  return res; }
    if (!grid.isPassable(cfg.goal))  { res.failure_reason = "GOAL_BLOCKED";   return res; }

    // ── Plan ─────────────────────────────────────────────────────────────────
    std::vector<Point> planned;

    if (cfg.behavior == Behavior::RECKLESS) {
        planned        = planReckless(cfg.start, cfg.goal, cfg.max_steps + 50);
        res.path_found = true;   // reckless always "has a plan"
    } else {
        planned = astar(grid, cfg.start, cfg.goal, cfg.behavior);
        if (planned.empty()) { res.failure_reason = "NO_PATH_FOUND"; return res; }
        res.path_found = true;
    }

    // Compute optimal step count using plain greedy A* as the baseline.
    int optimal_steps = 0;
    {
        auto opt   = astar(grid, cfg.start, cfg.goal, Behavior::GREEDY);
        optimal_steps = opt.empty() ? 0 : static_cast<int>(opt.size()) - 1;
    }

    // ── Execute ───────────────────────────────────────────────────────────────
    Point  agent = cfg.start;
    size_t idx   = 1;    // next position in planned path
    int    step  = 0;

    while (step < cfg.max_steps) {
        if (agent == cfg.goal) { res.reached_goal = true; break; }

        if (idx >= planned.size()) {
            res.failure_reason = "PLAN_EXHAUSTED";
            break;
        }

        Point next = planned[idx];

        if (!grid.inBounds(next)) { res.failure_reason = "OUT_OF_BOUNDS"; break; }

        if (grid.isObstacle(next)) {
            res.collisions++;
            res.failure_reason = "COLLISION";
            break;
        }

        agent = next;
        ++idx;
        ++step;
    }

    res.steps_taken = step;

    // Final goal check (covers start == goal edge-case)
    if (agent == cfg.goal) res.reached_goal = true;

    if (!res.reached_goal && res.failure_reason.empty())
        res.failure_reason = "MAX_STEPS_EXCEEDED";

    // Efficiency: 1.0 = followed optimal path exactly
    if (res.reached_goal) {
        if (optimal_steps == 0)
            res.efficiency = 1.0;
        else if (res.steps_taken > 0)
            res.efficiency = static_cast<double>(optimal_steps) / res.steps_taken;
    }

    // Pass criterion: reached goal with zero collisions
    res.passed = res.reached_goal && (res.collisions == 0);
    if (res.passed) res.failure_reason.clear();

    return res;
}

// ─────────────────────────────────────────────────────────────────────────────
// CLI argument parsing
// ─────────────────────────────────────────────────────────────────────────────

static std::string getArg(const std::vector<std::string>& args,
                           const std::string& flag,
                           const std::string& def = "") {
    for (size_t i = 0; i + 1 < args.size(); ++i)
        if (args[i] == flag) return args[i + 1];
    return def;
}

static std::vector<Point> parseObstacles(const std::string& s) {
    std::vector<Point> out;
    if (s.empty()) return out;
    std::istringstream ss(s);
    std::string token;
    while (std::getline(ss, token, ';')) {
        if (token.empty()) continue;
        std::istringstream ts(token);
        std::string xs, ys;
        if (std::getline(ts, xs, ',') && std::getline(ts, ys, ',')) {
            try { out.push_back({std::stoi(xs), std::stoi(ys)}); }
            catch (...) {}
        }
    }
    return out;
}

// ─────────────────────────────────────────────────────────────────────────────
// JSON serialisation
// ─────────────────────────────────────────────────────────────────────────────

static std::string jstr(const std::string& s) {
    std::string o = "\"";
    for (char c : s) {
        if      (c == '"')  o += "\\\"";
        else if (c == '\\') o += "\\\\";
        else if (c == '\n') o += "\\n";
        else                o += c;
    }
    return o + "\"";
}

static std::string toJson(const SimResult& r) {
    std::ostringstream o;
    o << std::fixed << std::setprecision(4);
    o << "{\n"
      << "  \"scenario_id\":    " << jstr(r.scenario_id) << ",\n"
      << "  \"passed\":         " << (r.passed        ? "true"  : "false") << ",\n"
      << "  \"steps_taken\":    " << r.steps_taken    << ",\n"
      << "  \"collisions\":     " << r.collisions     << ",\n"
      << "  \"reached_goal\":   " << (r.reached_goal  ? "true"  : "false") << ",\n"
      << "  \"path_found\":     " << (r.path_found    ? "true"  : "false") << ",\n"
      << "  \"efficiency\":     " << r.efficiency     << ",\n"
      << "  \"failure_reason\": "
      << (r.failure_reason.empty() ? "null" : jstr(r.failure_reason)) << "\n"
      << "}";
    return o.str();
}

// ─────────────────────────────────────────────────────────────────────────────
// Entry point
// ─────────────────────────────────────────────────────────────────────────────

int main(int argc, char* argv[]) {
    try {
        std::vector<std::string> args(argv + 1, argv + argc);

        SimConfig cfg;
        cfg.scenario_id  = getArg(args, "--id",       "unknown");
        cfg.grid_width   = std::stoi(getArg(args, "--width",    "20"));
        cfg.grid_height  = std::stoi(getArg(args, "--height",   "20"));
        cfg.start.x      = std::stoi(getArg(args, "--start-x",  "0"));
        cfg.start.y      = std::stoi(getArg(args, "--start-y",  "0"));
        cfg.goal.x       = std::stoi(getArg(args, "--goal-x",   "19"));
        cfg.goal.y       = std::stoi(getArg(args, "--goal-y",   "19"));
        cfg.max_steps    = std::stoi(getArg(args, "--max-steps","200"));
        cfg.obstacles    = parseObstacles(getArg(args, "--obstacles", ""));

        const std::string beh = getArg(args, "--behavior", "greedy");
        if      (beh == "cautious") cfg.behavior = Behavior::CAUTIOUS;
        else if (beh == "reckless") cfg.behavior = Behavior::RECKLESS;
        else                        cfg.behavior = Behavior::GREEDY;

        SimResult res = runSimulation(cfg);
        std::cout << toJson(res) << "\n";
        return res.passed ? 0 : 1;
    }
    catch (const std::exception& e) {
        std::cerr << "{\"error\": \"" << e.what() << "\"}\n";
        return 2;
    }
}
