import pulp
import time

from sample_data import exercises, muscles, days, DayParams, MuscleParams, ExerciseParams

print("training_milp_v1.py started")

# =============================================================================
# DAY TEMPLATES - one per goal
# =============================================================================
# Each template defines which exercise slots are allowed on which day.
# The LP is forced to zero for any (exercise, day) pair not in the allowed list.
# Templates are designed so truncation to fewer days still makes training sense:
#   6 days → use as-is
#   4 days → use Day1-Day4 (still balanced)
#   3 days → use Day1-Day3 (still hits every pattern)
# Template getters return None for very long sessions (>90 min), triggering
# the free-LP path with select_candidate_exercises instead.
# =============================================================================

# STRENGTH - alternating push-dominant / pull-dominant days (unchanged)
STRENGTH_ALLOWED_SLOTS_BY_DAY = {
    "Day1": ["squat_main",  "horizontal_push_main", "vertical_pull_main"],
    "Day2": ["hinge_main",  "horizontal_pull_main", "vertical_push_main"],
    "Day3": ["squat_main",  "horizontal_push_main", "vertical_pull_main"],
    "Day4": ["hinge_main",  "horizontal_pull_main", "vertical_push_main"],
    "Day5": ["squat_main",  "horizontal_push_main", "vertical_pull_main"],
    "Day6": ["hinge_main",  "horizontal_pull_main", "vertical_push_main"],
}

# HYPERTROPHY - PPL (Push/Pull/Legs) split
# Day1/4 = Legs, Day2/5 = Push, Day3/6 = Pull
# Truncated to 3 days → one of each; to 4 days → Legs, Push, Pull, Legs
HYPERTROPHY_ALLOWED_SLOTS_BY_DAY = {
    "Day1": ["squat_main", "hinge_main", "leg_iso_main"],
    "Day2": ["horizontal_push_main", "vertical_push_main", "shoulder_iso_main"],
    "Day3": ["horizontal_pull_main", "vertical_pull_main"],
    "Day4": ["squat_main", "hinge_main", "leg_iso_main"],
    "Day5": ["horizontal_push_main", "vertical_push_main", "shoulder_iso_main"],
    "Day6": ["horizontal_pull_main", "vertical_pull_main"],
}

# ATHLETIC PERFORMANCE - posterior chain focus, pulling emphasis
# Hinge days are for RDL + rowing; squat days add vertical push/pull for athleticism
ATHLETIC_ALLOWED_SLOTS_BY_DAY = {
    "Day1": ["squat_main", "vertical_pull_main", "vertical_push_main"],
    "Day2": ["hinge_main", "horizontal_pull_main"],
    "Day3": ["squat_main", "vertical_pull_main"],
    "Day4": ["hinge_main", "horizontal_pull_main", "vertical_push_main"],
    "Day5": ["squat_main", "vertical_pull_main"],
    "Day6": ["hinge_main", "horizontal_pull_main"],
}

# FAT LOSS - full-body compound movements, high frequency
# Squats and hinges appear frequently; push/pull balanced each session
FAT_LOSS_ALLOWED_SLOTS_BY_DAY = {
    "Day1": ["squat_main", "horizontal_push_main", "horizontal_pull_main"],
    "Day2": ["hinge_main", "horizontal_pull_main"],
    "Day3": ["squat_main", "horizontal_push_main"],
    "Day4": ["hinge_main", "squat_main"],
    "Day5": ["squat_main", "horizontal_push_main", "horizontal_pull_main"],
    "Day6": ["hinge_main", "horizontal_pull_main"],
}

# MAINTENANCE - all six compound patterns, lower volume
# Full-body A/B structure: Day1/3/5 hit push-dominant, Day2/4/6 pull-dominant
MAINTENANCE_ALLOWED_SLOTS_BY_DAY = {
    "Day1": ["squat_main", "horizontal_push_main", "horizontal_pull_main"],
    "Day2": ["hinge_main", "vertical_push_main", "vertical_pull_main"],
    "Day3": ["squat_main", "horizontal_push_main"],
    "Day4": ["hinge_main", "horizontal_pull_main"],
    "Day5": ["squat_main", "horizontal_push_main", "horizontal_pull_main"],
    "Day6": ["hinge_main", "vertical_pull_main"],
}


# =============================================================================
# MOVEMENT FAMILY TAXONOMY
# =============================================================================

MOVEMENT_FAMILY_KEYWORDS = {
    "squat":              ["squat", "leg press", "lunge", "split squat", "step up", "step-up", "hack squat"],
    "hinge":              ["deadlift", "rdl", "romanian", "hip thrust", "glute bridge", "good morning", "hip extension"],
    "horizontal_push":    ["bench press", "floor press", "push up", "push-up", "chest press", "dumbbell press"],
    "vertical_push":      ["overhead press", "shoulder press", "military press", "arnold press", "pike press"],
    "horizontal_pull":    ["row", "seal row", "chest supported", "inverted row", "face pull"],
    "vertical_pull":      ["pull up", "pull-up", "chin up", "chin-up", "lat pulldown"],
    "shoulder_isolation": ["lateral raise", "front raise", "rear delt"],
    "leg_isolation":      ["leg curl", "leg extension", "leg raise", "calf raise"],
}

REQUIRED_FAMILIES_BY_GOAL = {
    "strength":             ["squat", "hinge", "horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull"],
    "hypertrophy":          ["squat", "hinge", "horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull",
                             "shoulder_isolation", "leg_isolation"],
    "athletic_performance": ["squat", "hinge", "vertical_pull", "horizontal_pull", "vertical_push"],
    "fat_loss":             ["squat", "hinge", "horizontal_push", "horizontal_pull"],
    "maintenance":          ["squat", "hinge", "horizontal_push", "horizontal_pull", "vertical_push", "vertical_pull"],
}

MAX_PER_FAMILY_BY_GOAL = {
    "strength":             {"default": 2},
    "hypertrophy":          {"default": 3, "shoulder_isolation": 2, "leg_isolation": 2},
    "athletic_performance": {"default": 2},
    "fat_loss":             {"default": 2},
    "maintenance":          {"default": 2},
}

BASE_MUSCLE_PARAMS = {
    "quadriceps": MuscleParams(v_min=4, v_target=6,  v_max=10),
    "hamstrings":  MuscleParams(v_min=4, v_target=6,  v_max=10),
    "glutes":      MuscleParams(v_min=4, v_target=6,  v_max=10),
    "chest":       MuscleParams(v_min=4, v_target=6,  v_max=10),
    "back":        MuscleParams(v_min=4, v_target=6,  v_max=10),
    "shoulders":   MuscleParams(v_min=3, v_target=5,  v_max=8),
}


# =============================================================================
# DYNAMIC LP PARAMETER CALCULATION
# =============================================================================

def compute_recovery_budget(days_available, session_minutes, goal):
    days_factor = days_available / 3.0
    time_factor  = session_minutes / 60.0
    base         = 30.0
    goal_multiplier = {
        "strength":             1.00,
        "hypertrophy":          0.95,
        "athletic_performance": 0.85,
        "fat_loss":             0.80,
        "maintenance":          0.70,
    }.get(goal, 0.85)
    return round(base * days_factor * time_factor * goal_multiplier, 1)


def compute_lp_params(days_available, session_minutes, goal):
    time_factor = session_minutes / 60.0
    days_factor = days_available  / 3.0
    weekly_time_factor = (days_available * session_minutes) / (3.0 * 60.0)

    if goal == "strength":
        max_sets_per_day     = min(30, max(10, int(round(14 * time_factor))))
        per_exercise_day_cap = 5 if session_minutes <= 75 else 6
        weekly_exercise_cap  = min(24, max(6, int(round(6 * min(weekly_time_factor, 4.0)))))
        return {"max_sets_per_day": max_sets_per_day,
                "per_exercise_day_cap": per_exercise_day_cap,
                "weekly_exercise_cap": weekly_exercise_cap}

    base_weekly_cap = {
        "hypertrophy":          8,
        "athletic_performance": 7,
        "fat_loss":             6,
        "maintenance":          5,
    }.get(goal, 6)

    max_sets_per_day     = min(30, max(8, int(15 * time_factor)))
    per_exercise_day_cap = 6
    weekly_exercise_cap  = min(24, max(4, int(base_weekly_cap * days_factor)))

    return {"max_sets_per_day": max_sets_per_day,
            "per_exercise_day_cap": per_exercise_day_cap,
            "weekly_exercise_cap": weekly_exercise_cap}


