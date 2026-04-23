import mongoose from "mongoose";
import "dotenv/config";
import fetch from "node-fetch";
import Exercise from "../models/Exercise.js";

const EXERCISES_URL =
  "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json";

async function seed() {
  console.log("🌱 Starting exercise seed…");

  await mongoose.connect(process.env.MONGO_URI);
  console.log("✅ Mongo connected");

  const res = await fetch(EXERCISES_URL);
  const data = await res.json();

  let inserted = 0;

  for (const ex of data) {
    await Exercise.updateOne(
      { name: ex.name },
      {
        $set: {
          name: ex.name,
          category: ex.category,
          equipment: ex.equipment || [],
          primaryMuscles: ex.primaryMuscles || [],
          secondaryMuscles: ex.secondaryMuscles || [],
          instructions: ex.instructions || [],
          images: (ex.images || []).map(
            (img) =>
              `https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/images/${img}`
          ),
        },
      },
      { upsert: true }
    );

    inserted++;
  }

  console.log(`✅ Seeded ${inserted} exercises`);
  process.exit(0);
}

seed().catch((err) => {
  console.error("❌ Seed failed:", err);
  process.exit(1);
});
