import pulp
import time


MAX_SESSION_MINUTES = 150


def _clamp(value, low, high):
    return max(low, min(high, value))


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=None):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def compute_calorie_target(weight_kg, goal, days_available, session_minutes):
    """
    Simplified calorie target estimate based on:
    - bodyweight
    - weekly training minutes
    - goal adjustment

    """
    weekly_training_minutes = days_available * session_minutes

    # Simple activity multiplier driven by weekly training minutes
    # ~30 kcal/kg baseline, increasing modestly with training volume
    activity_multiplier = 30.0 + min(8.0, weekly_training_minutes / 120.0)

    maintenance_kcal = weight_kg * activity_multiplier

    goal_adjustment = {
        "fat_loss": -350,
        "maintenance": 0,
        "strength": 150,
        "hypertrophy": 250,
        "athletic_performance": 200,
    }.get(goal, 0)

    return round(maintenance_kcal + goal_adjustment)


def get_macro_rules(goal):
    """
    Goal-specific macro rules.
    Returns mins and targets in g/kg where appropriate.
    """
    rules = {
        "strength": {
            "protein_min_per_kg": 1.8,
            "protein_target_per_kg": 2.0,
            "fat_min_per_kg": 0.7,
            "fat_target_per_kg": 0.8,
            "carb_min_per_kg": 2.5,
            "calorie_tolerance": 125,
            "weights": {"protein": 4.0, "carbs": 2.0, "fat": 1.5, "calories": 3.0},
        },
        "hypertrophy": {
            "protein_min_per_kg": 1.8,
            "protein_target_per_kg": 2.0,
            "fat_min_per_kg": 0.7,
            "fat_target_per_kg": 0.8,
            "carb_min_per_kg": 3.0,
            "calorie_tolerance": 150,
            "weights": {"protein": 4.0, "carbs": 3.0, "fat": 1.5, "calories": 2.5},
        },
        "fat_loss": {
            "protein_min_per_kg": 2.0,
            "protein_target_per_kg": 2.2,
            "fat_min_per_kg": 0.6,
            "fat_target_per_kg": 0.7,
            "carb_min_per_kg": 1.5,
            "calorie_tolerance": 100,
            "weights": {"protein": 4.0, "carbs": 1.5, "fat": 2.0, "calories": 4.0},
        },
        "maintenance": {
            "protein_min_per_kg": 1.6,
            "protein_target_per_kg": 1.8,
            "fat_min_per_kg": 0.7,
            "fat_target_per_kg": 0.8,
            "carb_min_per_kg": 2.0,
            "calorie_tolerance": 120,
            "weights": {"protein": 3.0, "carbs": 1.5, "fat": 2.0, "calories": 3.0},
        },
        "athletic_performance": {
            "protein_min_per_kg": 1.7,
            "protein_target_per_kg": 1.9,
            "fat_min_per_kg": 0.7,
            "fat_target_per_kg": 0.8,
            "carb_min_per_kg": 3.5,
            "calorie_tolerance": 150,
            "weights": {"protein": 3.0, "carbs": 4.0, "fat": 1.5, "calories": 3.0},
        },
    }

    return rules.get(goal, rules["maintenance"])


def build_rule_based_macro_plan(weight_kg, goal, days_available, session_minutes):
    """
    Fallback if LP ever fails.
    """
    calorie_target = compute_calorie_target(weight_kg, goal, days_available, session_minutes)
    rules = get_macro_rules(goal)

    protein = weight_kg * rules["protein_target_per_kg"]
    fat = weight_kg * rules["fat_target_per_kg"]
    carbs = max(
        weight_kg * rules["carb_min_per_kg"],
        (calorie_target - 4 * protein - 9 * fat) / 4.0,
    )

    calories = 4 * protein + 4 * carbs + 9 * fat

    return {
        "calories": int(round(calories)),
        "protein": int(round(protein)),
        "carbs": int(round(carbs)),
        "fat": int(round(fat)),
        "goal": goal,
        "calorieTarget": int(round(calorie_target)),
        "method": "rule_based_fallback",
    }