def compute_min_weekly_sets_for_goal(goal, days_available, session_minutes, exercise_keys):
    """
    Per-exercise minimum weekly set floors for ALL goals, scaled by training volume.

    Base values are calibrated at 3 days / 60 min.  weekly_minutes_factor scales
    them proportionally so a 6-day / 120-min programme gets ~2× the base minimums.
    Hypertrophy gets higher bases than strength because volume is the primary driver.
    Athletic performance emphasises hinge and pulling.  Fat loss and maintenance
    use modest bases that keep volume manageable.
    """
    weekly_minutes_factor = (days_available * session_minutes) / (3.0 * 60.0)
    set_scale = max(0.75, min(2.0, weekly_minutes_factor ** 0.5))

    base_by_goal = {
        "strength": {
            "squat_main": 4, "hinge_main": 3,
            "horizontal_push_main": 4, "horizontal_pull_main": 3,
            "vertical_push_main": 2, "vertical_pull_main": 2,
        },
        "hypertrophy": {
            "squat_main": 4, "hinge_main": 4,
            "horizontal_push_main": 4, "vertical_push_main": 3,
            "horizontal_pull_main": 4, "vertical_pull_main": 3,
            "shoulder_iso_main": 3, "leg_iso_main": 3,
        },
        "athletic_performance": {
            "squat_main": 3, "hinge_main": 4,       # hinge bias for athleticism
            "vertical_pull_main": 4, "horizontal_pull_main": 3,
            "vertical_push_main": 2,
        },
        "fat_loss": {
            "squat_main": 3, "hinge_main": 3,
            "horizontal_push_main": 3, "horizontal_pull_main": 3,
        },
        "maintenance": {
            "squat_main": 2, "hinge_main": 2,
            "horizontal_push_main": 2, "horizontal_pull_main": 2,
            "vertical_push_main": 1, "vertical_pull_main": 2,
        },
    }

    base = base_by_goal.get(goal)
    if not base:
        return None

    mins = {k: max(1, round(v * set_scale)) for k, v in base.items() if k in exercise_keys}

    if weekly_minutes_factor <= 0.5:
        mins = {k: min(v, 1) for k, v in mins.items()}
    elif weekly_minutes_factor <= 0.75:
        mins = {k: min(v, 2) for k, v in mins.items()}

    return mins


# =============================================================================
# MOVEMENT FAMILY CLASSIFICATION
# =============================================================================

def get_movement_family(name):
    n = name.lower()
    for family, keywords in MOVEMENT_FAMILY_KEYWORDS.items():
        if any(kw in n for kw in keywords):
            return family
    return None


# =============================================================================
# EXERCISE QUALITY SCORING
# =============================================================================

def score_exercise_for_goal(name, goal):
    n = name.lower()
    score = 0.0

    canonical_patterns = {
        "strength": [
            ("barbell back squat", 12), ("back squat", 11), ("barbell squat", 10), ("front squat", 8), ("squat", 6),
            ("barbell deadlift", 12), ("deadlift", 11), ("romanian deadlift", 10), ("rdl", 10),
            ("barbell bench press", 12), ("bench press", 11), ("incline bench press", 8), ("floor press", 7),
            ("barbell overhead press", 11), ("overhead press", 10), ("military press", 10), ("shoulder press", 8),
            ("barbell row", 11), ("bent-over row", 10), ("pendlay row", 10), ("row", 7),
            ("pull up", 10), ("pull-up", 10), ("chin up", 10), ("chin-up", 10), ("lat pulldown", 8), ("pulldown", 7),
        ],
        "hypertrophy": [
            # Quads / lower body - leg press and hack squat are valued for hypertrophy
            ("squat", 8), ("leg press", 7), ("hack squat", 6), ("lunge", 5), ("split squat", 6),
            # Hamstrings / glutes - RDL preferred over heavy deadlift for time-under-tension
            ("romanian deadlift", 9), ("rdl", 9), ("hip thrust", 8), ("leg curl", 6),
            # Chest - dumbbell press valued alongside barbell
            ("bench press", 8), ("incline bench", 7), ("incline press", 7), ("dumbbell press", 6),
            # Back - lat pulldown and pull-up equally valued
            ("row", 8), ("lat pulldown", 8), ("pull up", 7), ("chin up", 7),
            # Shoulders - OHP + isolation
            ("overhead press", 7), ("lateral raise", 7), ("front raise", 5),
            # Isolation
            ("leg extension", 6), ("leg curl", 6), ("calf raise", 4),
        ],
        "athletic_performance": [
            # Posterior chain is the primary driver of athletic performance
            ("romanian deadlift", 11), ("rdl", 11), ("hip thrust", 9), ("glute bridge", 7), ("deadlift", 9),
            # Knee-dominant lower body - front squat preferred for athletes
            ("front squat", 10), ("squat", 8), ("split squat", 7), ("lunge", 7),
            # Pulling strength - vital for athletes
            ("pull up", 9), ("pull-up", 9), ("chin up", 9), ("row", 8), ("lat pulldown", 7),
            # Upper push - lower priority; OHP preferred over bench for athletes
            ("overhead press", 6), ("shoulder press", 5),
        ],
        "fat_loss": [
            # Full-body compounds that maximise metabolic demand per set
            ("squat", 8), ("deadlift", 8), ("romanian deadlift", 7), ("hip thrust", 7),
            ("lunge", 6), ("split squat", 6),
            ("row", 7), ("lat pulldown", 6), ("pull up", 6),
            ("bench press", 6), ("overhead press", 5),
        ],
        "maintenance": [
            # Minimal effective volume - classic compound lifts only
            ("squat", 7), ("deadlift", 7), ("row", 6), ("bench press", 6),
            ("overhead press", 5), ("lunge", 5), ("lat pulldown", 5), ("pull up", 5),
        ],
    }

    patterns = canonical_patterns.get(goal, canonical_patterns["maintenance"])
    for pattern, base_score in patterns:
        if pattern in n:
            score += base_score
            break

    variant_penalties = [
        ("with chains", -7), ("with band", -7), ("with bands", -7),
        ("kneeling", -5), ("zercher", -6), ("clean grip", -5),
        ("one leg", -6), ("one-leg", -6), ("single leg", -5),
        ("one arm", -5), ("one-arm", -5), ("alternating", -4),
        ("behind the neck", -7), ("guillotine", -7),
        ("decline", -3), ("reverse", -4),
        ("wide grip", -3), ("wide-grip", -3), ("close grip", -3), ("close-grip", -3),
        ("narrow stance", -4), ("wide stance", -3),
        ("cambered", -5), ("long bar", -4), ("snatch grip", -5),
        ("full range-of-motion", -4), ("full range of motion", -4), ("scapular", -6),
    ]
    for keyword, penalty in variant_penalties:
        if keyword in n:
            score += penalty

    return score


# =============================================================================
# PRE-SELECTION LAYER (used as fallback for large-session / non-templated paths)
# =============================================================================

def select_candidate_exercises(all_exercises, all_bonuses, goal, max_per_family=None):
    family_caps     = MAX_PER_FAMILY_BY_GOAL.get(goal, {"default": 2})
    target_families = REQUIRED_FAMILIES_BY_GOAL.get(goal, list(MOVEMENT_FAMILY_KEYWORDS.keys()))

    by_family = {}
    for key, ex in all_exercises.items():
        family = get_movement_family(ex.name)
        if family:
            by_family.setdefault(family, []).append((key, ex))

    selected, selected_bonuses = {}, {}
    for family in target_families:
        candidates = by_family.get(family, [])
        if not candidates:
            print(f"  [WARNING] No exercises for family '{family}' (goal={goal})")
            continue
        cap    = max_per_family if max_per_family is not None else family_caps.get(family, family_caps["default"])
        scored = sorted(candidates, key=lambda item: score_exercise_for_goal(item[1].name, goal), reverse=True)
        for key, ex in scored[:cap]:
            selected[key]         = ex
            selected_bonuses[key] = all_bonuses.get(key, 0.0)

    print(f"\nPre-selection: {len(all_exercises)} → {len(selected)} exercises")
    print(f"  {'Family':<22} {'Exercise':<48} {'Score':>6}")
    print(f"  {'-'*78}")
    for key, ex in selected.items():
        fam   = get_movement_family(ex.name) or "unclassified"
        score = score_exercise_for_goal(ex.name, goal)
        print(f"  {fam:<22} {ex.name:<48} {score:>6.1f}")
    print()

    return selected, selected_bonuses


# =============================================================================
# SLOT SELECTION - shared utilities
# =============================================================================

def _build_family_map(all_exercises):
    """Group all exercises by movement family."""
    families = {f: [] for f in MOVEMENT_FAMILY_KEYWORDS}
    for key, ex in all_exercises.items():
        family = get_movement_family(ex.name)
        if family in families:
            families[family].append((key, ex))
    return families


def pick_best_by_names(candidates, preferred_names):
    """
    Return (key, ExerciseParams) whose name best matches preferred_names.
    Exact match beats partial; earlier in the list beats later.
    """
    if not candidates:
        return None

    blocked_modifiers = [
        "decline", "close", "wide", "medium", "one arm", "one-arm",
        "alternating", "scapular", "guillotine", "rear delt",
    ]

    normalized = [(key, ex, ex.name.lower().strip()) for key, ex in candidates]

    # 1. Exact match
    for pref in preferred_names:
        p = pref.lower().strip()
        for key, ex, n in normalized:
            if n == p:
                return key, ex

    # 2. Starts/ends with preferred name and no blocked modifier
    for pref in preferred_names:
        p = pref.lower().strip()
        for key, ex, n in normalized:
            if any(b in n for b in blocked_modifiers):
                continue
            if n.startswith(p) or n.endswith(p):
                return key, ex

    return None


