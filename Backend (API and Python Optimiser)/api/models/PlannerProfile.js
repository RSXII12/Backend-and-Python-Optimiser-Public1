import mongoose from "mongoose";

const PlannerProfileSchema = new mongoose.Schema(
  {
    userId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: "User",
      required: true,
      unique: true,
      index: true,
    },
    height: { type: Number, min: 100, max: 300 },
    weight: { type: Number, min: 40, max: 500 },
    goal: {
      type: String,
      enum: ["strength", "hypertrophy", "fat_loss", "maintenance", "athletic_performance"],
    },
    experienceLevel: {
      type: String,
      enum: ["beginner", "intermediate", "advanced"],
    },
    availableEquipment: {
      type: [String],
      default: [],
    },
    daysAvailable: { type: Number, min: 2, max: 7 },
    sessionMinutes: { type: Number, min: 20, max: 300 },
  },
  { timestamps: true }
);

export default mongoose.models.PlannerProfile || mongoose.model("PlannerProfile", PlannerProfileSchema);