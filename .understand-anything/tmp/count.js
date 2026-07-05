const fs = require('fs');
const dir = 'CubeAPI/.understand-anything/intermediate';
const files = fs.readdirSync(dir).filter(f => /^batch-\d+(?:-part-\d+)?\.json$/.test(f)).sort();
let tn = 0, te = 0;
for (const f of files) {
  try {
    const j = JSON.parse(fs.readFileSync(`${dir}/${f}`, 'utf8'));
    const n = (j.nodes || []).length;
    const e = (j.edges || []).length;
    tn += n; te += e;
    console.log(`${f}: nodes=${n} edges=${e}`);
  } catch (err) {
    console.log(`${f}: INVALID JSON - ${err.message}`);
  }
}
console.log(`TOTAL pre-merge: nodes=${tn} edges=${te} files=${files.length}`);