def pick_backup_exercise(candidates, goal, blocked_words=None):
    """Score-based fallback when no canonical name match is found."""
    if not candidates:
        return None
    filtered = [(key, ex) for key, ex in candidates
                if not blocked_words or not any(b in ex.name.lower() for b in blocked_words)]
    if not filtered:
        filtered = candidates
    scored = sorted(filtered, key=lambda item: score_exercise_for_goal(item[1].name, goal), reverse=True)
    return scored[0]


def _resolve_slots(preferred_by_slot, goal, bonus_value=1.5):
    result, bonuses = {}, {}
    for slot, spec in preferred_by_slot.items():
        candidates, names = spec[0], spec[1]
        blocked = spec[2] if len(spec) > 2 else None

        picked = pick_best_by_names(candidates, names)
        if not picked:
            picked = pick_backup_exercise(candidates, goal=goal, blocked_words=blocked)
        if picked:
            key, ex = picked
            result[slot]  = ex
            bonuses[slot] = bonus_value

    return result, bonuses


# =============================================================================
# STRENGTH SLOT SELECTION (unchanged)
# =============================================================================


def pick_best_strength_exercise_by_names(candidates, preferred_names):
    if not candidates:
        return None
    blocked_modifiers = [
        "decline", "incline", "close", "wide", "medium", "one arm", "one-arm",
        "alternating", "scapular", "guillotine", "floor", "rear delt",
    ]
    normalized = [(key, ex, ex.name.lower().strip()) for key, ex in candidates]
    for pref in preferred_names:
        p = pref.lower().strip()
        for key, ex, n in normalized:
            if n == p:
                return key, ex
    for pref in preferred_names:
        p = pref.lower().strip()
        for key, ex, n in normalized:
            if any(b in n for b in blocked_modifiers):
                continue
            if n.startswith(p) or n.endswith(p):
                return key, ex
    return None


def pick_backup_strength_exercise(candidates, slot=None, goal="strength"):
    if not candidates:
        return None
    blocked_by_slot = {
        "vertical_pull_main":   ["straight-arm", "straight arm", "scapular", "underhand", "supinated", "one arm", "one-arm", "single arm", "single-arm"],
        "horizontal_push_main": ["decline", "floor", "close grip", "close-grip", "wide grip", "wide-grip"],
        "vertical_push_main":   ["alternating"],
        "horizontal_pull_main": ["face pull", "rear delt", "scapular"],
    }
    filtered = [(key, ex) for key, ex in candidates
                if not any(b in ex.name.lower() for b in blocked_by_slot.get(slot, []))]
    if not filtered:
        return None
    scored = sorted(filtered, key=lambda item: score_exercise_for_goal(item[1].name, goal), reverse=True)
    return scored[0]


def select_strength_slots(all_exercises):
    families = _build_family_map(all_exercises)

    print("\nStrength family candidates:")
    for family in ["squat", "hinge", "horizontal_push", "horizontal_pull", "vertical_push", "vertical_pull"]:
        print(f"  {family} ({len(families[family])}):")
        for _, ex in families[family]:
            print(f"    - {ex.name}")

    preferred_by_slot = {
        "squat_main":           (families["squat"],           ["Barbell Back Squat", "Back Squat", "Barbell Squat", "Squat", "Front Squat"]),
        "hinge_main":           (families["hinge"],           ["Barbell Deadlift", "Deadlift", "Romanian Deadlift", "RDL"]),
        "horizontal_push_main": (families["horizontal_push"], ["Barbell Bench Press", "Bench Press"]),
        "horizontal_pull_main": (families["horizontal_pull"], ["Barbell Row", "Bent-Over Row", "Pendlay Row", "Row"]),
        "vertical_push_main":   (families["vertical_push"],   ["Barbell Overhead Press", "Overhead Press", "Shoulder Press"]),
        "vertical_pull_main":   (families["vertical_pull"],   ["Pull Up", "Chin Up", "Pull-Up", "Chin-Up", "Lat Pulldown"]),
    }

    result, bonuses = {}, {}
    for slot, (candidates, names) in preferred_by_slot.items():
        picked = pick_best_strength_exercise_by_names(candidates, names)
        if not picked:
            picked = pick_backup_strength_exercise(candidates, slot=slot, goal="strength")
        if picked:
            key, ex = picked
            result[slot]  = ex
            bonuses[slot] = 2.0

    print("\nSelected strength slots:")
    for slot in ["squat_main", "hinge_main", "horizontal_push_main", "horizontal_pull_main", "vertical_push_main", "vertical_pull_main"]:
        print(f"  {slot:<30} -> {result.get(slot, type('', (), {'name': 'MISSING'})()).name}")

    return result, bonuses


# =============================================================================
# HYPERTROPHY SLOT SELECTION
# =============================================================================
# Hypertrophy differs from strength in two key ways:
#   1. Hinge slot prefers RDL / hip thrust over heavy deadlift (more TUT, less CNS load)
#   2. Two isolation slots are added: shoulder_iso_main and leg_iso_main
#
# The PPL template means these slots naturally appear on the right days:
#   Legs days  → squat_main, hinge_main, leg_iso_main
#   Push days  → horizontal_push_main, vertical_push_main, shoulder_iso_main
#   Pull days  → horizontal_pull_main, vertical_pull_main

def select_hypertrophy_slots(all_exercises):
    families = _build_family_map(all_exercises)

    preferred_by_slot = {
        # Squat family - leg press is a valid hypertrophy squat substitute
        "squat_main":           (families["squat"],
                                 ["Barbell Squat", "Squat", "Barbell Back Squat", "Leg Press", "Hack Squat"],
                                 ["one leg", "one-leg", "single leg", "pistol"]),
        # Hinge family - RDL first, hip thrust second, deadlift as last resort
        "hinge_main":           (families["hinge"],
                                 ["Romanian Deadlift", "RDL", "Barbell Romanian Deadlift",
                                  "Hip Thrust", "Barbell Hip Thrust", "Deadlift"],
                                 ["one leg", "one-leg", "stiff-legged", "stiff leg"]),
        # Horizontal push - bench press; incline accepted for hypertrophy
        "horizontal_push_main": (families["horizontal_push"],
                                 ["Barbell Bench Press", "Bench Press", "Dumbbell Bench Press",
                                  "Incline Bench Press", "Incline Dumbbell Press"],
                                 ["decline", "close grip", "wide grip", "guillotine"]),
        # Vertical push - OHP; dumbbell shoulder press also good for hypertrophy
        "vertical_push_main":   (families["vertical_push"],
                                 ["Barbell Overhead Press", "Overhead Press",
                                  "Dumbbell Shoulder Press", "Shoulder Press"],
                                 ["alternating", "behind the neck"]),
        # Horizontal pull - row; dumbbell row is fine for hypertrophy
        "horizontal_pull_main": (families["horizontal_pull"],
                                 ["Barbell Row", "Bent-Over Row", "Dumbbell Row",
                                  "Pendlay Row", "Cable Row", "Row"],
                                 ["face pull", "scapular"]),
        # Vertical pull - lat pulldown preferred (easier to load progressively for hypertrophy)
        "vertical_pull_main":   (families["vertical_pull"],
                                 ["Lat Pulldown", "Cable Lat Pulldown", "Pull Up",
                                  "Chin Up", "Pull-Up"],
                                 ["straight-arm", "straight arm", "scapular"]),
        # Shoulder isolation - lateral raise (targets lateral deltoid for width)
        "shoulder_iso_main":    (families["shoulder_isolation"],
                                 ["Dumbbell Lateral Raise", "Lateral Raise",
                                  "Cable Lateral Raise", "Side Lateral Raise"],
                                 []),
        # Leg isolation - leg curl for hamstrings (complements squat-dominant leg days)
        "leg_iso_main":         (families["leg_isolation"],
                                 ["Leg Curl", "Lying Leg Curl", "Seated Leg Curl",
                                  "Hamstring Curl", "Leg Extension"],
                                 []),
    }

    result, bonuses = _resolve_slots(preferred_by_slot, goal="hypertrophy", bonus_value=1.5)

    print("\nSelected hypertrophy slots:")
    for slot in ["squat_main", "hinge_main", "horizontal_push_main", "vertical_push_main",
                 "horizontal_pull_main", "vertical_pull_main", "shoulder_iso_main", "leg_iso_main"]:
        ex = result.get(slot)
        print(f"  {slot:<30} -> {ex.name if ex else 'MISSING'}")

    return result, bonuses


# =============================================================================
# ATHLETIC PERFORMANCE SLOT SELECTION
# =============================================================================
# Athletic performance emphasises the posterior chain (RDL >> deadlift),
# pulling strength (pull ups over lat pulldown), and knee-dominant lower body
# (front squat preferred for quad/glute balance).  Horizontal push is excluded
# from the template - bench press is a low priority for athletes.

