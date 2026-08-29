# CoreNovaLaunch 验证子工程设计方案（Repo C · CoreNovaLaunchVerify）

> 版本：v2.0 ｜ 日期：2026-08-27 ｜ 状态：工程化整改定稿（对应独立仓库 `CoreNovaLaunchVerify`）
> 范围：本子工程 = 独立仓库 Repo C。本文补全"验证 → 门禁 → 前端发布"闭环，并**严格区分三层**：Application Verification / Platform Verification / Publish。
> 跨仓联动见 [`repo-structure.md`](./repo-structure.md)；契约见 [`contracts/`](./contracts/)。

## 0. 结论速览

- 验证分两层：**Application Verification**（默认，GitHub Actions，无 AWS）与 **Platform Verification / AWS Golden Verification**（低频，有 AWS 成本）。
- 二者绝不能混为一谈：**GitHub 验证应用行为；AWS Golden 验证平台与部署链路。**
- Publish 是独立阶段，由九项 checks 全过驱动；失败绝不碰 `current.json`。

## 1. 范围：本子工程 = 独立仓库 `CoreNovaLaunchVerify`（Repo C）

- 持有 `apps/`（应用注册，App Schema 唯一事实源）、CFN 模板、验证脚本、产 Verification Manifest、写 R2。
- 通过 `repository_dispatch`(PAT) 通知 Repo A 重建前端（前端从 R2 拉数据）。
- 通过 SSM 读 Repo B 的 base AMI，**不自行跑 Packer**。
- 平台变更时跑 AWS Golden Verification，产出 Platform Contract 供 Application Verification 复用。

## 2. 三层职责边界（核心）

| 层 | 名称 | 频率 | AWS 成本 | 验证对象 | 产物 |
|----|------|------|---------|---------|------|
| L1 | **Application Verification** | 高 | 无（默认） | 应用行为：compose/容器/health/API/UI/Playwright/测试 | Verification Manifest（current/versions） |
| L2 | **Platform Verification**（AWS Golden） | 低 | 有 | 平台链路：AMI/CFN/cfn-init/Docker/Nginx/SSM/CloudWatch/EBS/SG/IAM/网络 | Platform Contract |
| L3 | **Publish** | 跟随 L1 | 无 | 门禁：九项 checks 全过 → 写 R2 + dispatch | `current.json` 更新 + 网站重建 |

## 3. 总体流程

```
monitor-versions.yml (每 6h)
   └─ 发现新版本 → application-verify.yml
application-verify.yml
   ├─ RESOLVED: 解析 app_version / 精确 image tag / digest / 引用有效 Platform Contract（并检测公开 AMI 漂移）
   ├─ VERIFYING: docker compose up (runner 内) + 就绪探测 + 版本断言 + 预写测试 + Playwright 打 localhost
   ├─ VERIFIED: 生成 Verification Manifest（6 项本地 checks 全 true）
   └─ PUBLISHING: 两阶段提交 → versions 占位 → 截图/报告 → HEAD 探测 → 重写最终态 → current.json + index.json
        → repository_dispatch(verified-update) → Repo A 构建 Vite+React 站点 → Cloudflare Pages
   └─ FAILED: 分类 → RETRY / FIX_PR / MANUAL_REQUIRED（台账 = GitHub issue，见 workflow-state-machine.md §7）

golden-verify.yml（平台变更触发；引导期用公开 AMI）
   ├─ RESOLVED: 解析 base_ami_source 对应入口 → 固定 ami_id
   ├─ DEPLOYING → DEPLOYED: canary stack (CFN + EC2 + cfn-init 装 Docker/Nginx + cfn-signal)
   ├─ VERIFYING: 平台探针（Docker/Nginx/SSM/CloudWatch/EBS/SG/网络）
   ├─ VERIFIED → PUBLISHING: 写 Platform Contract(status=valid) → 供后续 Application Verification 引用
```

## 4. Application Verification 正式流程（默认无 AWS）

```
1.  Resolve version              # 解析 app_version（来源 source.version_strategy）
2.  Resolve Docker image         # deploy.image_tag_template + app_version → **精确 tag**（禁止移动 tag）
3.  Resolve Docker digest        # 注册表解析 sha256:...（linux/amd64 单平台），不可变，写入 Manifest
4.  Prepare test environment     # 注入 CORENOVA_APP_IMAGE(tag@digest) / CORENOVA_HOST_PORT / CORENOVA_APP_URL / CORENOVA_DATA_DIR
5.  docker compose up            # runner 内起容器（bind mount 到本次独占数据目录）
6.  Wait for readiness           # health_check.startup_timeout_seconds 内就绪
7.  Health check                 # endpoint/expected_status/method/retries
7b. Version assertion            # health_check.version_assertion：容器自报版本 == app_version
8.  Run predefined tests         # apps/{app}/tests/**（优先预写，缺省才 AI 生成）
9.  Run Playwright               # 截图关键场景
10. Capture screenshots          # 存 workflow artifact + 待传 R2
11. Produce report               # reports/{verification_id}.html
12. Produce Verification Manifest# verification-manifest.md schema
13. Two-phase commit             # versions 占位 → 上传截图/报告 → HEAD 探测 → 重写最终态 → current.json + index.json
14. Dispatch                     # 仅九项 checks 全过 → repository_dispatch(verified-update) → Repo A（见 §9.1）
```

