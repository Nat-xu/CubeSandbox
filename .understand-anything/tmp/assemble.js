const fs = require('fs');
const ag = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/assembled-graph.json', 'utf8'));
const layers = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/layers.json', 'utf8'));
const tour = JSON.parse(fs.readFileSync('CubeAPI/.understand-anything/intermediate/tour.json', 'utf8'));
const kg = {
  version: '1.0.0',
  project: {
    name: 'cube-api',
    languages: ['dockerfile','go','json','makefile','markdown','python','rust','shell','toml'],
    frameworks: ['Axum','Tokio','serde','tower','tower-http','Docker'],
    description: '基于 Axum 框架的 Rust 实现的 E2B 兼容 API 服务，运行在 Cube 沙箱基础设施之上；无需修改客户端代码，只需将 E2B_API_URL 与 E2B_API_KEY 指向本服务即可从 E2B 云无缝迁移到 Cube 平台。',
    analyzedAt: '2026-07-05T10:24:23Z',
    gitCommitHash: '5c7025f3a393c30e723dd7f071ef1c28d7a2e52e'
  },
  nodes: ag.nodes,
  edges: ag.edges,
  layers: layers,
  tour: tour
};
fs.writeFileSync('CubeAPI/.understand-anything/intermediate/assembled-graph.json', JSON.stringify(kg, null, 2));
console.log('assembled knowledge graph written:', kg.nodes.length, 'nodes,', kg.edges.length, 'edges,', kg.layers.length, 'layers,', kg.tour.length, 'tour steps');