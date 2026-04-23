import mongoose from "mongoose";

const ExerciseSchema = new mongoose.Schema(
  {
    name: {
      type: String,
      required: true,
      index: true,
    },

    category: {
      type: String, // strength, cardio, stretching, etc.
    },

    equipment: {
      type: [String], // barbell, dumbbell, machine, bodyweight
      default: [],
    },

    primaryMuscles: {
      type: [String], // e.g. quadriceps, glutes
      required: true,
      index: true,
    },

    secondaryMuscles: {
      type: [String],
      default: [],
    },

    instructions: {
      type: [String],
      default: [],
    },

    images: {
      type: [String], // URLs
      default: [],
    },

    difficulty: {
      type: Number, // 1–5 (optional, can infer later)
      min: 1,
      max: 5,
    },
  },
  {
    timestamps: true, // adds createdAt, updatedAt
  }
);

// Prevent model overwrite in dev / hot reload
export default mongoose.models.Exercise ||
  mongoose.model("Exercise", ExerciseSchema);
