#!/usr/bin/env python3
"""新应用脚手架生成器：产出三件套骨架 + 事实核对单（不发明任何事实）。

用法：
    python scripts/dev/new_app.py --name demo --repo owner/demo --image owner/demo \\
        --port 8080 --category productivity [--tag-style plain|v]

设计原则（contracts/app-schema.md + uptime-kuma 接入演练的固化）：
- 生成器只填「机器可推导」字段（name/路径/端口/regions/size 等）；
- 凡需要实测的（健康端点、版本断言、数据卷）与人工双语文案，一律留显式 TODO，
  由校验器以违规形式强制补齐——生成后立即打印剩余违规清单；
- 打印的「事实核对单」就是接入演练的核实路径，已代入本次入参。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from corenova import appspec, profiles  # noqa: E402
from corenova.config import Config  # noqa: E402

# 官网当前实际渲染的分类（website/src/data/categories.ts）。其它枚举值合法，
# 但没有分类页/筛选项（见官网审计结论），接入时需要人工权衡。
WEBSITE_CATEGORIES = {"cms", "ai", "media", "devops", "productivity"}

SPEC_TEMPLATE = '''\
# CoreNova Launch · 应用注册（App Schema 唯一事实源）
# 契约：contracts/app-schema.md（校验规则见 §5，共 18 条）
# 由 scripts/dev/new_app.py 生成。所有 TODO 必须在上线前用**实测事实**填掉
# （生成时打印过"事实核对单"）；校验器会把每一处未填项报成违规。

app:
  name: "{name}"
  category: "{category}"
  app_type: "{app_type}"
  icon: "/icons/{name}.svg"   # Repo A 静态资产，需人工预置（缺失时官网回退字母头像）
  i18n:
    en:
      display_name: ""   # TODO 规则2：双语必填
      description: ""    # TODO 规则2：一句话描述
    zh:
      display_name: ""   # TODO 规则2
      description: ""    # TODO 规则2

source:
  repo: "{repo}"
  version_strategy: "release_tag"
  release_filter:
    prerelease: false
    draft: false

deploy:
  docker_image: "{image}"
  image_tag_template: "{image}:{{{tag_var}}}"   # TODO 核对单1/2：上游 release tag 必须能渲染出精确镜像 tag
  container_port: {port}
  compose_file: "apps/{name}/docker-compose.yml"
  # extra_environment: []   # 可选：one-click 模板注入的 KEY=VALUE；含敏感词会被拒绝（规则16）

health_check:
  # TODO 核对单3：实测探针端点。urllib 跟随重定向：若首访 302 到 200 页面，
  # 直接打 / 即可（见 apps/uptime-kuma.yaml 的注释）；404 会提前终止探测。
  endpoint: "/"
  expected_status: 200
  method: "GET"
  timeout_seconds: 5
  retries: 40
  interval_seconds: 3
  startup_timeout_seconds: 180
  # TODO 核对单4（规则12，强烈建议配置）：实测后从五种 kind 选一
  #   env:            镜像 config 是否带版本 env（docker inspect Env）
  #   label:          镜像是否有 OCI label
  #   header:         健康探测响应头是否含版本
  #   api_json_path:  有无免鉴权 API 可取版本（path + json_pointer）
  #   exec_command:   容器内执行命令（如读 package.json / --version）

tests:
  predefined_dir: "apps/{name}/tests"
  scenarios:
    - slug: "home"      # TODO ASCII slug（即截图文件名）；多场景自行追加
      url: "/"          # TODO 核对单3：实测确定截图场景
      caption:
        en: ""          # TODO 规则8：双语说明必填
        zh: ""

deployment:
  size: "small"
  documentation_url: ""   # TODO 官方文档地址
  regions: ["us-east-1"]  # v1 单区域（规则14）
  # TODO 若应用有后台，按规则17 填 post_deploy（只写"去哪/怎么获取"，凭据不进契约）：
  # post_deploy:
  #   admin_path: "/"
  #   admin_setup:
  #     en: "..."
  #     zh: "..."
  #   notes:
  #     - {{ en: "...", zh: "..." }}
  # TODO 核对单8（规则18，建议）：人工核对月成本后填（价格是注册事实，前端不算）
  # cost_estimate:
  #   monthly_usd: 18
  #   note:
  #     en: "t3.small + 30 GB gp3, us-east-1 on-demand."
  #     zh: "t3.small + 30GB gp3，us-east-1 按需计费。"
  # data_path: "/data"   # TODO 核对单9（规则19）：compose 文件的容器挂载目标路径

website:
  featured: false
  screenshots_order: ["home"]   # 必须与 scenarios slug 集合一致（规则8）
  tags: []                      # TODO 必填非空
  features: []                  # TODO 规则13：双语亮点列表（建议 2-3 条）
'''

COMPOSE_TEMPLATE = '''\
# {name} · CoreNova 验证用 compose（scripts/dev/new_app.py 生成）
#
# 单一事实源约束（contracts/app-schema.md §0）：
#   - image 只用 ${{CORENOVA_APP_IMAGE}}（= 精确 tag@digest，由验证器注入）
#   - 端口只用 ${{CORENOVA_HOST_PORT}}:${{CORENOVA_CONTAINER_PORT}}
#   - 数据挂载到本次验证独占的临时目录 ${{CORENOVA_DATA_DIR}}，跑完即弃
services:
  {name}:
    image: ${{CORENOVA_APP_IMAGE}}
    restart: "no"
    ports:
      - "${{CORENOVA_HOST_PORT}}:${{CORENOVA_CONTAINER_PORT}}"
    volumes:
      - ${{CORENOVA_DATA_DIR}}:/TODO-app-data-dir   # TODO 核对单5：实测数据目录；确无状态则删除本行
'''

CONFTEST_TEMPLATE = '''\
"""{name} 预写测试的共用夹具（scripts/dev/new_app.py 生成）。

