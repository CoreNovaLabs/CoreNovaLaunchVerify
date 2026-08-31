"""one-click 单栈模板的合并约束（scripts/verify/build_user_template.py）。

回归：2026-08-31 线上事故 -- 合并模板保留了 network.yaml 的跨栈 Export
（`${StackPrefix}-network-*`，StackPrefix 默认 corenova），与用户账号里既有的
corenova-network 栈导出同名，CREATE 即回滚
（"Export with name corenova-network-VpcId is already exported by stack corenova-network"）。
单栈模板自包含：任何 Export / Fn::ImportValue 都不允许出现。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify" / "build_user_template.py"


def build(tmp_path: pathlib.Path) -> dict:
    out = tmp_path / "one-click.template.yaml"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return yaml.safe_load(out.read_text(encoding="utf-8"))


def test_merged_template_has_no_cross_stack_exports(tmp_path):
    tpl = build(tmp_path)
    assert tpl.get("Outputs"), "单栈模板仍应保留 Outputs 的 Value（控制台展示用）"
    for key, o in tpl["Outputs"].items():
        assert "Export" not in o, f"Output {key!r} 仍带 Export 块：{o.get('Export')}"


def test_merged_template_is_self_contained(tmp_path):
    """脚本自身的 rewire 自检已覆盖，这里从产物侧再验一次：无 ImportValue、无旧网络栈参数。"""
    out = tmp_path / "one-click.template.yaml"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = out.read_text(encoding="utf-8")
    assert "Fn::ImportValue" not in text
    assert "Ref: SubnetId" not in text
    assert "Ref: SecurityGroupId" not in text
    assert "NetworkStackName" not in text
