# CoreNovaLaunchVerify（Repo C）

应用注册 + Application Verification + Publish Gate + 网站事实源产出。
架构与契约见 umbrella 仓库 `../docs/`（`docs/contracts/` 优先级最高，本仓 `contracts/` 是它的镜像副本）。

## 这个仓库负责什么

| 做 | 不做 |
|----|------|
| `apps/*.yaml` 应用注册（App Schema 唯一事实源） | 构建 AMI（归 Repo B；引导期直接引用公开 AMI） |
| Application Verification：compose → 就绪 → 版本断言 → 预写测试 → Playwright 截图 | 部署到 EC2 验证应用（应用验证零 AWS 资源、零 AWS 费用） |
| Publish Gate 两阶段提交，写 `verified/{index,current,versions/*}.json` + 截图 + 报告 | 让未通过门禁的数据进网站事实源 |
| 按需跑 AWS Golden Verification 产出 Platform Contract | 把 `ami_id`/`region` 写进 app schema |
| `repository_dispatch(verified-update)` 触发 Repo A 重建 | 直接改 Repo A 的代码或数据 |

## 本地跑一次真实验证

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium

# 1) 契约校验（不碰 Docker/AWS/网络）
.venv/bin/python scripts/verify/validate_app_schema.py --all

# 2) 只解析不验证：看 app_version 与不可变 digest
GITHUB_TOKEN=$(gh auth token) .venv/bin/python scripts/verify/resolve_version.py --app ghost
GITHUB_TOKEN=$(gh auth token) .venv/bin/python scripts/verify/resolve_image.py --app ghost

# 3) 完整验证（需要本机 Docker 可用）。--no-publish 表示只到 VERIFIED，不动网站事实源
GITHUB_TOKEN=$(gh auth token) .venv/bin/python \
  scripts/verify/run_application_verify.py --app ghost --no-publish --skip-ami-drift

# 4) 九项 checks 全过才写 current.json（引导期后端 = 本地 data/）
GITHUB_TOKEN=$(gh auth token) .venv/bin/python \
  scripts/verify/run_application_verify.py --app ghost
```

产物落在 `data/`：`verified/`、`screenshots/`、`reports/`、`runs/{verification_id}/`（含 `state.json` 与
HTML 报告）。`data/` 不进 Git——它是引导期与 R2 互斥的临时后端（`docs/repo-structure.md` §4.2.1）。

无法直连 Docker Hub 的网络（如本机）用镜像站前缀，只影响拉取路径、不改 Manifest 里的镜像身份：

```bash
CORENOVA_REGISTRY_MIRROR=docker.m.daocloud.io .venv/bin/python scripts/verify/run_application_verify.py --app ghost
```

验证器与 Docker daemon 不同机时（自托管 runner、容器内跑验证）用 `CORENOVA_PROBE_HOST=host.docker.internal`。

## 平台契约（`required_platform_contract_valid` 的依据）

```bash
.venv/bin/python scripts/verify/golden_verify.py --check      # 离线静态检查（CFN 函数白名单/SG/端口/硬编码）
.venv/bin/python scripts/verify/golden_verify.py --dry-run    # 打印 16 步计划 + 契约预览，零 AWS 调用
.venv/bin/python scripts/verify/golden_verify.py              # 真跑：创建 canary → 11 项探针 → 写契约 → 清理
```

引导期 `config/platform.yaml` 的 `base_ami_source: public` 表示用厂商公开 AMI（无镜像软件费），
Docker/Nginx 由 cfn-init 现装；切自建/收费 AMI 只改这一个字段与 SSM 参数名，契约其余不变
（`docs/contracts/platform-contract.md` §2.1）。公开 AMI 会被滚动替换，因此复验周期硬性 ≤30 天。

## 接入新应用

1. 写 `apps/{name}.yaml`（字段与默认值见 `contracts/app-schema.md` §1/§2）。
2. 写 `apps/{name}/docker-compose.yml`：**只允许**引用 `CORENOVA_APP_IMAGE` / `CORENOVA_HOST_PORT` /
   `CORENOVA_CONTAINER_PORT` / `CORENOVA_APP_URL` / `CORENOVA_DATA_DIR`，不得出现镜像、端口、URL 字面量。
3. 写 `apps/{name}/tests/`（pytest + Playwright）。断言只写**实测成立的事实**；不确定的行为宁可不测并写明原因。
4. `deploy.image_tag_template` 必须能用版本号渲染出**精确 tag**（禁止 `:latest` / `ghost:5-alpine` 这类移动 tag），
   并尽量配 `health_check.version_assertion` 让应用自己证明版本。
5. `tests.scenarios[].slug` 必须是 ASCII（它就是截图的对象文件名），并与 `website.screenshots_order` 一致。
6. 跑 `validate_app_schema.py --app {name}`，再跑第 3 步的验证命令。

## CI

`.github/workflows/`：`monitor-versions`（每 6h 发现新版本并按 app 扇出）、`application-verify`
（app 级并发、`app_name` 空值即失败）、`golden-verify`（平台变更/手动/每月复验）、`publish-site`
（→ Repo A dispatch）、`reverify-failed`（只重试 TRANSIENT，台账见 `contracts/workflow-state-machine.md` §7）。

Secrets 见 `docs/repo-structure.md` §6。本地自测：`.venv/bin/python -m pytest tests -q`。