容器是每次验证从零启动、跑完销毁的一次性环境。
TODO：按实测补充夹具（参照 apps/uptime-kuma/tests/conftest.py）。
"""

from __future__ import annotations

import os

import pytest

BASE_URL = os.environ.get("CORENOVA_APP_URL", "http://localhost:{port}")


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def browser_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_context(viewport={{"width": 1440, "height": 900}}).new_page()
        page.set_default_timeout(60_000)
        try:
            yield page
        finally:
            browser.close()
'''

TEST_SMOKE_TEMPLATE = '''\
"""{name} 冒烟测试骨架（scripts/dev/new_app.py 生成）。

TODO：替换为在真容器内实测得到的事实——断言只写实测成立的事实；
不确定的行为宁可少测并写明原因（参照 apps/uptime-kuma/tests/test_home.py）。
"""

from __future__ import annotations


def test_root_answers(base_url):
    import requests

    r = requests.get(base_url + "/", timeout=20, allow_redirects=True)
    # TODO 实测后收窄：具体状态码、重定向落点、标题/关键标记
    assert r.status_code < 500, f"/ 返回 {{r.status_code}}"
'''

SCENARIO_SETUP_TEMPLATE = '''\
"""截图前置钩子：若场景需要前置状态（如登录态），在此实现 prepare()。"""

from __future__ import annotations


def prepare(page, slug: str) -> None:
    return None
'''


def _fail(msg: str) -> int:
    print(f"::error::{msg}", file=sys.stderr)
    return 2


def _check_args(args: argparse.Namespace) -> str | None:
    """返回错误信息；None = 通过。校验器/契约能挡的，这里提前挡，减少往返。"""
    import re

    if not appspec.NAME_RE.match(args.name):
        return f"--name {args.name!r} 不匹配 ^[a-z0-9-]+$（app-schema 规则1）"
    if not re.match(r"^[^/\s]+/[^/\s]+$", args.repo):
        return f"--repo {args.repo!r} 必须是 owner/name"
    if ":" in args.image:
        return f"--image {args.image!r} 必须是镜像基名（不含 :tag；tag 由 image_tag_template 渲染）"
    if not (1 <= args.port <= 65535):
        return f"--port {args.port} 超出 1-65535"
    if args.app_type not in profiles.TYPES:
        return f"--app-type {args.app_type!r} 不在 {sorted(profiles.TYPES)} 内（app-profiles）"
    if args.category not in profiles.CATEGORIES:
        return f"--category {args.category!r} 不在 {profiles.CATEGORIES} 内"
    return None


def generate(args: argparse.Namespace, root: pathlib.Path) -> list[pathlib.Path]:
    tag_var = "version" if args.tag_style == "plain" else "version_no_v"
    written: list[pathlib.Path] = []

    def put(rel: str, text: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        written.append(p)

    put(f"apps/{args.name}.yaml", SPEC_TEMPLATE.format(
        name=args.name, category=args.category, app_type=args.app_type,
        repo=args.repo, image=args.image, port=args.port, tag_var=tag_var,
    ))
    put(f"apps/{args.name}/docker-compose.yml", COMPOSE_TEMPLATE.format(name=args.name))
    put(f"apps/{args.name}/tests/conftest.py", CONFTEST_TEMPLATE.format(name=args.name, port=args.port))
    put(f"apps/{args.name}/tests/test_smoke.py", TEST_SMOKE_TEMPLATE.format(name=args.name))
    put(f"apps/{args.name}/tests/scenario_setup.py", SCENARIO_SETUP_TEMPLATE)
    return written


def print_checklist(args: argparse.Namespace) -> None:
    print(f"""