def select_athletic_slots(all_exercises):
    families = _build_family_map(all_exercises)

    preferred_by_slot = {
        # Squat - front squat preferred for athletic quad/glute development
        "squat_main":          (families["squat"],
                                ["Front Squat", "Barbell Front Squat",
                                 "Barbell Squat", "Squat", "Split Squat"],
                                ["one leg", "one-leg", "hack"]),
        # Hinge - RDL strongly preferred; hip thrust second; deadlift acceptable
        "hinge_main":          (families["hinge"],
                                ["Romanian Deadlift", "RDL", "Barbell Romanian Deadlift",
                                 "Hip Thrust", "Barbell Hip Thrust", "Deadlift"],
                                ["stiff-legged", "stiff leg", "one leg"]),
        # Vertical pull - pull ups over machines for athletic performance
        "vertical_pull_main":  (families["vertical_pull"],
                                ["Pull Up", "Pull-Up", "Chin Up", "Chin-Up",
                                 "Weighted Pull Up", "Lat Pulldown"],
                                ["straight-arm", "straight arm", "scapular", "one arm"]),
        # Horizontal pull - barbell / dumbbell row for back thickness + trunk strength
        "horizontal_pull_main":(families["horizontal_pull"],
                                ["Barbell Row", "Bent-Over Row", "Pendlay Row",
                                 "Dumbbell Row", "Row"],
                                ["face pull", "scapular", "rear delt"]),
        # Vertical push - OHP for overhead strength; important for athletic performance
        "vertical_push_main":  (families["vertical_push"],
                                ["Barbell Overhead Press", "Overhead Press",
                                 "Shoulder Press", "Military Press"],
                                ["alternating", "behind the neck", "seated"]),
    }

    result, bonuses = _resolve_slots(preferred_by_slot, goal="athletic_performance", bonus_value=1.5)

    print("\nSelected athletic performance slots:")
    for slot in ["squat_main", "hinge_main", "vertical_pull_main", "horizontal_pull_main", "vertical_push_main"]:
        ex = result.get(slot)
        print(f"  {slot:<30} -> {ex.name if ex else 'MISSING'}")

    return result, bonuses


# =============================================================================
# FAT LOSS SLOT SELECTION
# =============================================================================
# Fat loss prioritises full-body compound movements that maximise metabolic
# demand.  Squats, hinges, rows and presses appear frequently (high-frequency
# template).  No isolation work - every set needs to carry its metabolic weight.
# Goblet squats and lunges are acceptable squat substitutes (lower load but
# good for keeping density high).

def select_fat_loss_slots(all_exercises):
    families = _build_family_map(all_exercises)

    preferred_by_slot = {
        # Squat - back squat preferred; goblet squat / lunge acceptable
        "squat_main":           (families["squat"],
                                 ["Barbell Squat", "Squat", "Barbell Back Squat",
                                  "Goblet Squat", "Lunge", "Split Squat"],
                                 ["one leg", "one-leg", "hack"]),
        # Hinge - RDL preferred for metabolic demand + posterior chain
        "hinge_main":           (families["hinge"],
                                 ["Romanian Deadlift", "RDL", "Deadlift",
                                  "Hip Thrust", "Barbell Hip Thrust"],
                                 ["stiff-legged", "one leg"]),
        # Horizontal push - bench press or push up (high rep accessible)
        "horizontal_push_main": (families["horizontal_push"],
                                 ["Barbell Bench Press", "Bench Press",
                                  "Push Up", "Push-Up", "Dumbbell Bench Press"],
                                 ["decline", "close grip", "guillotine"]),
        # Horizontal pull - row (high metabolic demand, back + biceps)
        "horizontal_pull_main": (families["horizontal_pull"],
                                 ["Barbell Row", "Bent-Over Row",
                                  "Dumbbell Row", "Row"],
                                 ["face pull", "scapular"]),
    }

    result, bonuses = _resolve_slots(preferred_by_slot, goal="fat_loss", bonus_value=1.5)

    print("\nSelected fat loss slots:")
    for slot in ["squat_main", "hinge_main", "horizontal_push_main", "horizontal_pull_main"]:
        ex = result.get(slot)
        print(f"  {slot:<30} -> {ex.name if ex else 'MISSING'}")

    return result, bonuses


# =========================================================================================
# MAINTENANCE SLOT SELECTION
# =========================================================================================
# Maintenance covers all six compound movement patterns at low volume.
# The goal is to preserve strength and muscle with minimal fatigue.
# Classic heavy basics are preferred.

def select_maintenance_slots(all_exercises):
    families = _build_family_map(all_exercises)

    preferred_by_slot = {
        "squat_main":           (families["squat"],
                                 ["Barbell Squat", "Barbell Back Squat", "Squat",
                                  "Back Squat", "Front Squat"],
                                 ["one leg", "one-leg", "hack"]),
        "hinge_main":           (families["hinge"],
                                 ["Deadlift", "Barbell Deadlift",
                                  "Romanian Deadlift", "RDL"],
                                 ["one leg", "stiff-legged"]),
        "horizontal_push_main": (families["horizontal_push"],
                                 ["Barbell Bench Press", "Bench Press"],
                                 ["decline", "close grip", "guillotine"]),
        "horizontal_pull_main": (families["horizontal_pull"],
                                 ["Barbell Row", "Bent-Over Row", "Pendlay Row", "Row"],
                                 ["face pull", "scapular"]),
        "vertical_push_main":   (families["vertical_push"],
                                 ["Barbell Overhead Press", "Overhead Press",
                                  "Shoulder Press", "Military Press"],
                                 ["alternating", "behind the neck"]),
        "vertical_pull_main":   (families["vertical_pull"],
                                 ["Pull Up", "Chin Up", "Pull-Up", "Lat Pulldown"],
                                 ["straight-arm", "scapular", "one arm"]),
    }

    result, bonuses = _resolve_slots(preferred_by_slot, goal="maintenance", bonus_value=1.5)

    print("\nSelected maintenance slots:")
    for slot in ["squat_main", "hinge_main", "horizontal_push_main", "horizontal_pull_main",
                 "vertical_push_main", "vertical_pull_main"]:
        ex = result.get(slot)
        print(f"  {slot:<30} -> {ex.name if ex else 'MISSING'}")

    return result, bonuses


# =============================================================================
# TEMPLATE GETTERS - one per goal
# =============================================================================
# Each function returns the appropriate day template or None.
# None triggers the free-LP path (select_candidate_exercises, no slot constraints).
#
# Thresholds:
#   strength   : template up to 75 min  (long sessions benefit from free LP)
#   hypertrophy: template always         (PPL works at any session length)
#   athletic   : template up to 90 min
#   fat_loss   : template always         (full-body compounds always appropriate)
#   maintenance: template always         (low volume, no reason to go free LP)

def get_strength_template(session_minutes):
    if session_minutes <= 25:
        return {
            "Day1": ["squat_main", "horizontal_push_main"],
            "Day2": ["hinge_main", "horizontal_pull_main"],
            "Day3": ["squat_main", "vertical_pull_main"],
            "Day4": ["hinge_main", "vertical_push_main"],
            "Day5": ["horizontal_push_main", "horizontal_pull_main"],
            "Day6": ["squat_main", "vertical_push_main"],
        }
    elif session_minutes <= 45:
        return {
            "Day1": ["squat_main", "horizontal_push_main"],
            "Day2": ["hinge_main", "horizontal_pull_main"],
            "Day3": ["squat_main", "vertical_pull_main"],
            "Day4": ["hinge_main", "vertical_push_main"],
            "Day5": ["horizontal_push_main", "horizontal_pull_main"],
            "Day6": ["squat_main", "vertical_push_main"],
        }
    elif session_minutes <= 75:
        return STRENGTH_ALLOWED_SLOTS_BY_DAY
    else:
        return None  # large sessions: free LP placement


def get_hypertrophy_template(session_minutes, days_available):
    # PPL works at all session lengths; no free-LP fallback needed.
    # For 3 days the truncation (Day1-Day3) gives one Legs, Push, Pull session.
    return HYPERTROPHY_ALLOWED_SLOTS_BY_DAY


def get_athletic_template(session_minutes, days_available):
    if session_minutes > 90:
        return None  # very long sessions: free LP
    return ATHLETIC_ALLOWED_SLOTS_BY_DAY


def get_fat_loss_template(session_minutes, days_available):
    # Full-body compounds are always appropriate for fat loss.
    return FAT_LOSS_ALLOWED_SLOTS_BY_DAY


def get_maintenance_template(session_minutes, days_available):
    # Low volume maintenance works at all session lengths.
    return MAINTENANCE_ALLOWED_SLOTS_BY_DAY


# =============================================================================
#  HELPERS
# =============================================================================

def select_slots_for_goal(goal, all_exercises):
    """Route to the correct slot-selection function for each goal."""
    dispatch = {
        "hypertrophy":          select_hypertrophy_slots,
        "athletic_performance": select_athletic_slots,
        "fat_loss":             select_fat_loss_slots,
        "maintenance":          select_maintenance_slots,
    }
    fn = dispatch.get(goal)
    return fn(all_exercises) if fn else select_candidate_exercises(all_exercises, {}, goal)


def get_goal_template_for(goal, session_minutes, days_available):
    """Return the day template for a goal, or None for free-LP fallback."""
    if goal == "strength":
        return get_strength_template(session_minutes)
    elif goal == "hypertrophy":
        return get_hypertrophy_template(session_minutes, days_available)
    elif goal == "athletic_performance":
        return get_athletic_template(session_minutes, days_available)
    elif goal == "fat_loss":
        return get_fat_loss_template(session_minutes, days_available)
    elif goal == "maintenance":
        return get_maintenance_template(session_minutes, days_available)
    return None


# =============================================================================
# GUARD HELPERS
# =============================================================================