def generate_macro_plan_response(
    *,
    weight_kg=None,
    goal=None,
    days_available=None,
    session_minutes=None,
):
    """
    Main nutrition LP entry point.
    """
    weight_kg = _safe_float(weight_kg, 80.0)
    goal = goal or "maintenance"
    days_available = _clamp(_safe_int(days_available, 3), 1, 7)
    session_minutes = _clamp(_safe_int(session_minutes, 60), 1, MAX_SESSION_MINUTES)

    if weight_kg is None or weight_kg <= 0:
        raise ValueError("A valid weight_kg is required to generate a macro plan.")

    calorie_target = compute_calorie_target(weight_kg, goal, days_available, session_minutes)
    rules = get_macro_rules(goal)

    protein_min = weight_kg * rules["protein_min_per_kg"]
    protein_target = weight_kg * rules["protein_target_per_kg"]

    fat_min = weight_kg * rules["fat_min_per_kg"]
    fat_target = weight_kg * rules["fat_target_per_kg"]

    carb_min = weight_kg * rules["carb_min_per_kg"]
    carb_target = max(
        carb_min,
        (calorie_target - 4 * protein_target - 9 * fat_target) / 4.0,
    )

    calorie_tolerance = rules["calorie_tolerance"]
    weights = rules["weights"]

    model = pulp.LpProblem("MacroPlanLP", pulp.LpMinimize)

    protein = pulp.LpVariable("protein", lowBound=0)
    carbs = pulp.LpVariable("carbs", lowBound=0)
    fat = pulp.LpVariable("fat", lowBound=0)

    p_under = pulp.LpVariable("p_under", lowBound=0)
    p_over = pulp.LpVariable("p_over", lowBound=0)
    c_under = pulp.LpVariable("c_under", lowBound=0)
    c_over = pulp.LpVariable("c_over", lowBound=0)
    f_under = pulp.LpVariable("f_under", lowBound=0)
    f_over = pulp.LpVariable("f_over", lowBound=0)
    kcal_under = pulp.LpVariable("kcal_under", lowBound=0)
    kcal_over = pulp.LpVariable("kcal_over", lowBound=0)

    calories_expr = 4 * protein + 4 * carbs + 9 * fat

    model += (
        weights["protein"] * (p_under + p_over)
        + weights["carbs"] * (c_under + c_over)
        + weights["fat"] * (f_under + f_over)
        + weights["calories"] * (kcal_under + kcal_over)
    ), "Objective"

    # Hard minimums
    model += protein >= protein_min, "protein_min"
    model += fat >= fat_min, "fat_min"
    model += carbs >= carb_min, "carb_min"

    # Keep calories in a sensible band
    model += calories_expr >= calorie_target - calorie_tolerance, "calorie_floor"
    model += calories_expr <= calorie_target + calorie_tolerance, "calorie_ceiling"

    # Prevent silly upper values
    model += protein <= max(protein_target * 1.35, protein_min + 20), "protein_max"
    model += fat <= max(fat_target * 1.35, fat_min + 15), "fat_max"
    model += carbs <= max(carb_target * 1.50, carb_min + 100), "carb_max"

    # Deviation equations
    model += protein - protein_target == p_over - p_under, "protein_target_dev"
    model += carbs - carb_target == c_over - c_under, "carb_target_dev"
    model += fat - fat_target == f_over - f_under, "fat_target_dev"
    model += calories_expr - calorie_target == kcal_over - kcal_under, "calorie_target_dev"

    print("Solving macro model...")
    start = time.time()
    model.solve(pulp.PULP_CBC_CMD(msg=False))
    solve_time = time.time() - start
    status = pulp.LpStatus[model.status]
    print(f"Macro solve time: {solve_time:.4f}s | Status: {status}")

    if status != "Optimal":
        return build_rule_based_macro_plan(weight_kg, goal, days_available, session_minutes)

    protein_val = pulp.value(protein) or 0.0
    carbs_val = pulp.value(carbs) or 0.0
    fat_val = pulp.value(fat) or 0.0
    calories_val = 4 * protein_val + 4 * carbs_val + 9 * fat_val

    return {
        "calories": int(round(calories_val)),
        "protein": int(round(protein_val)),
        "carbs": int(round(carbs_val)),
        "fat": int(round(fat_val)),
        "goal": goal,
        "calorieTarget": int(round(calorie_target)),
        "method": "lp",
    }


if __name__ == "__main__":
    print(
        generate_macro_plan_response(
            weight_kg=80,
            goal="hypertrophy",
            days_available=5,
            session_minutes=75,
        )
    )