═══ 事实核对单（每个 TODO 都必须实测确认，不要信记忆和文档）═══
1) release tag 格式（决定 version_strategy / image_tag_template 是否成立）：
   gh api /repos/{args.repo}/releases/latest --jq '.tag_name,.prerelease'
   → 带前缀的 tag（如 n8n@1.2.3）无法被当前版本策略解析（_SEMVER 锚定 ^v?\\d+），需换应用或提契约变更。
2) 镜像 tag 存在且与 tag 对应：
   docker manifest inspect {args.image}:<version>
3) 健康端点（真容器探测，别猜）：
   docker run -d --name cn-probe -p 31999:{args.port} {args.image}:<version>
   curl -sIL http://localhost:31999/
   → 记录重定向链与最终状态码；顺带找其它免鉴权端点。
4) 版本可观测性（选 version_assertion 的 kind）：
   docker inspect cn-probe --format '{{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}}' | grep -i version
   docker exec cn-probe sh -c '<--version 命令或读版本文件>'
5) 数据卷与运行用户（决定 compose volumes 与权限）：
   docker exec cn-probe id && docker exec cn-probe sh -c 'ls -la <疑似数据目录>'
6) 填完 TODO 后：
   .venv/bin/python scripts/verify/validate_app_schema.py --app {args.name}
   GITHUB_TOKEN=$(gh auth token) .venv/bin/python scripts/verify/run_application_verify.py --app {args.name}
7) 官网图标（跨仓，人工）：把 {args.name}.svg 放进 Website 仓 public/icons/（缺失时回退字母头像）。
8) 月成本估算（规则18，建议）：定稿 size 后按实例档×区域价格人工核对 monthly_usd
   （如 t3.small 按需 730h ≈ $15.2 + 30GB gp3 ≈ $2.4，us-east-1）。
""")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="新应用三件套脚手架（不发明事实，TODO 由校验器强制补齐）")
    ap.add_argument("--name", required=True, help="应用名（^[a-z0-9-]+$，即 apps/{name}.yaml 文件名）")
    ap.add_argument("--repo", required=True, help="上游 GitHub 仓库 owner/name")
    ap.add_argument("--image", required=True, help="Docker 镜像基名（不含 tag），如 owner/app")
    ap.add_argument("--port", required=True, type=int, help="容器内监听端口")
    ap.add_argument("--category", required=True, help=f"分类：{profiles.CATEGORIES}")
    ap.add_argument("--app-type", default="stateful_app", help=f"默认 stateful_app；{sorted(profiles.TYPES)}")
    ap.add_argument("--tag-style", choices=["plain", "v"], default="plain",
                    help="上游 tag 形态：plain=2.5.3（{version}）；v=v2.5.3（{version_no_v}）")
    ap.add_argument("--root", default="", help="仓库根（默认自动定位；测试用）")
    args = ap.parse_args(argv)

    err = _check_args(args)
    if err:
        return _fail(err)

    cfg = Config.load()
    root = pathlib.Path(args.root) if args.root else cfg.root
    if (root / "apps" / f"{args.name}.yaml").exists() or (root / "apps" / args.name).is_dir():
        return _fail(f"apps/{args.name} 已存在，拒绝覆盖")
    if args.category not in WEBSITE_CATEGORIES:
        print(f"::warning::category={args.category!r} 合法，但官网当前只渲染 {sorted(WEBSITE_CATEGORIES)}；"
              f"该分类没有落地页/筛选项，需人工权衡（见官网 categories.ts）")

    written = generate(args, root)
    print("已生成：")
    for p in written:
        print(f"  {p.relative_to(root)}")

    spec = appspec.load(args.name, root)
    errors = appspec.validate(spec, root, cfg.region)
    if errors:
        print(f"\n剩余 TODO（校验器报出 {len(errors)} 处，全部消除后才可提交）：")
        for e in errors:
            print(f"  - {e}")
    print_checklist(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