def can_remove_set(e, d, repaired, days, *, min_weekly_sets_by_exercise=None,
                   allowed_slots_by_day=None, template_min_per_day=0):
    if allowed_slots_by_day is not None and e in allowed_slots_by_day.get(d, []):
        if repaired[(e, d)] <= template_min_per_day:
            return False
    if min_weekly_sets_by_exercise and e in min_weekly_sets_by_exercise:
        if sum(repaired[(e, day)] for day in days) <= min_weekly_sets_by_exercise[e]:
            return False
    return True


def get_template_min_sets(days):
    if not days:
        return 0
    min_minutes = min(day.available_minutes for day in days.values())
    if min_minutes <= 40:  return 0
    elif min_minutes <= 55: return 1
    else:                   return 2


# =============================================================================
# MUSCLE CONTRIBUTION MATRIX
# =============================================================================

def build_contrib(exercises, muscles, secondary_weight=0.5):
    contrib = {}
    for e_key, ex in exercises.items():
        prim = {m.lower() for m in ex.primary_muscles}
        sec  = {m.lower() for m in ex.secondary_muscles}
        for m_key in muscles:
            m = m_key.lower()
            if m in prim:  contrib[(e_key, m_key)] = 1.0
            elif m in sec: contrib[(e_key, m_key)] = secondary_weight
            else:          contrib[(e_key, m_key)] = 0.0
    return contrib


# =============================================================================
# LP SOLUTION UTILITIES
# =============================================================================

def extract_lp_solution(x, exercises, days):
    return {(e, d): pulp.value(x[e][d]) or 0.0 for e in exercises for d in days}


def round_solution(x, exercises, days):
    return {(e, d): max(0, int(round(pulp.value(x[e][d]) or 0.0))) for e in exercises for d in days}


# =============================================================================
# METRICS
# =============================================================================

def compute_weekly_muscle_volumes(sets_dict, a, exercises, muscles, days):
    E, M, D = list(exercises), list(muscles), list(days)
    return {m: sum(a[(e, m)] * sets_dict[(e, d)] for e in E for d in D) for m in M}


def compute_total_fatigue(sets_dict, exercises, days):
    return sum(exercises[e].fatigue_per_set * sets_dict[(e, d)] for e in exercises for d in days)


def compute_plan_penalty(volumes, muscles):
    min_penalty    = sum(max(0.0, muscles[m].v_min - volumes[m]) for m in muscles)
    target_penalty = sum(abs(volumes[m] - muscles[m].v_target) for m in muscles)
    return 100 * min_penalty + target_penalty


def summarize_plan(sets_dict, a, exercises, muscles, days, recovery_budget):
    volumes = compute_weekly_muscle_volumes(sets_dict, a, exercises, muscles, days)
    fatigue = compute_total_fatigue(sets_dict, exercises, days)
    return {
        "fatigue":          round(fatigue, 2),
        "fatigue_excess":   round(max(0.0, fatigue - recovery_budget), 2),
        "min_shortfall":    round(sum(max(0.0, muscles[m].v_min - volumes[m]) for m in muscles), 2),
        "target_deviation": round(sum(abs(volumes[m] - muscles[m].v_target) for m in muscles), 2),
    }


# =============================================================================
# GOAL-SPECIFIC MUSCLE TARGETS
# =============================================================================

def build_muscles_from_goal(base_muscles, goal, days_available=3, session_minutes=60):
    weekly_time_factor = (days_available * session_minutes) / (3.0 * 60.0)

    if goal == "strength":
        volume_scale = max(0.90, min(3.00, 0.70 + 0.55 * weekly_time_factor))
    elif goal == "hypertrophy":
        volume_scale = max(0.90, min(2.00, 0.65 + 0.35 * weekly_time_factor))
    else:
        volume_scale = max(0.85, min(1.60, weekly_time_factor ** 0.6))

    goal_adjustments = {
        "strength":             {"primary": ["chest", "back", "quadriceps", "hamstrings", "glutes", "shoulders"], "pt": 1.00, "px": 1.15, "ot": 0.75, "ox": 0.85},
        "hypertrophy":          {"primary": ["chest", "back", "shoulders", "quadriceps", "hamstrings", "glutes"], "pt": 1.20, "px": 1.25, "ot": 1.05, "ox": 1.10},
        "athletic_performance": {"primary": ["quadriceps", "hamstrings", "glutes", "back"],                       "pt": 1.00, "px": 1.05, "ot": 0.75, "ox": 0.80},
        "fat_loss":             {"primary": list(base_muscles.keys()),                                            "pt": 0.90, "px": 0.95, "ot": 0.90, "ox": 0.95},
        "maintenance":          {"primary": list(base_muscles.keys()),                                            "pt": 0.75, "px": 0.80, "ot": 0.75, "ox": 0.80},
    }

    adj = goal_adjustments.get(goal, goal_adjustments["maintenance"])
    adjusted = {}
    for m_key, params in base_muscles.items():
        is_primary = m_key in adj["primary"]
        t_mult = adj["pt"] if is_primary else adj["ot"]
        x_mult = adj["px"] if is_primary else adj["ox"]
        adjusted[m_key] = MuscleParams(
            v_min   = round(params.v_min, 2),
            v_target= round(params.v_target * t_mult * volume_scale, 2),
            v_max   = round(params.v_max   * x_mult * volume_scale, 2),
        )
    return adjusted


# =============================================================================
# EXERCISE PARAMETER CONSTRUCTION FROM MONGODB PAYLOAD
# =============================================================================

def normalise_muscle_name(m):
    mapping = {"middle back": "back", "lats": "back", "traps": "back", "lower back": "back"}
    return mapping.get(m.lower(), m.lower())


def slugify_exercise_name(name):
    return (name.lower().replace(" ", "_").replace("-", "_")
            .replace("/", "_").replace("(", "").replace(")", "").replace(",", ""))


def estimate_time_per_set(category, primary_muscles, equipment):
    if category == "strength":   return 4.0
    if category == "hypertrophy": return 3.0
    return 2.5


def estimate_fatigue_per_set(category, primary_muscles, secondary_muscles):
    if any(m in primary_muscles for m in ["quadriceps", "hamstrings", "glutes"]):
        return 1.5
    return 1.3 if category == "strength" else 1.0


def is_unwanted_exercise_name(name):
    n = name.lower()
    blocked = [
        "mountain climber", "burpee", "jumping jack", "high knees", "butt kicks",
        "skater", "sprint", "jog", "run ", "running", "walk ", "walking",
        "treadmill", "cycling", "bike", "rowing machine",
        "warm up", "warm-up", "cool down", "cool-down", "stretch", "mobility", "foam roll",
    ]
    return any(kw in n for kw in blocked)


def is_too_technical_for_general_use(name):
    n = name.lower()
    return any(kw in n for kw in [
        "clean and jerk", "snatch", "power clean", "hang clean",
        "split jerk", "push jerk", "clean pull", "muscle snatch",
    ])


def is_explosive_lower_body(name):
    n = name.lower()
    return any(kw in n for kw in ["jump squat", "box jump", "depth jump", "broad jump", "jump lunge", "plyometric"])


def should_keep_exercise(name, category, primary, secondary, goal, experience_level):
    n = name.lower()
    if is_unwanted_exercise_name(name):   return False
    if is_too_technical_for_general_use(name):
        return goal == "athletic_performance" and experience_level == "advanced"
    if is_explosive_lower_body(name):
        return goal == "athletic_performance"

    if goal == "strength":
        blocked = [
            "fly", "pullover", "with chains", "with band", "with bands", "neutral grip",
            "kneeling", "jump", "plyometric", "clean and jerk", "snatch", "neutral-grip",
            "guillotine", "medium grip", "close-grip", "close grip", "underhand",
            "wide-grip", "wide grip", "to a bench", "zercher", "floor", "supinated",
            "one leg", "one-leg", "single leg", "rear delt", "cambered", "powerlifting",
            "one arm", "one-arm",
            "long bar", "clean grip", "alternating", "scapular", "straight arm",
            "full range-of-motion", "full range of motion", "decline", "straight-arm",
        ]
        if any(kw in n for kw in blocked):
            return False

    if "pullover" in n and goal in ["strength", "athletic_performance"]:
        return False

    tracked = {"quadriceps", "hamstrings", "glutes", "chest", "back", "shoulders"}
    if not any(m in tracked for m in primary + secondary):
        return False

    return True


def build_exercise_preference_bonus(name, category, primary, secondary, equipment, goal):
    n = name.lower()
    bonus = 0.0
    if any(kw in n for kw in ["squat", "deadlift", "bench", "row", "press", "lunge", "split squat", "hip thrust", "pull up", "chin up"]):
        bonus += 1.0
    if category in ["strength", "hypertrophy"]:
        bonus += 0.3
    equipment_lower = [str(e).lower() for e in (equipment or [])]
    if goal == "strength":
        if "barbell" in equipment_lower: bonus += 0.8
        if "rack"    in equipment_lower: bonus += 0.4
        if category == "strength":       bonus += 0.8
    elif goal == "hypertrophy":
        if any(kw in n for kw in ["press", "row", "curl", "extension", "raise", "pulldown"]):
            bonus += 0.8
    elif goal == "athletic_performance":
        if any(kw in n for kw in ["squat", "deadlift", "rdl", "lunge", "row"]): bonus += 0.8
        if is_explosive_lower_body(name): bonus += 0.6
    elif goal in ("fat_loss", "maintenance"):
        if any(kw in n for kw in ["squat", "row", "deadlift", "press", "lunge"]): bonus += 0.6
    return round(bonus, 2)


