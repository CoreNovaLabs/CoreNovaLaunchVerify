# CoreNovaLaunch 多仓库结构与联动契约

> 版本：v2.0 ｜ 日期：2026-08-27 ｜ 状态：工程化整改定稿（仅文档）
> 配套总览见 [`architecture.md`](./architecture.md)。本文定义三仓物理目录、跨仓触发、两条核心契约（SSM AMI、repository_dispatch + R2 Manifest）。
> **契约优先**：与 `contracts/` 冲突时以 contract 为准。

## 1. 物理目录布局（与三仓一致）

`CoreNovaLaunch` 为 umbrella 仓库，仅承载共享设计文档；三个子仓各自独立 Git remote。

```
CoreNovaLaunch/                            # umbrella（GitHub: CoreNovaLaunch）
├── docs/                                  # 共享设计文档（本目录 + contracts/）
│   ├── architecture.md
│   ├── repo-structure.md                  # 本文
│   ├── verify-gate-design.md
│   ├── infra-build-design.md
│   ├── website-design.md
│   ├── quick-start.md
│   └── contracts/                         # 最高优先级规范（6 份）
│
├── CoreNovaLaunchVerify/                  # Repo C（GitHub: CoreNovaLaunchVerify）
│   ├── apps/                              # 应用注册（App Schema 唯一事实源）
│   │   ├── ghost.yaml                     # 主配置（见 contracts/app-schema.md）
│   │   ├── ghost/
│   │   │   ├── docker-compose.yml         # 用 ${CORENOVA_APP_IMAGE}/${CORENOVA_HOST_PORT} 等变量
│   │   │   ├── nginx.conf                 # 反代配置（可选）
│   │   │   └── tests/{conftest.py,test_home.py,test_admin.py}   # 预写测试（pytest + Playwright）
│   │   └── n8n/ ...
│   ├── contracts/                         # umbrella contracts 的镜像副本（校验自包含，见下文）
│   ├── templates/
│   │   └── cloudformation/fixed/
│   │       ├── {network,app,canary}.yaml  # 三栈（见 platform-contract.md §9）
│   │       └── init/                      # cfn-init 资产：公开 AMI 模式下装 Docker/Nginx/CloudWatch
│   │                                      #   ← docker_runtime_revision / nginx_base_revision 取此目录 SHA
│   ├── scripts/
│   │   ├── verify/                        # 流水线核心（Python）
│   │   │   ├── validate_app_schema.py     #   app-schema §5 十五条校验
│   │   │   ├── resolve_version.py         #   RESOLVED：上游 release → app_version + release.type
│   │   │   ├── resolve_image.py           #   RESOLVED：tag 模板 → 精确 tag + digest
│   │   │   ├── run_application_verify.py  #   VERIFYING：compose→就绪→断言→测试→截图→报告
│   │   │   ├── publish.py                 #   PUBLISHING：两阶段提交（dir / r2 两后端）
│   │   │   ├── build_user_template.py     #   one-click 模板：fixed 栈 -> 单栈模板（--publish-s3 -> 公开桶 §4.4）
│   │   │   └── golden_verify.py           #   Platform Verification + 写 Platform Contract
│   │   ├── ai-test/{analyze-failure,generate-report}.py
│   │   └── monitor/{check_versions,failure_issue}.py   # 版本发现 + §7 失败台账
│   ├── data/                              # 引导期 fixtures 输出（.gitignore，非事实源）
│   │   ├── verified/  ├── platform/  ├── templates/  └── reports/
│   └── .github/workflows/
│       ├── monitor-versions.yml           # 每 6h 发现新版本
│       ├── application-verify.yml         # GitHub Application Verification（默认无 AWS）
│       ├── golden-verify.yml              # AWS Golden Verification（平台变更触发）
│       ├── publish-template.yml           # fixed 栈变化 -> one-click 模板发布公开 S3（§4.4）
│       ├── publish-site.yml               # repository_dispatch → Repo A
│       └── reverify-failed.yml            # 定时重试失败（仅 TRANSIENT）
│
├── CoreNovaLaunchWebsite/                 # Repo A（GitHub: CoreNovaLaunchWebsite）
│   ├── src/                               # Vite + React 源码
│   ├── public/                            # 静态资源 / 图标
│   ├── scripts/
│   │   └── fetch-verified.mjs             # 构建前拉 index.json → current.json → versions/*.json（dir 或 R2）
│   ├── data/                              # 构建期派生产物：verified/ + stats.json + {app}/releases.json
│   ├── wrangler.toml                      # Cloudflare Pages 配置
│   └── .github/workflows/
│       └── build-site.yml                # 监听 repository_dispatch → 拉 R2 → 构建 → Pages
│
└── CoreNovaLaunchAmi/                     # Repo B（GitHub: CoreNovaLaunchAmi）
    ├── packer/base-image.pkr.hcl
    ├── scripts/{setup-base.sh,setup-docker.sh,harden-os.sh}
    └── .github/workflows/
        └── build-ami.yml                 # 构建 → 写 SSM(/corenova/ami/base/latest) → 产出 Platform Contract
```

