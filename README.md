Optimiser / Backend Repo
Overview
Backend services for the fitness app, including:
GraphQL API for app data
Python optimisation engine for training and nutrition planning

Features
Training plan optimisation (MILP-based)
Macro/nutrition planning
REST endpoints for plan generation
Backend logic for user data and workouts
Tech Stack
Python (Flask, PuLP)
Node.js (GraphQL API)
MongoDB
Endpoints
POST /generate-plan → training plan optimisation
POST /generate-macros → nutrition planning
GET /health → service status

Architecture
This repo contains the backend layer:

Node/GraphQL API (app data)
Python optimisation service (plan generation)

Used by:
Frontend app:
[](https://github.com/RSXII12/Fitness-Optimisation-App-Public/tree/main)

Setup
Python service
pip install -r requirements.txt
python app.py
Node backend
npm install
npm start
Notes
Requires environment variables for DB/API access (Not included)
Designed to be deployed (via Railway)