def build_exercises_from_payload(exercise_payloads, goal=None, experience_level=None):
    built, bonuses = {}, {}
    for item in exercise_payloads:
        name = item.get("name")
        if not name: continue
        key           = item.get("id") or slugify_exercise_name(name)
        primary_raw   = item.get("primaryMuscles", [])
        secondary_raw = item.get("secondaryMuscles", [])
        equipment     = item.get("equipment", [])
        category      = item.get("category")
        primary       = [normalise_muscle_name(m) for m in primary_raw]
        secondary     = [normalise_muscle_name(m) for m in secondary_raw]
        if not should_keep_exercise(name, category, primary, secondary, goal, experience_level):
            continue
        built[key] = ExerciseParams(
            name=name, primary_muscles=primary, secondary_muscles=secondary,
            time_per_set=estimate_time_per_set(category, primary, equipment),
            fatigue_per_set=estimate_fatigue_per_set(category, primary, secondary),
        )
        bonuses[key] = build_exercise_preference_bonus(name, category, primary, secondary, equipment, goal)
    return built, bonuses


# =============================================================================
# GREEDY REPAIR
# =============================================================================

def repair_rounded_solution(rounded_sets, a, exercises, muscles, days, *, recovery_budget,
                             min_weekly_sets_by_exercise=None, allowed_slots_by_day=None, template_min_per_day=0):
    E, D = list(exercises), list(days)
    repaired = dict(rounded_sets)
    print("\n=== Repair Process ===")
    step = 0
    while compute_total_fatigue(repaired, exercises, days) > recovery_budget + 1e-6:
        current = compute_total_fatigue(repaired, exercises, days)
        print(f"Step {step}: fatigue={current:.2f} (budget={recovery_budget})")
        best_move, best_score = None, None
        for e in E:
            for d in D:
                if repaired[(e, d)] <= 0: continue
                day_total = sum(repaired[(x, d)] for x in E)
                if allowed_slots_by_day is None and min_weekly_sets_by_exercise and day_total <= 3:
                    continue
                if not can_remove_set(e, d, repaired, D, min_weekly_sets_by_exercise=min_weekly_sets_by_exercise,
                                      allowed_slots_by_day=allowed_slots_by_day, template_min_per_day=template_min_per_day):
                    continue
                candidate = dict(repaired)
                candidate[(e, d)] -= 1
                score = compute_plan_penalty(compute_weekly_muscle_volumes(candidate, a, exercises, muscles, days), muscles)
                if best_score is None or score < best_score:
                    best_score, best_move = score, (e, d)
        if best_move is None:
            print("No valid repair move found."); break
        e_b, d_b = best_move
        repaired[(e_b, d_b)] -= 1
        print(f"  Removed 1 set of {exercises[e_b].name} on {d_b}")
        step += 1
    print(f"Final repaired fatigue: {compute_total_fatigue(repaired, exercises, days):.2f}")
    return repaired


def repair_time_and_set_violations(rounded_sets, a, exercises, muscles, days, *, max_sets_per_day,
                                    min_weekly_sets_by_exercise=None, allowed_slots_by_day=None, template_min_per_day=0):
    E, D = list(exercises), list(days)
    repaired = dict(rounded_sets)
    print("\n=== Time/Set Feasibility Repair ===")

    def day_time(d, s): return sum(exercises[e].time_per_set * s[(e, d)] for e in E)
    def day_sets(d, s): return sum(s[(e, d)] for e in E)

    changed = True
    while changed:
        changed = False
        for d in D:
            while day_time(d, repaired) > days[d].available_minutes + 1e-6 or day_sets(d, repaired) > max_sets_per_day + 1e-6:
                best_move, best_score = None, None
                for e in E:
                    if repaired[(e, d)] <= 0: continue
                    day_total = sum(repaired[(x, d)] for x in E)
                    if allowed_slots_by_day is None and min_weekly_sets_by_exercise and day_total <= 3:
                        continue
                    if not can_remove_set(e, d, repaired, D, min_weekly_sets_by_exercise=min_weekly_sets_by_exercise,
                                          allowed_slots_by_day=allowed_slots_by_day, template_min_per_day=template_min_per_day):
                        continue
                    candidate = dict(repaired)
                    candidate[(e, d)] -= 1
                    score = compute_plan_penalty(compute_weekly_muscle_volumes(candidate, a, exercises, muscles, days), muscles)
                    if best_score is None or score < best_score:
                        best_score, best_move = score, (e, d)
                if best_move is None:
                    print(f"  No valid move for {d}"); break
                e_b, d_b = best_move
                repaired[(e_b, d_b)] -= 1
                changed = True
                print(f"  Removed 1 set of {exercises[e_b].name} on {d_b} (time/set)")
    return repaired


# =============================================================================
# CORE LP SOLVER
# =============================================================================

def solve_training_lp_relaxation(
    exercises, muscles, days, *,
    recovery_budget=None, max_sets_per_day=18, secondary_weight=0.5,
    goal_exercise_bonus=None, per_exercise_day_cap=4, weekly_exercise_cap=8,
    min_weekly_sets_by_exercise=None, allowed_slots_by_day=None,
    template_min_sets_override=None,
):
    E, M, D = list(exercises), list(muscles), list(days)
    if goal_exercise_bonus is None:
        goal_exercise_bonus = {e: 0.0 for e in E}

    preferred_used_days = len(D)
    a = build_contrib(exercises, muscles, secondary_weight=secondary_weight)
    model = pulp.LpProblem("TrainingLP_v2", pulp.LpMinimize)

    x = pulp.LpVariable.dicts("sets", (E, D), lowBound=0, cat="Continuous")

    if allowed_slots_by_day is not None:
        for d in D:
            allowed = set(allowed_slots_by_day.get(d, []))
            for e in E:
                if e not in allowed:
                    model += x[e][d] == 0, f"disallow_{e}_{d}"
        template_min_sets = (
            template_min_sets_override
            if template_min_sets_override is not None
            else get_template_min_sets(days)
        )
        
        if template_min_sets > 0:
            for d in D:
                for e in allowed_slots_by_day.get(d, []):
                    if e in E:
                        model += x[e][d] >= template_min_sets, f"tpl_min_{e}_{d}"

    y             = pulp.LpVariable.dicts("day_used", D, lowBound=0, upBound=1, cat="Binary")
    day_shortfall = pulp.LpVariable("day_shortfall", lowBound=0)
    s_min         = pulp.LpVariable.dicts("slack_min",    M, lowBound=0)
    under         = pulp.LpVariable.dicts("under_target", M, lowBound=0)
    over          = pulp.LpVariable.dicts("over_target",  M, lowBound=0)
    peak_day_sets = pulp.LpVariable("peak_day_sets", lowBound=0)

    peak_day_penalty = 0.8 if allowed_slots_by_day is None and max_sets_per_day >= 20 else 0.0

    model += (
        100 * pulp.lpSum(s_min[m] for m in M)
        + 1.0 * pulp.lpSum(under[m] for m in M)
        + 0.2 * pulp.lpSum(over[m] for m in M)
        + 20  * day_shortfall
        + peak_day_penalty * peak_day_sets
        - 0.5 * pulp.lpSum(goal_exercise_bonus[e] * x[e][d] for e in E for d in D)
        - 0.35 * pulp.lpSum(x[e][d] for e in E for d in D)
    ), "Objective"

    min_sets_for_used_day = (
        2 if allowed_slots_by_day is not None
        else (5 if max_sets_per_day >= 28 else (3 if max_sets_per_day >= 20 else 1))
    )

    for d in D:
        day_total = pulp.lpSum(x[e][d] for e in E)
        model += pulp.lpSum(exercises[e].time_per_set * x[e][d] for e in E) <= days[d].available_minutes, f"time_{d}"
        model += day_total <= max_sets_per_day,                        f"set_cap_{d}"
        model += day_total <= max_sets_per_day * y[d],                 f"day_link_hi_{d}"
        model += day_total >= min_sets_for_used_day * y[d],            f"day_link_lo_{d}"
        model += day_total <= peak_day_sets,                           f"peak_{d}"
        for e in E:
            model += x[e][d] <= per_exercise_day_cap, f"ex_day_{e}_{d}"

    for e in E:
        model += pulp.lpSum(x[e][d] for d in D) <= weekly_exercise_cap, f"weekly_{e}"

    if min_weekly_sets_by_exercise:
        for e, min_s in min_weekly_sets_by_exercise.items():
            if e in E:
                model += pulp.lpSum(x[e][d] for d in D) >= min_s, f"min_weekly_{e}"

    model += pulp.lpSum(y[d] for d in D) + day_shortfall >= preferred_used_days, "spread"
    model += pulp.lpSum(exercises[e].fatigue_per_set * x[e][d] for e in E for d in D) <= recovery_budget, "budget"

    for m in M:
        vol = pulp.lpSum(a[(e, m)] * x[e][d] for e in E for d in D)
        model += vol + s_min[m] >= muscles[m].v_min,               f"min_{m}"
        model += vol <= muscles[m].v_max,                           f"max_{m}"
        model += vol - muscles[m].v_target == over[m] - under[m],  f"tgt_{m}"

    print("Solving model...")
    start = time.time()
    model.solve(pulp.PULP_CBC_CMD(msg=False))
    print(f"Solve time: {time.time()-start:.4f}s  |  Status: {pulp.LpStatus[model.status]}")
    return model, x, a


