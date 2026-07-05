---
title: OpenCode 集成指南
author: Nat-xu
date: 2026-07-05
tags:
  - integration
  - opencode
  - coding-agent
  - agent
lang: zh-CN
---

# OpenCode 集成指南

[English](../../../guide/integrations/opencode.md)

在 CubeSandbox MicroVM 内运行 [OpenCode](https://www.npmjs.com/package/opencode-ai)
（开源终端 AI 编码 Agent）。本文覆盖镜像构建、密钥注入，以及基于快照的会话持久化，
配套的可运行示例位于
[`examples/opencode-integration`](https://github.com/TencentCloud/CubeSandbox/tree/master/examples/opencode-integration)。

## 集成对象与版本

| 组件 | 版本 |
|---|---|
| OpenCode | `opencode-ai`（通过 npm 安装，如需固定版本请在 Dockerfile 中指定） |
| Node.js | 24（通过 NodeSource 安装） |
| CubeSandbox 基础镜像 | `ghcr.io/tencentcloud/cubesandbox-base:2026.16` |
| E2B SDK（宿主端驱动） | `e2b`（最新） |
| CubeSandbox 平台 | `>= 0.3.0`（pause/resume） |

## 前置条件

- 已部署 CubeSandbox，CubeAPI 可访问（`http://<node>:8080`）。
- `cubemastercli` 已在 `$PATH` 且已连通集群。
- 构建机装有 Docker，且 registry 能被 Cube 集群拉取。
- 一个 LLM provider 的 API Key。默认 OpenAI；OpenCode 支持的其他 provider
  （Anthropic、Google 等）均可通过 `--provider <name>` 指定。
- Python 3.9+（宿主端驱动脚本）。

## 为什么要把 OpenCode 放进沙箱

OpenCode 是一个会编辑文件、执行命令、安装依赖的终端 Agent。直接跑在开发机上，
Agent 的"爆炸半径"就等于你的开发环境。放进 CubeSandbox 你能拿到：

| 关注点 | CubeSandbox 提供 |
|---|---|
| **隔离** | 每个会话一个 KVM MicroVM，独立 guest kernel |
| **可复现** | 每次会话都从同一个 template 快照启动 |
| **秒起** | 冷启动 <60ms，N 路并行代价极小 |
| **长任务** | `sandbox.pause()` 对 VM + rootfs 打快照，稍后恢复 |
| **密钥卫生** | CubeEgress 在链路上注入鉴权头，VM 看不到真实密钥 |
| **出网审计** | 每次访问 LLM API 都会记入出网审计日志 |

## 接入步骤

### 1. 构建模板镜像

镜像在 `cubesandbox-base` 上叠加 Node.js 24 与 OpenCode CLI，envd 已监听
`:49983`。

```dockerfile
# examples/opencode-integration/Dockerfile（节选）
ARG CUBE_BASE_IMAGE=ghcr.io/tencentcloud/cubesandbox-base:2026.16
FROM ${CUBE_BASE_IMAGE}

ARG NODE_MAJOR=24

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git gnupg jq less procps python3 python3-pip ripgrep \
    && curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g --ignore-scripts opencode-ai@latest \
    && opencode --version \
    && npm cache clean --force \
    && rm -rf /root/.npm /var/lib/apt/lists/*

ENV OPENCODE_CONFIG_DIR=/root/.config/opencode

RUN mkdir -p /workspace "${OPENCODE_CONFIG_DIR}" \
    && printf '%s\n' \
        '{' \
        '  "provider": "openai",' \
        '  "model": "gpt-4.1"' \
        '}' \
        > "${OPENCODE_CONFIG_DIR}/opencode.json"

WORKDIR /workspace
EXPOSE 49983
```

构建并推送：

```bash
docker build --platform linux/amd64 \
  -t <your-registry>/opencode-cube:latest \
  examples/opencode-integration
docker push <your-registry>/opencode-cube:latest
```

### 2. 注册为 Cube 模板

```bash
cubemastercli tpl create-from-image \
  --image <your-registry>/opencode-cube:latest \
  --writable-layer-size 4G \
  --expose-port 49983 \
  --probe       49983 \
  --probe-path  /health

cubemastercli tpl watch --job-id <job_id>
```

任务变为 `READY` 后记下 `template_id`，后续每次 `Sandbox.create()` 都要用它。
`4G` 可写层适合中等任务；若 Agent 会安装大型工具链，提升到 `8G+`。

### 3. 配置宿主端驱动

```bash
cd examples/opencode-integration
cp .env.example .env
# 填写 E2B_API_URL、CUBE_TEMPLATE_ID 以及你的 provider key
pip install -r requirements.txt
```

| 变量 | 作用位置 | 说明 |
|---|---|---|
| `E2B_API_URL` | 本地进程 | CubeAPI 地址（`http://<node>:8080`） |
| `E2B_API_KEY` | 本地进程 | 本地开发填任意非空字符串 |
| `CUBE_TEMPLATE_ID` | `Sandbox.create(template=...)` | 来自第 2 步 |
| `OPENAI_API_KEY` | `envs=...`（逐命令注入） | OpenAI 的 provider key；Anthropic 则用 `ANTHROPIC_API_KEY` |
| `OPENCODE_PROVIDER` | OpenCode CLI `--provider` 参数 | 覆盖 `opencode.json` 中的默认 provider |

### 4. 运行时配置与 API Key 注入

OpenCode 以无交互方式调用：`--non-interactive` 表示执行完 prompt 即退出（不启动
TUI，否则会在 E2B exec 通道上挂死），配合显式 `--provider`，prompt 作为 `--prompt`
参数传入：

```python
result = sandbox.commands.run(
    "cd /workspace && opencode --non-interactive --provider openai "
    "--prompt '创建 hello.py 打印 Hello from CubeSandbox 并运行它。'",
    envs={"OPENAI_API_KEY": key},
    user="root",
    timeout=900,
)
```

`e2b` 的 `commands.run(envs=...)` 把环境放进 exec 信封，而非 VM 内的持久文件，
因此密钥只在该命令执行期间存在。

> **安全：** 本示例默认放开出网以简化初次体验。共享集群或生产环境请使用
> CubeEgress 密钥保险柜配合默认拒绝出网（参考 pi-agent 的 `network_policy.py`
> 示例）。保险柜方式在链路上把 API Key 作为 HTTP 头注入——VM 看不到真实密钥，
> 沙箱内 `printenv` 只显示占位值。

### 5. 会话持久化（pause / resume）

```bash
python resume_opencode.py --sandbox-id <run_opencode.py 输出的 id>
```

它在 SDK 层复用了[快照 / 克隆 / 回滚](../snapshot-rollback-clone.md)引擎：

- `sandbox.pause()` 对运行中的 VM（内存 + rootfs）打快照并释放算力。
- `Sandbox.connect(sandbox_id)` 恢复时，`/workspace`、OpenCode 配置目录
  （`/root/.config/opencode`）及其他文件都完好无损。

> **生命周期注意：** 用 `try/finally` 手动管理沙箱，不要用 `with Sandbox.create(...)`
> context manager。context manager 在 `__exit__` 时会 kill 沙箱，这会让 pause
> 失效。示例显式创建沙箱，只在 `finally` 里调用 `sandbox.kill()`。

```python
sandbox = Sandbox.create(template=template_id, timeout=1800)
try:
    run_turn(sandbox, prompt_1)          # 写入 /workspace/plan.md
    sandbox_id = sandbox.pause() or sandbox.sandbox_id
    sandbox = Sandbox.connect(sandbox_id)
    verify_state_survived(sandbox)       # /workspace + /root/.config/opencode 仍在
    run_turn(sandbox, prompt_2)          # 继续工作
finally:
    sandbox.kill()
```

## 使用场景与最佳实践

- **隔离开发。** 把编码 Agent 跑在沙箱内，其文件编辑与 shell 命令无法触及宿主。
- **执行 Agent 生成的代码并回收结果。** 让 Agent 写入 `/workspace`，再通过
  `sandbox.files` 或 `commands.run` 读回产物。
- **长任务断点续跑。** 用 `pause()` + `connect()` 给长时间重构打快照并稍后恢复，
  或从一个快照分叉多个任务变体。
- **把重依赖预装进模板**，而不是运行时拉取，尤其在默认拒绝出网的策略下。

## 关键代码片段

### 无交互调用 OpenCode

```python
cmd = (
    "cd /workspace && opencode --non-interactive --provider openai "
    "--prompt 'Inspect the project, run app.py, and summarize the result.'"
)
result = sandbox.commands.run(cmd, envs={"OPENAI_API_KEY": key}, user="root", timeout=900)
```

### preflight 版本检查

```python
version = sandbox.commands.run("opencode --version", timeout=60)
```

### 向沙箱写入演示项目

```python
sandbox.commands.run("""
cat > /workspace/app.py <<'EOF'
def main() -> None:
    print("hello from CubeSandbox + OpenCode")

if __name__ == "__main__":
    main()
EOF
""", user="root", timeout=60)
```

## 注意事项

- **Node.js 版本。** OpenCode 需要较新的 Node 运行时；基础镜像自带的 apt Node
  偏旧，务必通过 NodeSource 安装（Dockerfile 已如此）。
- **Agent 配置目录。** `/root/.config/opencode` 保存 OpenCode 的配置与会话状态。
  镜像里保持它不含凭证；Dockerfile 创建的最小 `opencode.json` 仅含默认 provider
  和 model。
- **直连方式的密钥留存。** 直连方式（`envs=`）下密钥仅作用于该 exec 调用，但
  OpenCode 可能把 provider 凭证缓存到其配置目录（`/root/.config/opencode/`），
  会在 `pause()` / `resume()` 后仍留在盘上。对隔离要求高时优先用 CubeEgress
  保险柜方式，密钥完全不进入 VM。
- **出网副作用。** 需要 `npm install` 或拉取 MCP 工具的任务，要放行相应 host 或
  预装进模板。
- **交互式 TTY 功能。** OpenCode 的 TUI 在 E2B 协议下不可用。请用
  `--non-interactive` 模式，多轮对话由宿主脚本驱动。
- **Provider 兼容性。** OpenCode 支持多种 LLM provider（OpenAI、Anthropic、
  Google 等）。确保为每次调用设置并传入对应的 `*_API_KEY` 环境变量。运行时可用
  `--provider <name>` 覆盖默认 provider。

## 排错

| 现象 | 可能原因 | 处理 |
|---|---|---|
| preflight 报 `opencode: command not found` | CLI 变更后未重建模板 | 重建镜像并重新注册模板 |
| provider 鉴权失败 | 密钥未传入（直连）或缺少 inject 规则（vault） | 传 `envs={...}` 或修正规则的 `sni`/`host` |
| `403 Forbidden - CubeEgress` | 默认拒绝且无匹配放行规则 | 把 LLM host（及所需其他 host）加入规则 |
| OpenCode 报 `Connection error` / TLS 失败（vault 路径） | OpenCode 基于 Node，忽略系统 CA 库，不信任 CubeEgress CA | 设置 `NODE_EXTRA_CA_CERTS` 指向含 CubeEgress CA 的系统 bundle 路径 |
| 模板创建卡在 `PULLING` | Cube 节点无法访问 registry | 推送到集群可访问的 registry，必要时提供鉴权 |
| 就绪探针超时 | 基础镜像缺少 envd | 确认 `FROM ghcr.io/tencentcloud/cubesandbox-base:2026.16` |
| `pause()` / `connect()` 报错 | 平台版本过低不支持快照 | 升级 CubeSandbox 平台 |
| OpenCode 卡死或超时 | prompt 过大或 Agent 陷入循环 | 减小 prompt 长度或降低 `--exec-timeout`；检查 stderr 获取线索 |

## 参考

- 可运行示例：[`examples/opencode-integration`](https://github.com/TencentCloud/CubeSandbox/tree/master/examples/opencode-integration)
- 自带镜像：[`docs/guide/tutorials/bring-your-own-image.md`](../tutorials/bring-your-own-image.md)
- 从镜像构建模板：[`docs/guide/tutorials/template-from-image.md`](../tutorials/template-from-image.md)
- 快照 / 克隆 / 回滚：[`docs/guide/snapshot-rollback-clone.md`](../snapshot-rollback-clone.md)
- 密钥保险柜 + 出网管控：[`docs/guide/security-proxy.md`](../security-proxy.md)
- Pi Agent `network_policy.py`（保险柜模式参考）：[`examples/pi-agent-integration/network_policy.py`](https://github.com/TencentCloud/CubeSandbox/tree/master/examples/pi-agent-integration)
- OpenCode：<https://www.npmjs.com/package/opencode-ai>
