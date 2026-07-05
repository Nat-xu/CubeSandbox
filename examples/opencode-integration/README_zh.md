# OpenCode + CubeSandbox 示例

[English](README.md)

在 CubeSandbox MicroVM 内运行 [OpenCode](https://www.npmjs.com/package/opencode-ai)
（开源终端 AI 编码 Agent）。Agent 在一个隔离、可复现的沙箱内编辑文件、执行命令并访问
LLM API。

本示例包含：

- 一个 `Dockerfile`：在 CubeSandbox 基础镜像上叠加 Node.js 与 OpenCode CLI
  （envd 已监听 `:49983`）。
- `run_opencode.py`：在 `/workspace` 内的一次性无交互运行。
- `resume_opencode.py`：跨两轮的 pause/resume，证明 `/workspace` 与 OpenCode
  配置目录在快照后仍存在。
- `.env.example`、`requirements.txt`。

## 目录结构

```
opencode-integration/
├── Dockerfile            # CubeSandbox 模板镜像（Node.js + OpenCode CLI）
├── .env.example          # 复制为 .env 并填写
├── requirements.txt      # 宿主端驱动依赖（e2b、python-dotenv）
├── _common.py            # 共享辅助（沙箱操作、密钥解析、凭据清理）
├── run_opencode.py       # 一次性 OpenCode 任务
├── resume_opencode.py    # pause / resume 会话持久化
├── README.md             # 英文文档
└── README_zh.md          # 中文文档（本文件）
```

## 前置条件

- 已部署 CubeSandbox，CubeAPI 可访问（`http://<node>:8080`）。
- `cubemastercli` 已在 `$PATH` 且已连通集群。
- 构建机装有 Docker，且 registry 能被 Cube 集群拉取。
- 一个 LLM provider 的 API Key（默认 OpenAI；OpenCode 支持的其他 provider 均可）。
- Python 3.9+（宿主端驱动脚本）。

## 1. 构建模板镜像

```bash
docker build --platform linux/amd64 \
  -t <your-registry>/opencode-cube:latest \
  examples/opencode-integration
docker push <your-registry>/opencode-cube:latest
```

镜像会安装 `opencode-ai`，以及 `git`、`python3`、`ripgrep`、`jq`，并清理 apt/npm
缓存。OpenCode 版本默认安装 `@latest`；如需固定版本请修改 `Dockerfile`。

## 2. 注册为 Cube 模板

```bash
cubemastercli tpl create-from-image \
  --image <your-registry>/opencode-cube:latest \
  --writable-layer-size 4G \
  --expose-port 49983 \
  --probe       49983 \
  --probe-path  /health

cubemastercli tpl watch --job-id <job_id>
```

任务变为 `READY` 后记下 `template_id`。

## 3. 配置宿主端驱动

```bash
cd examples/opencode-integration
cp .env.example .env
# 填写 E2B_API_URL、E2B_API_KEY、CUBE_TEMPLATE_ID 以及你的 provider key
pip install -r requirements.txt
```

| 变量 | 作用位置 | 说明 |
|---|---|---|
| `E2B_API_URL` | 本地进程 | CubeAPI 地址（`http://<node>:8080`） |
| `E2B_API_KEY` | 本地进程 | 本地开发填任意非空字符串 |
| `CUBE_TEMPLATE_ID` | `Sandbox.create(template=...)` | 来自第 2 步 |
| `OPENAI_API_KEY` | `envs=...`（逐命令注入） | provider 密钥，仅在该命令执行期间存在 |
| `OPENCODE_PROVIDER` | OpenCode CLI `--provider` 参数 | `openai`（默认）、`anthropic` 等 |

## 4. 一次性运行

```bash
python run_opencode.py --prompt "创建 hello.py 打印 'Hello from CubeSandbox' 并运行它。"
```

密钥通过 `sandbox.commands.run(..., envs=...)` 逐命令传入，只在该命令执行期间存在，
不会写入 VM 内的持久文件。

> **安全：** 本示例默认放开出网，Agent 被攻破可能外泄注入的密钥。共享集群请使用
> CubeEgress 密钥保险柜配合默认拒绝出网（参考 pi-agent 的 `network_policy.py` 示例）。

脚本会打印 OpenCode 的 stdout/stderr、退出码以及最终的 `/workspace` 文件列表。
运行结束后会暂停沙箱并打印 sandbox ID 以供后续恢复。

## 5. pause / resume（会话持久化）

```bash
python resume_opencode.py --sandbox-id <run_opencode.py 输出的 id>
```

第一轮（由 `run_opencode.py` 执行）在 `/workspace` 写入产物并调用
`sandbox.pause()`。本脚本用 `Sandbox.connect(sandbox_id)` 恢复，校验
`/workspace` 与 OpenCode 配置目录（`/home/agent/.config/opencode`）在快照后仍存在，
再执行第二轮续写。沙箱生命周期用 `try/finally` 手动管理（不用 context manager），
避免 pause 后被过早 `kill` 掉。

## 排错

| 现象 | 可能原因 | 处理 |
|---|---|---|
| preflight 报 `opencode: command not found` | CLI 变更后未重建模板 | 重建镜像并重新注册模板 |
| provider 鉴权失败 | 密钥未传入 | 确保正确设置了 `*_API_KEY` 环境变量，并通过 `envs=` 传入 |
| `403 Forbidden - CubeEgress` | 默认拒绝且无匹配放行规则 | 将 LLM host 加入出网规则，或开发阶段保持出网开放 |
| OpenCode 报 `Connection error` / TLS 失败 | Node 运行时忽略系统 CA 库（在出网拦截场景下） | 设置 `NODE_EXTRA_CA_CERTS` 指向系统 CA bundle 路径 |
| 模板创建卡在 `PULLING` | Cube 节点无法访问 registry | 推送到集群可访问的 registry，必要时提供鉴权 |
| 就绪探针超时 | 镜像缺少 envd | 确认 `FROM ghcr.io/tencentcloud/cubesandbox-base:...` |
| `pause()` / `connect()` 报错 | 平台版本过低不支持快照 | 升级 CubeSandbox 平台 |

## 参考

- 集成指南：[`docs/zh/guide/integrations/opencode.md`](../../docs/zh/guide/integrations/opencode.md)
- 快照 / 克隆 / 回滚：[`docs/zh/guide/snapshot-rollback-clone.md`](../../docs/zh/guide/snapshot-rollback-clone.md)
- 网络 / 出网策略示例：[`examples/network-policy`](../network-policy)
- OpenCode：<https://www.npmjs.com/package/opencode-ai>
- CubeEgress 密钥保险柜：[`docs/zh/guide/security-proxy.md`](../../docs/zh/guide/security-proxy.md)