### 4.1 版本 ↔ 镜像三层绑定（本流程的立身之本）

```
app_version ──① image_tag_template 渲染──▶ 精确 tag ──② 注册表解析──▶ container.digest
                                                                    │
                                       ③（可选但强烈推荐）version_assertion 实测通过 ◀──
```

- ① 无移动 tag（`ghost:5-alpine` 之类）——否则 `app_version` 只是未证明的声明（规则见 [`contracts/app-schema.md`](./contracts/app-schema.md) §3.1）。
- ② 实际启动的镜像 = `精确 tag@digest`，compose 只用注入变量，杜绝"改 yaml 没改 compose"。
- ③ 运行期由应用自己回答"我是哪个版本"（§3.2 五种 kind），把版本关系从"靠 tag 命名约定"升级为"靠被测事实"。

全过程默认：**NO EC2 / NO CloudFormation deployment / NO AWS infrastructure cost**。

## 5. AWS Golden Verification 正式流程（平台层）

```
1.  Resolve Base AMI            # 按 base_ami_source 解析一次 → 固定 ami_id（见下）
2.  Validate CloudFormation     # validate-template + change-set（no-execute）
3.  Create / update canary stack# corenova-canary
4.  EC2 launch
5.  Wait for cfn-init           # 公开 AMI 模式：cfn-init 现装 Docker/Nginx/CloudWatch（自建 AMI 模式已烤进镜像）
6.  Wait for cfn-signal
7.  Verify Docker runtime       # 实测 docker version（公开模式下这是首次证明运行时可用性）
8.  Verify Nginx                # 实测 nginx -t + 反代到本机端口
9.  Verify SSM
10. Verify CloudWatch
11. Verify EBS
12. Verify Security Group / network
13. Optional application smoke test
14. Produce Platform Verification Manifest   # platform-contract.md schema
15. Mark platform version as verified        # status=valid + 记录 base_ami_source / source_* / reverify_interval_days
16. Cleanup canary resources if configured   # 默认保留或清理
```

**`Resolve Base AMI` 的两条入口（同一"只解析一次"规则）：**

| `base_ami_source` | 解析入口 | 阶段 |
|-------------------|---------|------|
| `public` | AWS 公共 SSM 参数（如 `/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id`），无镜像软件费 | **引导期（当前）** |
| `custom` | Repo B 写的 `/corenova/ami/base/latest` | 自建/收费 AMI 就绪后 |

公开模式的额外义务（AMI 内容会被厂商滚动替换）：契约必须记 `source_ami_name` / `source_ami_account` / `ami_resolved_at`，`reverify_interval_days ≤ 30`，且 Application Verification 的 `RESOLVED` 阶段要比对"公共参数现值 vs 契约 `ami_id`"以检测漂移。详见 [`contracts/platform-contract.md`](./contracts/platform-contract.md) §2.1。

它不是常规 application-version verification，仅在 architecture.md §4 的 9 类情况触发。

## 6. 两层验证能力对照（明确区分，消除"GitHub 能验证 EC2"歧义）

| 验证项 | Application Verification（GH runner） | Platform Verification（真实 AWS） |
|--------|--------------------------------------|-----------------------------------|
| 应用容器行为 | ✅ 完全 | （smoke 可选） |
| compose / 端口映射 | ✅ 完全（同份文件） | — |
| CFN 模板语法 | （仅 Golden 做） | ✅ validate-template |
| CFN 参数/依赖/权限 | — | ✅ change-set |
| AMI 存在/可启动 | — | ✅ canary EC2 |
| cfn-init 正确 | — | ✅ canary |
| Nginx/TLS/ALB/SG/网络 | — | ✅ canary |
| SSM/CloudWatch | — | ✅ canary |

**结论**：GH 验证覆盖"应用能不能跑"；平台正确性靠 Golden 兜底。组合形成完整可信链。**不声称 GH 验证能担保 EC2 运行。**

## 7. Retry 分类（禁止统一重试）

