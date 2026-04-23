from dataclasses import dataclass


@dataclass(frozen=True)
class ExerciseParams:
    name: str
    primary_muscles: list[str]
    secondary_muscles: list[str]
    time_per_set: float
    fatigue_per_set: float


@dataclass(frozen=True)
class MuscleParams:
    v_min: float
    v_target: float
    v_max: float


@dataclass(frozen=True)
class DayParams:
    available_minutes: float


exercises = {
    "squat": ExerciseParams(
        name="Squat",
        primary_muscles=["quadriceps"],
        secondary_muscles=["hamstrings", "glutes"],
        time_per_set=4.0,
        fatigue_per_set=1.6,
    ),
    "bench": ExerciseParams(
        name="Bench Press",
        primary_muscles=["chest"],
        secondary_muscles=["shoulders", "triceps"],
        time_per_set=4.0,
        fatigue_per_set=1.4,
    ),
    "row": ExerciseParams(
        name="Bent-Over Row",
        primary_muscles=["back"],
        secondary_muscles=["biceps"],
        time_per_set=3.5,
        fatigue_per_set=1.3,
    ),
    "rdl": ExerciseParams(
        name="Romanian Deadlift",
        primary_muscles=["hamstrings", "glutes"],
        secondary_muscles=["lower back"],
        time_per_set=4.0,
        fatigue_per_set=1.5,
    ),
    "ohp": ExerciseParams(
        name="Overhead Press",
        primary_muscles=["shoulders"],
        secondary_muscles=["triceps", "chest"],
        time_per_set=3.5,
        fatigue_per_set=1.3,
    ),
}

muscles = {
    "quadriceps": MuscleParams(v_min=4, v_target=6, v_max=10),
    "hamstrings": MuscleParams(v_min=4, v_target=6, v_max=10),
    "glutes": MuscleParams(v_min=4, v_target=6, v_max=10),
    "chest": MuscleParams(v_min=4, v_target=6, v_max=10),
    "back": MuscleParams(v_min=4, v_target=6, v_max=10),
    "shoulders": MuscleParams(v_min=3, v_target=5, v_max=8),
}

days = {
    "Mon": DayParams(available_minutes=60),
    "Wed": DayParams(available_minutes=60),
    "Fri": DayParams(available_minutes=60),
}
