// Vercel requires Serverless Function entrypoints to live inside /api so
// that the `functions` property in vercel.json (used here for maxDuration)
// can match them. This file just re-exports the existing Express app from
// src/start.js — no logic was moved or duplicated.
module.exports = require('../src/start.js');