| 分类 | 示例 | 自动重试 | 流转 |
|------|------|---------|------|
| `TRANSIENT` | 网络超时、Docker pull 超时、GitHub API 失败、AWS 限流 | ✅（≤3 次退避） | RETRY |
| `APPLICATION` | 容器启动失败、迁移失败、无效 app 配置 | ❌ | FIX_PR / MANUAL |
| `TEST` | Playwright 断言失败、selector 变化 | ❌ | FIX_PR |
| `INFRASTRUCTURE` | CFN 失败、AMI 失败、cfn-init 失败、Nginx 失败 | ❌ | MANUAL_REQUIRED |
| `MANUAL_REQUIRED` | 未知失败、安全敏感变更、AI 置信度不足 | ❌ | MANUAL_REQUIRED |

详见 [`contracts/workflow-state-machine.md`](./contracts/workflow-state-machine.md) §4。

## 8. AI 辅助修复白名单（人工发起、离线、走 PR）

测试脚本**预先写好**；Actions 只跑它们。失败时流水线**不连 AI**，只产出交接包
（失败台账 + HTML 报告 + `analyze_failure.py` 规则诊断），由**人工在流水线外**用 AI 修改白名单内文件再开 PR。
完整状态流转与反模式见 [`contracts/workflow-state-machine.md`](./contracts/workflow-state-machine.md) §6。

- 默认允许：`apps/{app}/tests/**`
- 视设计允许：`apps/{app}/*.yaml`（仅应用配置）
- **禁止**：`.github/workflows/**`、`templates/cloudformation/**`、`packer/**`、`infra/**`、IAM、Security Group、networking、production 部署逻辑。

修复必须走：[离线] 人+AI 改白名单内文件 → Create PR → Run CI（重跑预写测试）→ Human review → Merge → Re-verify。**不直接改 main。**
review 必须核对断言仍覆盖原意图——只靠放宽/删除断言变绿的"修复"是 TEST 回归，拒绝合并。

## 9. Publish Gate（完整条件 + 两阶段提交）

九项 `checks.*` 全 `true` 才 `PUBLISHED` 并触发 `repository_dispatch(verified-update)`：

```
compose_started
container_healthy
health_check_passed
tests_passed
screenshots_generated
screenshots_uploaded
report_uploaded
verification_manifest_uploaded
required_platform_contract_valid
```

### 9.1 三项"上传类" check 的循环依赖（必须按序解决）

`screenshots_uploaded` / `report_uploaded` / `verification_manifest_uploaded` 描述的是上传的**结果**，不可能在上传前为 `true`。因此门禁分两段执行（权威定义见 [`contracts/verification-manifest.md`](./contracts/verification-manifest.md) §6）：

```
P0  前置门禁：6 项本地 checks 全 true（compose_started / container_healthy /
    health_check_passed / tests_passed / screenshots_generated /
    required_platform_contract_valid）
    任一 false → FAILED，PUBLISHING 完全不开始，R2 零写入
P1  占位写 versions/{app_version}.json（三项上传 check = false）
P2  上传截图 → screenshots/{app}/{app_version}/{slug}.png；上传 report → reports/{vid}.html
P3  逐项 HEAD 探测对象可读 → 得出 screenshots_uploaded / report_uploaded 真值
P4  用 P3 结果重写 versions/{app_version}.json（最终态九项全 true）
P5  写 current.json + 更新 verified/index.json   ← 唯一提交点
```

- **`current.json` 存在 = 九项全真**；`versions/` 里的占位记录对网站不可见（前端按 §2.2 过滤）。
- P1–P4 任一步失败 → 不写 `current.json`、不发 dispatch，官网继续显示旧版本（无损）。
- 只有 `TRANSIENT`（网络/限流/探测抖动）允许在 P3/P4 内退避重试 ≤3 次；其余分类按 §7 流转。

## 10. 工作流清单（Repo C）

| 工作流 | 触发 | 说明 |
|--------|------|------|
| `monitor-versions.yml` | 定时（每 6h） | 发现新版本 → application-verify |
| `application-verify.yml` | 版本更新 / 手动 | §4 流程，默认无 AWS |
| `golden-verify.yml` | 平台变更 / 手动 / 计划 | §5 流程，AWS Golden |
| `publish-site.yml` | verify 通过后 | dispatch → Repo A |
| `reverify-failed.yml` | 定时（每天） | 重试 `TRANSIENT`/待处理失败 |

Concurrency（每个 workflow）：

```yaml
concurrency:
  group: verify-${{ inputs.app_name }}
  cancel-in-progress: false
```

## 11. 反模式（本次消除的冲突）

- ❌ 把 Application Verification 写成"部署到 EC2 再验证"（产生 AWS 费用、混淆两层）。
- ❌ 声称"GitHub 验证保证 EC2 正常运行"。
- ❌ 只写 `pytest exit 0` 就发布（缺少九项 checks）。
- ❌ AI 为让测试过而改 CFN/IAM/SG。
- ❌ 旧版本覆盖新版本 `current.json`。
- ❌ 所有失败统一 `RETRY`。