> **引导期（`base_ami_source=public`）Repo B 缺席不影响链路**：Repo C 直接从 AWS 公共 SSM 参数解析公开 AMI 跑 Golden Verification，Platform Contract 由 Repo C 产出（见 platform-contract.md §2.1）。Repo B 目录在切换到自建/收费 AMI 时启用。

> 网站事实源是 R2（§4）。引导期未接入 R2 时，Repo C 的 `data/` 只是**同一套形状文件的临时后端**（§4.2.1），且**不进 Git**、任一时刻与 R2 只有一个生效；接入 R2 后 `data/` 降级为审计副本，不再参与门禁。Repo A 只读当前生效后端，禁止两处择优。

**契约落地（消除"契约在哪被执行"的歧义）**：`contracts/` 物理存放于 umbrella 仓库 `CoreNovaLaunch/docs/contracts/`，是**唯一权威源**与唯一变更入口。但 `apps/*.yaml` 校验、Manifest 生成发生在 Repo C，前端字段约束发生在 Repo A——因此两仓需将契约**镜像/同步**到本仓（如 `contracts/` 或 `.corenova/contracts/`），随 umbrella 更新而同步，保证校验自包含、不依赖跨仓读取。镜像副本与 umbrella 冲突时以 umbrella 为准。

## 2. 跨仓触发矩阵

| 触发方 | 事件 | 接收方 | 机制 | 目的 |
|--------|------|--------|------|------|
| 定时 / 手动 | `workflow_dispatch` | Repo B `build-ami` | 原生 | 按计划构建 base AMI → 写 SSM → 产出 Platform Contract |
| Repo B | `repository_dispatch` (`ami-built`) | Repo C `golden-verify` | PAT | AMI 变更 → 触发 AWS Golden Verification |
| 定时（每 6h） | `workflow_dispatch` | Repo C `monitor-versions` | 原生 | 检测应用新版本 |
| Repo C `monitor-versions` | `workflow_dispatch`（同仓，`-f app_name=…`） | Repo C `application-verify` | 原生 / `gh api` | 发现新版本 → 触发该应用 Application Verification |
| Repo C | `repository_dispatch` (`verified-update`) | Repo A `build-site` | PAT | Application Verification 通过 → 触发前端重建 |
| 手动 | `workflow_dispatch` | Repo A `build-site` | 原生 | 手动重建站点 |
| 平台变更检测 | 自动 | Repo C `golden-verify` | 原生 | 见 platform-contract.md §4 |

**PAT 配置**：Repo C Secrets 存 `REPO_A_PAT`（具备 `CoreNovaLaunchWebsite` `workflow` 作用域）。PAT 持有账户需对目标仓库有 `workflow` 写权限。

## 3. 契约一：B→C（SSM AMI，latest 仅作入口）

Repo B 构建后写 SSM：

```
Name:  /corenova/ami/base/latest          # mutable pointer，Repo B 每次构建覆盖
Type:  String
Value: ami-xxxxxxxxxxxxxxxxx
Tags:  { built_by: corenovalaunch-ami, region: us-east-1, arch: x86_64 }
```

Repo C 在验证 workflow **开头**解析一次：

```bash
AMI_ID=$(aws ssm get-parameter \
  --name /corenova/ami/base/latest \
  --query 'Parameter.Value' --output text)
# AMI_ID 固定为本次 workflow 的 immutable verification input
# 禁止中途再次查询 latest
```

- 若 SSM 缺失 AMI → fail-fast + 报警（建议先触发 B 构建再继续）。
- **C 绝不自行 `packer build`**（镜像生命周期归 B）。
- Manifest / Platform Contract 记录最终 `ami_id`（不可变），不记录 `latest`。
- 详见 [`contracts/platform-contract.md`](./contracts/platform-contract.md) §3、§6。

## 4. 契约二：C→A（repository_dispatch + R2 Manifest）

### 4.1 dispatch 事件

Repo C `publish-site.yml` 向 Repo A 发：

```bash
curl -L -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $REPO_A_PAT" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/<org>/CoreNovaLaunchWebsite/dispatches \
  -d '{"event_type":"verified-update","client_payload":{"apps":["ghost"],"verification_id":"ghost-v5.75.0-20260827-001"}}'
```

