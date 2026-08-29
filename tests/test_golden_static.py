"""CFN 模板离线静态检查的回归用例。

这三类缺陷都是"validate-template 通过、真实建栈才发现"或"cfn-init 静空跑"的类型，
只能靠静态规则兜住；每一条都对应一次真实的线上失败。
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from corenova import golden

FIXTURES = Path(__file__).resolve().parents[1] / "templates" / "cloudformation" / "fixed"


def _instance_tpl(init: dict) -> dict:
    return {"Resources": {"Instance": {"Type": "AWS::EC2::Instance",
                                       "Metadata": {"AWS::CloudFormation::Init": init}}}}


def test_config_set_key_is_rejected():
    tpl = _instance_tpl({"config-set": {"default": ["a"]}, "config": {"a": {"files": {}}}})
    errs = golden._cfn_init_errors("app.yaml", tpl)
    assert any("非法键" in e for e in errs), errs


def test_missing_configsets_is_rejected():
    errs = golden._cfn_init_errors("app.yaml", _instance_tpl({"Comment": "x"}))
    assert any("缺少 configSets" in e for e in errs), errs


def test_dangling_configset_reference_is_rejected():
    tpl = _instance_tpl({"configSets": {"default": ["nope"]}, "present": {"files": {}}})
    errs = golden._cfn_init_errors("app.yaml", tpl)
    assert any("不存在的配置 'nope'" in e for e in errs), errs


def test_correct_init_shape_passes():
    tpl = _instance_tpl({"configSets": {"default": ["a"]}, "a": {"files": {}}})
    assert golden._cfn_init_errors("app.yaml", tpl) == []


def test_unknown_cfn_function_is_rejected():
    tpl = {"Resources": {"W": {"Type": "AWS::CloudFormation::WaitCondition",
                              "Properties": {"Timeout": {"Fn::MultiplyInt": [1, 60]}}}}}
    errs = golden._function_errors("app.yaml", tpl)
    assert any("Fn::MultiplyInt" in e for e in errs), errs


def test_shipped_templates_pass_static_rules():
    for name in ("network.yaml", "app.yaml", "canary.yaml"):
        tpl = yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))
        assert golden._function_errors(name, tpl) == []
        assert golden._structure_errors(name, tpl) == []


def test_real_init_metadata_is_valid_and_assets_inlined():
    tpl = yaml.safe_load((FIXTURES / "app.yaml").read_text(encoding="utf-8"))
    init = tpl["Resources"]["Instance"]["Metadata"]["AWS::CloudFormation::Init"]
    assert "configSets" in init and "config" not in init and "config-set" not in init
    assert "default" in init["configSets"]


def test_inlined_assets_roundtrip(cfg=None):
    from corenova.config import Config

    c = cfg or Config.load()
    inlined = golden.inlined_assets(c, "app.yaml")
    assert set(inlined) >= {"00-packages-and-docker-runtime.sh", "10-nginx-base.sh",
                            "40-ready-and-signal.sh"}
    assert golden.asset_drift(c) == []
