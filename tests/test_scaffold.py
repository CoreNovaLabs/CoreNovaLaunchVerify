"""scripts/dev/new_app.py 脚手架生成器的回归测试。

核心不变量：
- 生成器只产出结构性骨架，所有内容型字段（双语/说明/标签）留空并由校验器报成违规；
- 结构型规则（3/4/8 一致性/9/14 等）在骨架上必须零违规；
- 非法入参（名字/分类/覆盖已有应用）必须被拒绝且不落任何文件。
回滚生成器的参数校验或模板纪律，这里必须立刻变红。
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

from corenova import appspec  # noqa: E402
from corenova import profiles  # noqa: E402


def _load_new_app():
    path = REPO_ROOT / "scripts" / "dev" / "new_app.py"
    spec = importlib.util.spec_from_file_location("new_app_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


na = _load_new_app()

BASE_ARGS = ["--repo", "acme/demo-app", "--image", "acme/demo-app", "--port", "8080"]


def _gen(root: pathlib.Path, name: str = "demo-app", extra: list[str] | None = None) -> int:
    argv = ["--name", name, *BASE_ARGS, "--category", "productivity", "--root", str(root)]
    return na.main(argv + (extra or []))


@pytest.fixture
def root(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "apps").mkdir()
    return tmp_path


class TestGenerate:
    def test_three_piece_set_created(self, root):
        assert _gen(root) == 0
        for rel in (
            "apps/demo-app.yaml",
            "apps/demo-app/docker-compose.yml",
            "apps/demo-app/tests/conftest.py",
            "apps/demo-app/tests/test_smoke.py",
            "apps/demo-app/tests/scenario_setup.py",
        ):
            assert (root / rel).is_file(), f"缺少 {rel}"

    def test_skeleton_only_content_violations(self, root):
        """骨架的违规必须全部是内容型（双语/说明/标签），结构型规则零违规。"""
        assert _gen(root) == 0
        spec = appspec.load("demo-app", root)
        errors = appspec.validate(spec, root, "us-east-1")
        joined = "\n".join(errors)
        assert "规则2" in joined and "规则8" in joined and "tags" in joined
        # 结构纪律：compose 变量/镜像/端口、tag 模板、区域、尺寸阶梯必须直接过关
        for rule in ("规则3", "规则4", "规则9", "规则10", "规则14"):
            assert rule not in joined, f"骨架不应触发 {rule}：{joined}"

    def test_yaml_parses_and_key_fields(self, root):
        assert _gen(root) == 0
        data = yaml.safe_load((root / "apps/demo-app.yaml").read_text(encoding="utf-8"))
        assert data["app"]["name"] == "demo-app"
        assert data["deploy"]["image_tag_template"] == "acme/demo-app:{version}"
        assert data["deploy"]["container_port"] == 8080
        assert data["deployment"]["regions"] == ["us-east-1"]

    def test_tag_style_v(self, root):
        assert _gen(root, extra=["--tag-style", "v"]) == 0
        data = yaml.safe_load((root / "apps/demo-app.yaml").read_text(encoding="utf-8"))
        assert data["deploy"]["image_tag_template"] == "acme/demo-app:{version_no_v}"

    def test_generated_tests_dir_passes_repo_discipline(self, root):
        """conftest 必须读 CORENOVA_APP_URL（否则流水线注入的 base_url 失效）。"""
        assert _gen(root) == 0
        conftest = (root / "apps/demo-app/tests/conftest.py").read_text(encoding="utf-8")
        assert "CORENOVA_APP_URL" in conftest
        compose = (root / "apps/demo-app/docker-compose.yml").read_text(encoding="utf-8")
        violations = appspec._validate_compose(compose)
        assert not violations, f"生成的 compose 违反纪律：{violations}"


class TestRejection:
    def test_invalid_name_rejected_and_nothing_written(self, root):
        assert _gen(root, name="Bad_Name") == 2
        assert list((root / "apps").iterdir()) == []

    def test_existing_app_not_overwritten(self, root):
        assert _gen(root) == 0
        before = (root / "apps/demo-app.yaml").read_text(encoding="utf-8")
        assert _gen(root) == 2
        assert (root / "apps/demo-app.yaml").read_text(encoding="utf-8") == before

    def test_unknown_category_rejected(self, root):
        argv = ["--name", "x", *BASE_ARGS, "--category", "not-exist", "--root", str(root)]
        assert na.main(argv) == 2

    def test_unknown_app_type_rejected(self, root):
        argv = ["--name", "x", *BASE_ARGS, "--category", "cms", "--app-type", "web", "--root", str(root)]
        assert na.main(argv) == 2

    def test_image_with_tag_rejected(self, root):
        argv = ["--name", "x", "--repo", "a/b", "--image", "a/b:latest",
                "--port", "80", "--category", "cms", "--root", str(root)]
        assert na.main(argv) == 2


def test_website_category_set_is_subset_of_contract():
    """官网渲染的分类必须是契约枚举的子集（否则警告逻辑失去意义）。"""
    assert na.WEBSITE_CATEGORIES <= set(profiles.CATEGORIES)
