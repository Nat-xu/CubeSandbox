const fs = require('fs');
const g = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/assembled-graph.json', 'utf8'));
const ids = new Set(g.nodes.map(n => n.id));
const layers = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/layers.json', 'utf8'));
const fileLevel = new Set(g.nodes.filter(n => ['file','config','document','service','pipeline','table','schema','resource','endpoint'].includes(n.type)).map(n => n.id));
let totalAssigned = 0, missing = [], multi = new Map(), unassigned = [];
for (const l of layers) {
  for (const id of l.nodeIds) {
    totalAssigned++;
    if (!ids.has(id)) missing.push(`${l.id} -> ${id}`);
    if (multi.has(id)) missing.push(`DUP ${multi.get(id)} & ${l.id} -> ${id}`);
    multi.set(id, l.id);
  }
}
for (const id of fileLevel) { if (!multi.has(id)) unassigned.push(id); }
console.log('layers:', layers.length, 'assigned:', totalAssigned, 'fileLevel:', fileLevel.size);
console.log('missing/dup:', missing.length, missing.slice(0, 20));
console.log('unassigned file-level nodes:', unassigned.length, unassigned.slice(0, 20));