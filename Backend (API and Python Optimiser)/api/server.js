import "dotenv/config";
import express from "express";
import cors from "cors";
import mongoose from "mongoose";
import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import fs from "fs";
import { ApolloServer } from "@apollo/server";
import { expressMiddleware } from "@apollo/server/express4";

import Exercise from "./models/Exercise.js";
import PlannerProfile from "./models/PlannerProfile.js";


console.log("SERVER VERSION: equipment helper with Set is loaded");


// ================== ENV ==================
const MONGO_URI = process.env.MONGO_URI;
const JWT_SECRET = process.env.JWT_SECRET;

const PYTHON_OPTIMIZER_URL =
  process.env.PYTHON_OPTIMIZER_URL || "https://optimiserapi-production.up.railway.app";

function matchesAvailableEquipment(exerciseEquipment = [], availableEquipment = []) {
  const userEquipment = new globalThis.Set(
    (availableEquipment || []).map((e) => String(e).toLowerCase())
  );

  const requiredEquipment = (exerciseEquipment || []).map((e) =>
    String(e).toLowerCase()
  );

  console.log("equipment helper debug", {
    setCtor: globalThis.Set.name,
    userEquipmentType: userEquipment.constructor?.name,
    hasType: typeof userEquipment.has,
    sampleAvailable: availableEquipment?.slice?.(0, 5),
    sampleRequired: requiredEquipment?.slice?.(0, 5),
  });

  if (requiredEquipment.length === 0) return true;

  return requiredEquipment.every((eq) => userEquipment.has(eq));
}

async function callPythonOptimizer({
  recovery_budget = 30.0,
  max_sets_per_day = 18,
  secondary_weight = 0.5,
  days_available = null,
  session_minutes = null,
  goal = null,
  experience_level = null,
  available_equipment = [],
  exercises = [],
}) {
  const response = await fetch(`${PYTHON_OPTIMIZER_URL}/generate-plan`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      recovery_budget,
      max_sets_per_day,
      secondary_weight,
      days_available,
      session_minutes,
      goal,
      experience_level,
      available_equipment,
      exercises,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(
      `Optimizer request failed: ${response.status} ${response.statusText} - ${text}`
    );
  }

  return await response.json();
}

if (!MONGO_URI) {
  throw new Error("❌ Missing env var: MONGO_URI");
}
if (!JWT_SECRET) {
  throw new Error("❌ Missing env var: JWT_SECRET");
}

// ================== MongoDB ==================
await mongoose.connect(MONGO_URI);
console.log("✅ Connected to MongoDB");

// ================== Schemas / Models ==================
const UserSchema = new mongoose.Schema({
  email: { type: String, unique: true, required: true },
  passwordHash: { type: String, required: true },
});
const User = mongoose.models.User || mongoose.model("User", UserSchema);

const SetSchema = new mongoose.Schema({
  exerciseId: { type: mongoose.Schema.Types.ObjectId, ref: "Exercise" }, // using this for the new database, don't forget to update resolvers
  exerciseName: { type: String, required: true, index: true },
  reps: { type: Number, required: true },
  weight: { type: Number, required: true },
  date: { type: Date, default: Date.now },
  userId: { type: mongoose.Schema.Types.ObjectId, ref: "User", required: true },
});
const WorkoutSet = mongoose.models.Set || mongoose.model("Set", SetSchema);



// ================== GraphQL Schema ==================
const typeDefs = fs.readFileSync("./index.graphql", "utf-8");

// ================== Auth Helper ==================

console.log("CWD =", process.cwd());
console.log("schema exists at ./index.graphql ?", fs.existsSync("./index.graphql"));
console.log("schema preview:", typeDefs.slice(0, 200));

async function getUserFromReq(req) {
  const header = req.headers.authorization || "";
  console.log("AUTH HEADER:", header);

  if (!header.startsWith("Bearer ")) {console.log("No bearer token"); return null};

  const token = header.replace("Bearer ", "").trim();
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    console.log("Decoded JWT:", decoded);
    return decoded
  } catch (err){
    console.log("JWT verification error:", err);
    return null;
  }
}

