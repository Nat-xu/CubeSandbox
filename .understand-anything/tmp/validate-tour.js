const fs = require('fs');
const g = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/assembled-graph.json', 'utf8'));
const ids = new Set(g.nodes.map(n => n.id));
const tour = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/tour.json', 'utf8'));
let missing = [];
for (const s of tour) for (const id of s.nodeIds) if (!ids.has(id)) missing.push(`${s.order}: ${id}`);
console.log('tour steps:', tour.length, 'missing refs:', missing.length, missing.slice(0,20));