`client_payload` 仅作提示；**前端实际数据以 R2 拉取为准**。

### 4.2 R2 路径与 current/versions 分离（唯一事实源）

```
r2://<bucket>/
├── verified/index.json                        # 应用清单：前端枚举 app 的唯一入口（R2 公共端点不可 ListObjects）
├── verified/{app}/current.json                # 官网当前应展示的最新 Verified 状态
├── verified/{app}/versions/{app_version}.json # 历史 Verification Record
├── screenshots/{app}/{app_version}/{slug}.png # 截图（slug = tests.scenarios[].slug，纯 ASCII）
├── reports/{verification_id}.html             # 验证报告
└── platform/platform-contract-{region}-{arch}.json   # Platform Contract
```

- `current.json` = 最新一次 `PUBLISHED` 的 Manifest 的 `website` 投影（形状见 [`contracts/deployment-contract.md`](./contracts/deployment-contract.md)）。
- `versions/{app_version}.json` = 完整 Verification Manifest（形状见 [`contracts/verification-manifest.md`](./contracts/verification-manifest.md)）。
- **截图键必须含 `app_version`**：同名场景（如 `home.png`）在不同版本间会复用文件名，不带版本会导致 CDN/浏览器缓存串图，且网站无法证明"这张图是这个版本截的"。
- **slug 必须是 ASCII**（`^[a-z0-9][a-z0-9-]*$`）：对象键非 ASCII 时 URL 编码规则在 SDK / CDN / 浏览器之间不一致，且中文文件名在部分工具链里会被规范化破坏。
- Repo A `fetch-verified.mjs` 构建流程：读 `verified/index.json` → 逐个 `GET verified/{app}/current.json` →（版本页）`GET versions/*.json`；**不读 Git 内 verified、不读 `apps/`、不猜 app 列表**。

### 4.2.1 引导期后端：本地 fixtures（与 R2 互斥）

在 R2 尚未接入时，Repo C 的发布产物可写到工作区目录（默认 `data/verified/` + `data/platform/` + `data/reports/`），由 `VERIFIED_OUTPUT_DIR` 指定；Repo A 的 `fetch-verified.mjs` 用 `VERIFIED_SOURCE=dir:<path>` 读同一份文件。

- 两者共享**同一套文件形状**（index.json / current.json / versions / screenshots / reports），接入 R2 后只换后端实现，形状与门禁不变。
- **任一时刻只允许一个后端生效**（`VERIFIED_BACKEND=dir|r2`）。默认值允许**按环境选择**：本地开发 = `dir`；任何 CI/云端构建（`CI` / `CF_PAGES*` / `CI_NAME=cloudflare_pages`，实测 Cloudflare 里 `CF_PAGES` 不一定为 `"1"`）= `r2`。**禁止的是失败回退**（"先读 R2、读不到再回退本地"）——那会让门禁依据不确定（platform-contract.md §3 同理）；按环境选定后，本次构建内不换。
- 本地 fixtures 是**开发链路产物**，不得提交进 Git 当事实源（见 §5 反模式）。

### 4.3 Verification Identity 绑定

每次 `current.json` / `versions/*.json` 必须包含 `verification_id` 及不可变输入（`app_version`、`container.digest`、`ami_id`、`config.*_revision` 等），见 verification-manifest.md。

### 4.4 one-click 模板公开分发（S3 直链 = 深链 URL 源）

官网 `Generate Template` 深链的 `templateURL` 指向 Repo C 发布的公开读 S3 直链：

```
https://<bucket>.s3.us-east-1.amazonaws.com/corenova-one-click.template.yaml
```

CloudFormation 控制台原生支持该 URL 形态，深链一点即进创建向导（应用参数拼在深链上）。约束：

- **发布链路**：`templates/cloudformation/fixed/{network,app}.yaml` 变化（或手动 dispatch）触发
  Repo C `publish-template.yml` -> `build_user_template.py --publish-s3` -> `corenova/template_publish.py`
  put 到公开桶 + **匿名 GET 探测**（非 200 / 字节不一致 = 发布失败，深链绝不指向读不到的对象）。
- **桶要求**：us-east-1、公开读（对象 ACL `public-read` 或桶策略 `Allow s3:GetObject`，put 两者
  兼容、探测统一把关）；桶内只放这一个对象。它是**附加分发渠道，不是第二个事实源后端**--
  verified JSON / 截图 / Platform Contract 仍走 dir|r2（§4.2.1），模板也不进 Manifest。
- **模板内容 app 无关**、只在 fixed 栈变化时变化 -> 不挂每次验证的 PUBLISHING
  （`application-verify` 默认无 AWS，不为模板分发多背一份凭据）。
