const fs = require('fs');
const sr = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/scan-result.json', 'utf8'));
const sourcePaths = sr.files.map(f => f.path);
const input = {
  projectRoot: 'C:/Users/18257/Desktop/issue/CubeSandbox/CubeAPI',
  sourceFilePaths: sourcePaths,
  gitCommitHash: '5c7025f3a393c30e723dd7f071ef1c28d7a2e52e'
};
fs.writeFileSync('CubeAPI/.understand-anything/intermediate/fingerprint-input.json', JSON.stringify(input, null, 2));
console.log('fingerprint-input written:', sourcePaths.length, 'paths');