# =============================================================================
# POST-PROCESSING
# =============================================================================

def deduplicate_day_by_family(day_items):
    seen, filtered = set(), []
    for item in day_items:
        family = get_movement_family(item["exerciseName"])
        if family is None:       filtered.append(item)
        elif family not in seen: seen.add(family); filtered.append(item)
    return filtered


def spread_sessions_across_days(plan, days):
    day_names     = list(days.keys())
    used_sessions = [plan[d] for d in day_names if plan.get(d)]
    if not used_sessions or len(used_sessions) >= len(day_names):
        return plan
    n, total = len(used_sessions), len(day_names)
    positions = [round(i * (total - 1) / (n - 1)) if n > 1 else 0 for i in range(n)]
    final, used_pos = [], set()
    for pos in positions:
        while pos in used_pos and pos < total - 1: pos += 1
        while pos in used_pos and pos > 0:          pos -= 1
        used_pos.add(pos); final.append(pos)
    new_plan = {d: [] for d in day_names}
    for session, pos in zip(used_sessions, final):
        new_plan[day_names[pos]] = session
    return new_plan


def build_days_from_profile(days_available, session_minutes):
    days_available  = max(1, int(days_available or 3))
    session_minutes = max(1, int(session_minutes or 60))
    warmup_overhead = 6 if session_minutes <= 20 else (8 if session_minutes <= 45 else 12)
    usable_minutes  = max(6, session_minutes - warmup_overhead)
    return {f"Day{i}": DayParams(available_minutes=usable_minutes) for i in range(1, days_available + 1)}


def build_plan_response_from_sets(sets_dict, exercises, days, a, muscles, recovery_budget, deduplicate_families=True):
    plan = {}
    for d in days:
        day_items = [
            {"exerciseKey": e, "exerciseName": exercises[e].name, "sets": int(round(sets_dict[(e, d)]))}
            for e in exercises if int(round(sets_dict[(e, d)])) >= 1
        ]
        plan[d] = deduplicate_day_by_family(day_items) if deduplicate_families else day_items
    return {"plan": plan, "summary": summarize_plan(sets_dict, a, exercises, muscles, days, recovery_budget)}


def fill_empty_strength_days(sets_dict, exercises, days, allowed_slots_by_day):
    repaired = dict(sets_dict)
    E, D = list(exercises), list(days)
    for d in D:
        if sum(repaired[(e, d)] for e in E) > 0:
            continue
        for e in allowed_slots_by_day.get(d, []):
            if e not in exercises: continue
            used = sum(exercises[x].time_per_set * repaired[(x, d)] for x in E)
            if used + exercises[e].time_per_set * 2 <= days[d].available_minutes + 1e-6:
                repaired[(e, d)] += 2; break
    return repaired


# =============================================================================
# REPORTING HELPERS
# =============================================================================

def print_plan_summary(label, summary):
    print(f"\n=== {label} Summary ===")
    for k in ("fatigue", "fatigue_excess", "min_shortfall", "target_deviation"):
        print(f"  {k}: {summary[k]:.2f}")


def print_lp_solution(model, x, a, exercises, muscles, days):
    print(f"\nStatus: {pulp.LpStatus[model.status]}\n=== LP Solution ===")
    for d in days:
        print(f"{d}:")
        used = False
        for e in exercises:
            val = pulp.value(x[e][d]) or 0.0
            if val > 1e-6:
                print(f"  {exercises[e].name}: {val:.2f}"); used = True
        if not used: print("  Rest")
    print("\n=== LP Muscle Volumes ===")
    for m in muscles:
        vol = sum(a[(e, m)] * (pulp.value(x[e][d]) or 0.0) for e in exercises for d in days)
        print(f"  {m}: {vol:.2f} (min={muscles[m].v_min}, tgt={muscles[m].v_target}, max={muscles[m].v_max})")


def evaluate_integer_solution(label, sets_dict, a, exercises, muscles, days):
    print(f"\n=== {label} ===")
    for d in days:
        print(f"{d}:")
        used = False
        for e in exercises:
            val = sets_dict[(e, d)]
            if val > 0:
                s = int(round(val)) if abs(val - round(val)) < 1e-6 else f"{val:.2f}"
                print(f"  {exercises[e].name}: {s} sets"); used = True
        if not used: print("  Rest")
    for d in days:
        t = sum(exercises[e].time_per_set * sets_dict[(e, d)] for e in exercises)
        print(f"  {d}: {t:.2f} min (limit={days[d].available_minutes})")
    for m in muscles:
        vol = sum(a[(e, m)] * sets_dict[(e, d)] for e in exercises for d in days)
        print(f"  {m}: {vol:.2f} (min={muscles[m].v_min}, tgt={muscles[m].v_target}, max={muscles[m].v_max})")
    print(f"  Fatigue: {compute_total_fatigue(sets_dict, exercises, days):.2f}")


def check_plan_feasibility(label, sets_dict, a, exercises, muscles, days, *, recovery_budget, max_sets_per_day):
    print(f"\n=== {label} Feasibility ===")
    for d in days:
        t = sum(exercises[e].time_per_set * sets_dict[(e, d)] for e in exercises)
        s = sum(sets_dict[(e, d)] for e in exercises)
        s_str = str(int(round(s))) if abs(s - round(s)) < 1e-6 else f"{s:.2f}"
        print(f"  {d}: time={t:.2f}/{days[d].available_minutes} {'OK' if t<=days[d].available_minutes+1e-6 else 'VIOLATION'} | sets={s_str}/{max_sets_per_day} {'OK' if s<=max_sets_per_day+1e-6 else 'VIOLATION'}")
    f = compute_total_fatigue(sets_dict, exercises, days)
    print(f"  Fatigue: {f:.2f}/{recovery_budget} {'OK' if f<=recovery_budget+1e-6 else 'VIOLATION'}")
    for m in muscles:
        vol = sum(a[(e, m)] * sets_dict[(e, d)] for e in exercises for d in days)
        print(f"  {m}: {vol:.2f} | min {'OK' if vol>=muscles[m].v_min-1e-6 else 'VIOLATION'} | max {'OK' if vol<=muscles[m].v_max+1e-6 else 'VIOLATION'}")


def evaluate_plan_pipeline(label, sets_dict, a, exercises, muscles, days, *, recovery_budget, max_sets_per_day):
    evaluate_integer_solution(label, sets_dict, a, exercises, muscles, days)
    check_plan_feasibility(label, sets_dict, a, exercises, muscles, days,
                           recovery_budget=recovery_budget, max_sets_per_day=max_sets_per_day)
    print_plan_summary(label, summarize_plan(sets_dict, a, exercises, muscles, days, recovery_budget))


def run_scenario(scenario_name, exercises, muscles, days, *, recovery_budget, max_sets_per_day, secondary_weight):
    print(f"\n{'='*60}\nSCENARIO: {scenario_name}\n{'='*60}")
    model, x, a = solve_training_lp_relaxation(exercises, muscles, days,
        recovery_budget=recovery_budget, max_sets_per_day=max_sets_per_day, secondary_weight=secondary_weight)
    print_lp_solution(model, x, a, exercises, muscles, days)
    print_plan_summary("LP", summarize_plan(extract_lp_solution(x, exercises, days), a, exercises, muscles, days, recovery_budget))
    rounded = round_solution(x, exercises, days)
    evaluate_plan_pipeline("Rounded", rounded, a, exercises, muscles, days,
                           recovery_budget=recovery_budget, max_sets_per_day=max_sets_per_day)
    repaired = repair_rounded_solution(rounded, a, exercises, muscles, days, recovery_budget=recovery_budget)
    evaluate_plan_pipeline("Repaired", repaired, a, exercises, muscles, days,
                           recovery_budget=recovery_budget, max_sets_per_day=max_sets_per_day)


# =============================================================================
# MAIN ENTRY POINT - called by Flask API
# =============================================================================