- **Repo A 深链 URL 来源**：构建期常量（`src/lib/deploy.ts`，`VITE_ONE_CLICK_TEMPLATE_URL` 可覆盖），
  默认值必须与 Repo C 的 `TEMPLATE_S3_BUCKET` 指向同一只桶；**禁止**拼站点自身 origin
  或在 Repo A 自托管模板副本（两个分发渠道必然漂移）。

## 5. 边界与反模式

- ❌ Repo A 不得持有 `AWS_*` 或任何部署/验证密钥。
- ❌ Repo C 不得执行 `packer build`（AMI 归 B）。
- ❌ Repo A 不得直接读 `apps/`——唯一数据源是 R2 `verified/*/current.json`。
- ❌ 验证未通过（九项 checks 未全过）不得写 `current.json`、不得发 `verified-update` dispatch。
- ❌ Git 内 `verified` 不得作为网站运行时第二事实源。
- ❌ workflow 中途不得重新查询 SSM `latest`（破坏可复现）。
- ❌ Repo A 靠枚举/硬编码猜 app 列表——必须读 `verified/index.json`（§4.2）。
- ❌ 同一份事实源在 R2 与本地 `data/` 各存一份并让脚本"择优读取"（§4.2.1）。
- ❌ 在上传前把 `checks.*_uploaded` 写成 `true`，或上传后不做对象可读性探测就更新 `current.json`（见 verification-manifest.md §6）。
- ❌ 用移动 tag（`ghost:5-alpine`）充当被验证镜像却声称具体 `app_version`（见 app-schema.md §3.1）。
- ❌ 把 `github_stars` / `success_rate` 等构建期统计塞进 `current.json`（应落 Repo A 的 `data/stats.json`，见 deployment-contract.md §5.1）。
- ❌ 深链 templateURL 拼站点自身 origin、或 Repo A 自托管 `/templates/` 模板副本--分发渠道必须唯一：公开 S3 直链（§4.4）。
- ✅ 跨仓唯一耦合点：`repository_dispatch`(PAT) + SSM(AMI) + R2(verified JSON/截图/Platform Contract)。

## 6. Secrets 汇总（KEY_PAIR_NAME 已移除默认必填）

| Secret | 所在仓库 | 说明 |
|--------|---------|------|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | B、C(仅 Golden) | AWS 构建/Golden 验证 |
| `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` | A、C | Pages 部署（A）/ `wrangler` 管理 R2 对象 |
| `R2_BUCKET_NAME` | A、C | verified JSON / 截图 / Platform Contract 存储 |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | A(读)、C(写) | **R2 走 S3 兼容 API 必需的 Access Key**（`CLOUDFLARE_API_TOKEN` 不能签 S3 请求，缺这两项则上传/下载全部失败）；在 R2 → Manage R2 API Tokens 创建 |
| `R2_PUBLIC_BASE_URL` | A、C | 截图/报告的公开访问前缀（`https://pub-<hash>.r2.dev` 或自定义域）；Manifest 里的 `screenshots[].url` / `report_url` 由它拼出 |
| `TEMPLATE_S3_BUCKET` | C | one-click 模板公开读桶名（us-east-1，`publish-template.yml` 用）；深链 templateURL 直链 `https://<bucket>.s3.us-east-1.amazonaws.com/corenova-one-click.template.yaml` 的桶（§4.4） |
| `REPO_A_PAT` | C | 跨仓 `repository_dispatch` |
| `VERIFIED_BACKEND` | A、C | 可选。显式指定优先；未指定时按环境选默认——本地 `dir`、CI/云端构建 `r2`（§4.2.1）。禁止的仍是**失败回退**，不是按环境选默认 |
| `KEY_PAIR_NAME` | — | **已删除**：基础 AMI 用 SSM Session Manager，关闭 22 入站；仅在显式 `debug mode` 才允许，默认不配置 |

> 引导期（`VERIFIED_BACKEND=dir`）三项 R2 secret 与 `CLOUDFLARE_*` 均可缺省，链路本地即可跑通；接入 R2 时一次性补齐，不改代码路径（只换后端实现）。
> 网站统计 `success_rate` 由 Repo A 构建时用自带 `GITHUB_TOKEN` 读 Repo C 的 Actions runs（跨仓读需该 token 有权限，否则降级 `—`，见 deployment-contract.md §5.1），**不需要**额外 secret。

> 旧 `quick-start.md` / `architecture.md` 中 `KEY_PAIR_NAME` 为必填项，属歧义，本次统一删除。详见 platform-contract.md §8。