// ================== Resolvers ==================
const resolvers = {
  Query: {
    exercise: async (_, { id }) => {
      const e = await Exercise.findById(id);
      if (!e) return null;

      return {
        id: e._id.toString(),
        name: e.name,
        category: e.category ?? null,
        equipment: e.equipment ?? [],
        primaryMuscles: e.primaryMuscles ?? [],
        secondaryMuscles: e.secondaryMuscles ?? [],
        instructions: e.instructions ?? [],
        images: e.images ?? [],
        difficulty: e.difficulty ?? null,
      };
    },

    exercises: async (_, { muscle, equipment, q, limit = 30, offset = 0 }) => {
      const filter = {};

      const muscleGroups = {
        upper: [
          "chest",
          "shoulders",
          "biceps",
          "triceps",
          "lats",
          "middle back",
          "traps",
        ],
        lower: [
          "quadriceps",
          "hamstrings",
          "calves",
          "glutes",
          "adductors",
          "abductors",
        ],
        core: [
          "abdominals",
          "lower back",
        ],
        pull: [
          "lats",
          "middle back",
          "traps",
          "biceps",
        ],
        push: [
          "chest",
          "shoulders",
          "triceps",
        ],
      };


      // Search by name
      if (q && q.trim()) {
        filter.name = { $regex: q.trim(), $options: "i" };
      }

      // Filter by muscle (primary OR secondary arrays)
      let muscleValue = null;

      if (muscle && muscle.trim()) {
        muscleValue = muscle.trim().toLowerCase();

        const musclesToMatch = muscleGroups[muscleValue] || [muscleValue];

        filter.$or = [
          { primaryMuscles: { $in: musclesToMatch } },
          { secondaryMuscles: { $in: musclesToMatch } },
        ];
      }


      // Filter by equipment (equipment is an array in our DB)
      if (equipment && equipment.trim()) {
        const eq = equipment.trim().toLowerCase();
        filter.equipment = { $in: [eq] };
      }

      const safeLimit = Math.min(Math.max(limit, 1), 100);
      const safeOffset = Math.max(offset, 0);

      let rows = await Exercise.find(filter)
        .skip(safeOffset)
        .limit(safeLimit);

      if (muscleValue) {
        rows.sort((a, b) => {
          const aPrimary = a.primaryMuscles.includes(muscleValue);
          const bPrimary = b.primaryMuscles.includes(muscleValue);

          if (aPrimary && !bPrimary) return -1;
          if (!aPrimary && bPrimary) return 1;

          return a.name.localeCompare(b.name);
        });
      } else {
        rows.sort((a, b) => a.name.localeCompare(b.name));
      }
      // Map Mongo _id -> GraphQL id
      return rows.map((e) => ({
        id: e._id.toString(),
        name: e.name,
        category: e.category ?? null,
        equipment: e.equipment ?? [],
        primaryMuscles: e.primaryMuscles ?? [],
        secondaryMuscles: e.secondaryMuscles ?? [],
        instructions: e.instructions ?? [],
        images: e.images ?? [],
        difficulty: e.difficulty ?? null,
      }));
    },

    sets: async (_, { exerciseId, exerciseName }, { user }) => {
      if (!user) throw new Error("Not authenticated");

      const filter = { userId: user.userId };
      if (exerciseId) filter.exerciseId = exerciseId;
      else if (exerciseName) filter.exerciseName = exerciseName; // fallback

      const rows = await WorkoutSet.find(filter).sort({ date: -1 });

      return rows.map((s) => ({
        ...s.toObject(),
        _id: s._id.toString(),
        date: s.date.toISOString(),
      }));
    },

    myPlannerProfile: async (_, __, { user }) => {
      if (!user) throw new Error("Not authenticated");

      const profile = await PlannerProfile.findOne({ userId: user.userId });

      if (!profile) return null;

      return {
        id: profile._id.toString(),
        userId: profile.userId.toString(),
        height: profile.height ?? null,
        weight: profile.weight ?? null,
        goal: profile.goal ?? null,
        experienceLevel: profile.experienceLevel ?? null,
        availableEquipment: profile.availableEquipment ?? [],
        daysAvailable: profile.daysAvailable ?? null,
        sessionMinutes: profile.sessionMinutes ?? null,
        createdAt: profile.createdAt?.toISOString() ?? null,
        updatedAt: profile.updatedAt?.toISOString() ?? null,
      };
    },

    generateOptimizedPlan: async (_, __, { user }) => {
      if (!user) throw new Error("Not authenticated");

      const profile = await PlannerProfile.findOne({ userId: user.userId });
      if (!profile) {
        throw new Error("Planner profile not found");
      }

      const allExercises = await Exercise.find({});
      const equipmentFiltered = allExercises.filter((exercise) =>
        matchesAvailableEquipment(exercise.equipment ?? [], profile.availableEquipment ?? [])
      );

      const optimizerExercises = equipmentFiltered.map((e) => ({
        id: e._id.toString(),
        name: e.name,
        category: e.category ?? null,
        equipment: e.equipment ?? [],
        primaryMuscles: e.primaryMuscles ?? [],
        secondaryMuscles: e.secondaryMuscles ?? [],
      }));

      const result = await callPythonOptimizer({
        recovery_budget: 30.0,
        max_sets_per_day: 18,
        secondary_weight: 0.5,
        days_available: profile.daysAvailable ?? null,
        session_minutes: profile.sessionMinutes ?? null,
        goal: profile.goal ?? null,
        experience_level: profile.experienceLevel ?? null,
        available_equipment: profile.availableEquipment ?? [],
        exercises: optimizerExercises,
      });

      console.log("OPTIMIZER RESULT INPUTS USED:", result.inputs_used);

      const planArray = Object.entries(result.plan || {}).map(([day, exercises]) => ({
        day,
        exercises,
      }));

      return {
        plan: planArray,
        summary: result.summary,
      };
    },

    generateMacroPlan: async (_, __, { user }) => {
      if (!user) {
        throw new Error("Not authenticated");
      }

      const profile = await PlannerProfile.findOne({ userId: user.userId });

      if (!profile) {
        throw new Error("Planner profile not found.");
      }

      const response = await fetch(`${PYTHON_OPTIMIZER_URL}/generate-macros`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          weight: profile.weight,
          goal: profile.goal,
          days_available: profile.daysAvailable,
          session_minutes: Math.min(profile.sessionMinutes || 60, 150),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to generate macro plan.");
      }

      return data;
    },

  },

  Mutation: {
    signup: async (_, { email, password }) => {
      const exists = await User.findOne({ email });
      if (exists) throw new Error("Email already used");

      const passwordHash = await bcrypt.hash(password, 10);
      const user = await User.create({ email, passwordHash });

      const token = jwt.sign(
        { userId: user._id.toString(), email },
        JWT_SECRET,
        { expiresIn: "7d" }
      );

      console.log("LOGIN TOKEN:", token);

      try 
      {
        const decodedTest = jwt.verify(token, JWT_SECRET);
        console.log("SELF-VERIFY OK:", decodedTest);
      } catch (err) {
        console.log("SELF-VERIFY FAILED:", err.message);
      }

      return { token, user };
    },

    login: async (_, { email, password }) => {
      const user = await User.findOne({ email });
      if (!user) throw new Error("Invalid credentials");

      const valid = await bcrypt.compare(password, user.passwordHash);
      if (!valid) throw new Error("Invalid credentials");

      const token = jwt.sign(
        { userId: user._id.toString(), email },
        JWT_SECRET,
        { expiresIn: "7d" }
      );

      return { token, user };
    },

    addWorkout: async (_, { exerciseId,exerciseName, reps, weight }, { user }) => {
      if (!user) throw new Error("Not authenticated");

      const s = await WorkoutSet.create({
        exerciseId,
        exerciseName,
        reps,
        weight,
        userId: user.userId,
      });

      return {
        ...s.toObject(),
        _id: s._id.toString(),
        date: s.date.toISOString(),
      };
    },

    deleteWorkoutSet: async (_, { setId }, { user }) => {
      if (!user) throw new Error("Not authenticated");

      const deleted = await WorkoutSet.findOneAndDelete({
        _id: setId,
        userId: user.userId,
      });

      return !!deleted;
    },

    savePlannerProfile: async (_, { input }, { user }) => {
      if (!user) throw new Error("Not authenticated");

      const profile = await PlannerProfile.findOneAndUpdate(
        { userId: user.userId },
        {
          $set: {
            userId: user.userId,
            height: input.height ?? null,
            weight: input.weight ?? null,
            goal: input.goal ?? null,
            experienceLevel: input.experienceLevel ?? null,
            availableEquipment: input.availableEquipment ?? [],
            daysAvailable: input.daysAvailable ?? null,
            sessionMinutes: input.sessionMinutes ?? null,
          },
        },
        {
          new: true,
          upsert: true,
          setDefaultsOnInsert: true,
        }
      );

      return {
        id: profile._id.toString(),
        userId: profile.userId.toString(),
        height: profile.height ?? null,
        weight: profile.weight ?? null,
        goal: profile.goal ?? null,
        experienceLevel: profile.experienceLevel ?? null,
        availableEquipment: profile.availableEquipment ?? [],
        daysAvailable: profile.daysAvailable ?? null,
        sessionMinutes: profile.sessionMinutes ?? null,
        createdAt: profile.createdAt?.toISOString() ?? null,
        updatedAt: profile.updatedAt?.toISOString() ?? null,
      };
    },
  },
};

// ================== Apollo v4 Server ==================
const server = new ApolloServer({ typeDefs, resolvers });
await server.start();

// ================== Express App ==================
const app = express();
app.use(cors());
app.use(express.urlencoded({ extended: true }));
app.use(express.json());

app.use(
  "/graphql",
  express.json(),
  expressMiddleware(server, {
    context: async ({ req }) => ({
      user: await getUserFromReq(req),
    }),
  })
);

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
