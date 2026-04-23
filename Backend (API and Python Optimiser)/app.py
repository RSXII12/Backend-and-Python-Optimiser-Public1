import os
import traceback

from flask import Flask, jsonify, request

from sample_data import exercises, muscles, days
from training_milp_v1 import generate_optimized_plan_response
from nutrition_milp_v1 import generate_macro_plan_response

app = Flask(__name__)

MAX_SESSION_MINUTES = 150

@app.get("/health")
def health():
    return jsonify({"status": "ok"})
    
@app.route("/generate-macros", methods=["POST"])
def generate_macros():
    try:
        data = request.get_json() or {}

        weight_kg = data.get("weight")
        goal = data.get("goal")
        days_available = max(1, min(int(data.get("days_available") or 3), 7))
        session_minutes = max(1, min(int(data.get("session_minutes") or 60), MAX_SESSION_MINUTES))

        result = generate_macro_plan_response(
            weight_kg=weight_kg,
            goal=goal,
            days_available=days_available,
            session_minutes=session_minutes,
        )

        return jsonify(result)

    except Exception as e:
        print("ERROR IN /generate-macros")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
        

@app.route("/generate-plan", methods=["GET", "POST"])
def generate_plan():
    if request.method == "GET":
        return jsonify({
            "message": "Use POST for /generate-plan"
        }), 405

    try:
        data = request.get_json() or {}
        
        exercise_payloads = data.get("exercises", [])
        recovery_budget = None#data.get("recovery_budget")#, 30.0)
        max_sets_per_day = None#data.get("max_sets_per_day")#, 18)
        secondary_weight = data.get("secondary_weight", 0.5)

        days_available = max(1, min(int(data.get("days_available") or 3), 7))
        session_minutes = max(1, min(int(data.get("session_minutes") or 60), MAX_SESSION_MINUTES))
        goal = data.get("goal")
        experience_level = data.get("experience_level")
        available_equipment = data.get("available_equipment", [])

        result = generate_optimized_plan_response(
            exercises,
            muscles,
            days,
            recovery_budget=recovery_budget,
            max_sets_per_day=max_sets_per_day,
            secondary_weight=secondary_weight,
            days_available=days_available,
            session_minutes=session_minutes,
            goal=goal,
            experience_level=experience_level,
            available_equipment=available_equipment,
            exercise_payloads=exercise_payloads,
        )

        return jsonify(result)

    except Exception as e:
        print("ERROR IN /generate-plan")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
