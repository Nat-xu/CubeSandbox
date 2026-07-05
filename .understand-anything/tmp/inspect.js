const fs = require('fs');
const idx = process.argv[2] ? process.argv[2].split(',') : ['1','2','3','4','5','6','7','8','9'];
for (const i of idx) {
  const p = `CubeAPI/.understand-anything/tmp/ua-file-extract-results-${i}.json`;
  const j = JSON.parse(fs.readFileSync(p, 'utf8'));
  console.log(`batch${i}: results=${j.results.length} filesAnalyzed=${j.filesAnalyzed} skipped=${(j.filesSkipped||[]).length}`);
  for (const r of j.results) {
    const extras = [];
    if (r.services) extras.push('services='+r.services.length);
    if (r.endpoints) extras.push('endpoints='+r.endpoints.length);
    if (r.resources) extras.push('resources='+r.resources.length);
    if (r.steps) extras.push('steps='+r.steps.length);
    if (r.definitions) extras.push('defs='+r.definitions.length);
    if (r.sections) extras.push('sections='+r.sections.length);
    console.log(`  ${r.path} cat=${r.fileCategory} lang=${r.language} lines=${r.totalLines} nonEmpty=${r.nonEmptyLines} fns=${(r.functions||[]).length} cls=${(r.classes||[]).length} ${extras.join(' ')}`);
  }
}