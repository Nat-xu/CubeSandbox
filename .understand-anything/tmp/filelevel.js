const fs = require('fs');
const g = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/assembled-graph.json', 'utf8'));
const fileLevel = g.nodes.filter(n => ['file','config','document','service','pipeline','table','schema','resource','endpoint'].includes(n.type));
const ids = fileLevel.map(n => n.id).sort();
console.log(JSON.stringify(ids, null, 0));
console.log('COUNT', ids.length);
// also print imports edges for layer intuition
const imp = g.edges.filter(e => e.type === 'imports').map(e => `${e.source} -> ${e.target}`);
console.log('IMPORTS_EDGES', imp.length);