def generate_optimized_plan_response(
    exercises, muscles, days, *,
    recovery_budget=None, max_sets_per_day=None, secondary_weight=0.5,
    days_available=None, session_minutes=None, goal=None, experience_level=None,
    available_equipment=None, exercise_payloads=None,
):
    """
    Full pipeline for all five goals.

    Each goal follows the same structure:
      1. get_goal_template_for()  - returns a day template or None (free-LP fallback)
      2. select_slots_for_goal()  - picks canonical exercises by name for each slot
         OR select_candidate_exercises() for the free-LP path
      3. compute_min_weekly_sets_for_goal()  - floors per exercise
      4. Solve LP → round → repair (shared for all goals)
      5. Post-process (spread_sessions for non-strength, dedup for all)

    Strength has its own legacy path preserved exactly as before.
    All other goals use the unified dispatch system.
    """
    days_available  = int(days_available  or 3)
    session_minutes = int(session_minutes or 60)
    goal            = goal or "maintenance"

    active_days    = build_days_from_profile(days_available, session_minutes)
    active_muscles = build_muscles_from_goal(
        muscles if muscles else BASE_MUSCLE_PARAMS, goal, days_available, session_minutes,
    )

    dynamic_budget    = compute_recovery_budget(days_available, session_minutes, goal)
    lp_params         = compute_lp_params(days_available, session_minutes, goal)
    effective_budget  = recovery_budget   if recovery_budget   is not None else dynamic_budget
    effective_max_sets = max_sets_per_day if max_sets_per_day  is not None else lp_params["max_sets_per_day"]

    print(f"\nProfile: goal={goal}, days={days_available}, mins={session_minutes}, level={experience_level}")
    print(f"LP params: budget={effective_budget}, max_sets/day={effective_max_sets}, "
          f"per_ex_cap={lp_params['per_exercise_day_cap']}, weekly_cap={lp_params['weekly_exercise_cap']}")

    # Step 1: build filtered pool from MongoDB
    if exercise_payloads:
        all_exercises, all_bonuses = build_exercises_from_payload(
            exercise_payloads, goal=goal, experience_level=experience_level,
        )
    else:
        all_exercises = exercises
        all_bonuses   = {k: 0.0 for k in exercises}
    print(f"After hard filtering: {len(all_exercises)} exercises")

    # -------------------------------------------------------------------------
    # Step 2: pre-selection - goal-specific routing
    # -------------------------------------------------------------------------
    if goal == "strength":
        # Strength: preserved exactly as before
        strength_template = get_strength_template(session_minutes)

        if strength_template is None:
            optimizer_exercises, goal_bonus = select_candidate_exercises(
                all_exercises, all_bonuses, "strength", max_per_family=2,
            )
            allowed_slots        = None
            template_min_per_day = 0
            weekly_time_factor   = (days_available * session_minutes) / (3.0 * 60.0)
            big_lift_min         = 4 if weekly_time_factor >= 3.5 else (3 if weekly_time_factor >= 2.5 else 2)
            upper_secondary_min  = 2 if weekly_time_factor >= 2.5 else 1
            min_weekly = {}
            for e_key, ex in optimizer_exercises.items():
                fam = get_movement_family(ex.name)
                if fam in {"squat", "hinge", "horizontal_push", "horizontal_pull"}:
                    min_weekly[e_key] = big_lift_min
                elif fam in {"vertical_push", "vertical_pull"}:
                    min_weekly[e_key] = upper_secondary_min
        else:
            optimizer_exercises, goal_bonus = select_strength_slots(all_exercises)
            min_weekly = compute_min_weekly_sets_for_goal(
                goal, days_available, session_minutes, set(optimizer_exercises.keys()),
            )
            allowed_slots = {
                f"Day{i+1}": [s for s in strength_template.get(f"Day{i+1}", []) if s in optimizer_exercises]
                for i in range(days_available)
            }
            template_min_per_day = get_template_min_sets(active_days)

            if min_weekly and allowed_slots:
                reachable = {e for slots in allowed_slots.values() for e in slots}
                min_weekly = {e: v for e, v in min_weekly.items() if e in reachable}

        missing = {"squat_main","hinge_main","horizontal_push_main","horizontal_pull_main",
                   "vertical_push_main","vertical_pull_main"} - set(optimizer_exercises.keys())
        if missing:
            print(f"WARNING: Missing strength slots: {sorted(missing)}")

    else:
        # All other goals: unified dispatch
        goal_template = get_goal_template_for(goal, session_minutes, days_available)

        if goal_template is None:
            # Free-LP fallback for large sessions
            optimizer_exercises, goal_bonus = select_candidate_exercises(all_exercises, all_bonuses, goal)
            allowed_slots        = None
            template_min_per_day = 0
        else:
            optimizer_exercises, goal_bonus = select_slots_for_goal(goal, all_exercises)
            allowed_slots = {
                f"Day{i+1}": [s for s in goal_template.get(f"Day{i+1}", []) if s in optimizer_exercises]
                for i in range(days_available)
            }
            template_min_per_day = 1 if goal == "maintenance" else get_template_min_sets(active_days)

        min_weekly = compute_min_weekly_sets_for_goal(
            goal, days_available, session_minutes, set(optimizer_exercises.keys()),
        )

        if min_weekly and allowed_slots:
            reachable = {e for slots in allowed_slots.values() for e in slots}
            min_weekly = {e: v for e, v in min_weekly.items() if e in reachable}

        min_weekly = compute_min_weekly_sets_for_goal(
            goal, days_available, session_minutes, set(optimizer_exercises.keys()),
        )

    if not optimizer_exercises:
        print("WARNING: pre-selection empty - falling back to full filtered pool.")
        optimizer_exercises, goal_bonus, min_weekly = all_exercises, all_bonuses, None
        allowed_slots = None

    active_min_weekly = min_weekly

    # Step 3: solve
    model, x, a = solve_training_lp_relaxation(
        optimizer_exercises, active_muscles, active_days,
        recovery_budget=effective_budget,
        max_sets_per_day=effective_max_sets,
        secondary_weight=secondary_weight,
        goal_exercise_bonus=goal_bonus,
        per_exercise_day_cap=lp_params["per_exercise_day_cap"],
        weekly_exercise_cap=lp_params["weekly_exercise_cap"],
        min_weekly_sets_by_exercise=active_min_weekly,
        allowed_slots_by_day=allowed_slots,
        template_min_sets_override=template_min_per_day,
    )

    status = pulp.LpStatus[model.status]
    if status != "Optimal":
        print(f"Retrying with relaxed constraints (status={status})...")
        active_min_weekly = (
            {e: max(1, int(round(v * 0.5))) for e, v in active_min_weekly.items()}
            if active_min_weekly else None
        )
        model, x, a = solve_training_lp_relaxation(
            optimizer_exercises, active_muscles, active_days,
            recovery_budget=effective_budget, max_sets_per_day=effective_max_sets,
            secondary_weight=secondary_weight, goal_exercise_bonus=goal_bonus,
            per_exercise_day_cap=lp_params["per_exercise_day_cap"],
            weekly_exercise_cap=lp_params["weekly_exercise_cap"],
            min_weekly_sets_by_exercise=active_min_weekly,
            allowed_slots_by_day=allowed_slots,
            template_min_sets_override=template_min_per_day,
        )
        status = pulp.LpStatus[model.status]

    if status != "Optimal":
        return {
            "plan": {}, "summary": {"fatigue": 0, "fatigue_excess": 0, "min_shortfall": 0, "target_deviation": 0},
            "warning": f"Model status was {status}; no valid plan could be produced.",
        }

    # Step 4: round + repair
    rounded_sets   = round_solution(x, optimizer_exercises, active_days)
    time_fixed     = repair_time_and_set_violations(
        rounded_sets, a, optimizer_exercises, active_muscles, active_days,
        max_sets_per_day=effective_max_sets,
        min_weekly_sets_by_exercise=active_min_weekly,
        allowed_slots_by_day=allowed_slots,
        template_min_per_day=template_min_per_day,
    )
    repaired_sets  = repair_rounded_solution(
        time_fixed, a, optimizer_exercises, active_muscles, active_days,
        recovery_budget=effective_budget,
        min_weekly_sets_by_exercise=active_min_weekly,
        allowed_slots_by_day=allowed_slots,
        template_min_per_day=template_min_per_day,
    )

    if goal == "strength" and session_minutes <= 20 and allowed_slots is not None:
        repaired_sets = fill_empty_strength_days(repaired_sets, optimizer_exercises, active_days, allowed_slots)

    # Step 5: post-process
    # Strength keeps day order from template; all other goals spread sessions evenly.
    # Deduplication is skipped for free-LP strength (same family may legitimately appear twice).
    deduplicate = not (goal == "strength" and get_strength_template(session_minutes) is None)

    response = build_plan_response_from_sets(
        repaired_sets, optimizer_exercises, active_days, a, active_muscles,
        effective_budget, deduplicate_families=deduplicate,
    )

    if goal != "strength":
        response["plan"] = spread_sessions_across_days(response["plan"], active_days)

    response["inputs_used"] = {
        "days_available":      days_available,
        "session_minutes":     session_minutes,
        "goal":                goal,
        "experience_level":    experience_level,
        "available_equipment": available_equipment or [],
        "recovery_budget":     effective_budget,
        "max_sets_per_day":    effective_max_sets,
        "secondary_weight":    secondary_weight,
        "exercise_count":      len(optimizer_exercises),
    }

    return response


## if __name__ == "__main__":
##     run_scenario("Baseline",        exercises, muscles, days, recovery_budget=30.0, max_sets_per_day=18, secondary_weight=0.5)
##     run_scenario("Tighter Budget",  exercises, muscles, days, recovery_budget=26.0, max_sets_per_day=18, secondary_weight=0.5)
##     run_scenario("Lower Secondary", exercises, muscles, days, recovery_budget=30.0, max_sets_per_day=18, secondary_weight=0.3)
##     run_scenario("Tight Day Cap",   exercises, muscles, days, recovery_budget=30.0, max_sets_per_day=10, secondary_weight=0.5)
