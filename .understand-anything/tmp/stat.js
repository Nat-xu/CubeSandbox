const fs = require('fs');
const g = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/assembled-graph.json', 'utf8'));
const nodeTypes = {}, edgeTypes = {};
for (const n of g.nodes) nodeTypes[n.type] = (nodeTypes[n.type]||0)+1;
for (const e of g.edges) edgeTypes[e.type] = (edgeTypes[e.type]||0)+1;
console.log('nodes:', g.nodes.length, JSON.stringify(nodeTypes));
console.log('edges:', g.edges.length, JSON.stringify(edgeTypes));
// list file-level nodes (the ones architecture/tour care about)
const fileLevel = g.nodes.filter(n => ['file','config','document','service','pipeline','table','schema','resource','endpoint'].includes(n.type));
console.log('file-level nodes:', fileLevel.length);
console.log('sample file nodes:');
for (const n of fileLevel.slice(0, 60)) console.log(`  ${n.type}: ${n.filePath || n.id} — ${(n.summary||'').slice(0,40)}`);