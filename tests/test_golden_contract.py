"""golden.py 里"契约形状 / 漂移判定 / 探针清单"三组纯逻辑的行为钉子。

golden.py 有 1883 行，拆分只是时间问题；拆分真正的风险不是搬错代码，而是这些没人盯的
隐式约定被顺手改掉：
- CONTRACT_FIELD_ORDER 是写到 R2/dir 上的线上 JSON 字段顺序，官网与 platformref 都按它读；
- VERIFICATION_KEYS 是 platform-contract.md §2 承诺的"恰好十一个键"，多一个少一个都是违约；
- check_drift 的判定直接决定一次应用验证是 PUBLISHED 还是 FAILED/INFRASTRUCTURE；
- _probe_ec2_launched 的轮询必须在循环内重读实例状态（源码注释已明确警告过一次误判）。

这些断言与文件怎么组织无关：将来无论 golden.py 被拆成几个模块，它们都必须原样通过。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from corenova import golden, platformref
from corenova.platformref import REVISION_KEYS
from corenova.util import utcnow

# --------------------------------------------------------------------------- 测试替身


class FakeBackend:
    """只实现 check_drift 用到的 get；name 决定 write_contract 是否额外落盘。"""

    name = "fake"

    def __init__(self, payloads: dict[str, bytes] | None = None):
        self.store = dict(payloads or {})

    def get(self, key: str) -> bytes | None:
        return self.store.get(key)


def _cfg(**over):
    base = dict(
        region="us-east-1",
        architecture="x86_64",
        base_ami_source="public",
        reverify_interval_days=30,
        platform={"public_ami": {"name_pattern": "al2023-ami-*", "owner_account": "amazon"}},
        ami_ssm_parameter=lambda: "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _revisions(value: str = "rev-a") -> dict[str, str]:
    return {key: f"{value}-{key}" for key in REVISION_KEYS}


def _contract(**over) -> dict:
    doc = {
        "schema_version": golden.SCHEMA_VERSION,
        "platform_verification_id": "plat-us-east-1-x86_64-20260906-001",
        "ami_id": "ami-recorded",
        "region": "us-east-1",
        "architecture": "x86_64",
        **_revisions(),
        "verification": {key: True for key in golden.VERIFICATION_KEYS},
        "status": golden.VALID,
        "platform_verified_at": utcnow(),
        "invalidated_at": None,
        "invalidated_reason": None,
        "base_ami_source": "public",
        "reverify_interval_days": 30,
    }
    doc.update(over)
    return doc


# --------------------------------------------------------------------------- 契约形状


# 线上 JSON 的字段顺序就是契约本身（platform-contract.md §2）。下面两处硬编码是刻意的：
# build_contract 按 CONTRACT_FIELD_ORDER 生成、verification 按 VERIFICATION_KEYS 生成，
# 拿同一个常量去比同一个常量永远为真，钉不住任何"顺手改常量"的破坏，所以期望值写死在这里。
EXPECTED_FIELD_ORDER = [
    "schema_version", "platform_verification_id", "ami_id", "region", "architecture",
    "cloudformation_revision", "cfn_init_revision", "infrastructure_revision",
    "base_ami_revision", "nginx_base_revision", "docker_runtime_revision",
    "verification", "status", "platform_verified_at", "invalidated_at",
    "invalidated_reason", "base_ami_source", "source_ami_name", "source_ami_account",
    "source_ssm_parameter", "ami_resolved_at", "reverify_interval_days",
]

EXPECTED_VERIFICATION_KEYS = [
    "cfn_validated", "ec2_launched", "cfn_init_completed", "cfn_signal_received",
    "docker_runtime_ok", "nginx_ok", "ssm_ok", "cloudwatch_ok", "ebs_ok",
    "security_group_ok", "network_ok",
]


def test_build_contract_emits_keys_in_contract_field_order():
    """字段顺序即线上格式：重排 CONTRACT_FIELD_ORDER 会改变 R2 上 JSON 的字节内容。"""
    contract = golden.build_contract(
        _cfg(),
        platform_verification_id="plat-us-east-1-x86_64-20260906-001",
        ami_id="ami-1",
        ami_resolved_at="2026-09-06T00:00:00Z",
        revisions=_revisions(),
        verification={key: True for key in golden.VERIFICATION_KEYS},
        status=golden.VALID,
        verified_at="2026-09-06T00:00:00Z",
    )
    assert list(contract) == EXPECTED_FIELD_ORDER
    assert list(golden.CONTRACT_FIELD_ORDER) == EXPECTED_FIELD_ORDER


def test_build_contract_verification_is_exactly_the_eleven_keys():
    """多传的键必须被丢掉、漏传的键必须补 False——契约里不允许出现第十二个键。"""
    contract = golden.build_contract(
        _cfg(),
        platform_verification_id="p",
        ami_id="ami-1",
        ami_resolved_at="",
        revisions=_revisions(),
        verification={"ec2_launched": True, "not_a_real_key": True},
        status=golden.VALID,
        verified_at="",
    )
    assert list(contract["verification"]) == EXPECTED_VERIFICATION_KEYS
    assert list(golden.VERIFICATION_KEYS) == EXPECTED_VERIFICATION_KEYS
    assert len(contract["verification"]) == 11
    assert contract["verification"]["ec2_launched"] is True
    assert contract["verification"]["ssm_ok"] is False


def test_build_contract_revision_defaults_to_empty_string():
    contract = golden.build_contract(
        _cfg(),
        platform_verification_id="p",
        ami_id="ami-1",
        ami_resolved_at="",
        revisions={},
        verification={},
        status=golden.VALID,
        verified_at="",
    )
    assert all(contract[key] == "" for key in REVISION_KEYS)


def test_valid_contract_carries_no_invalidation_fields():
    contract = golden.build_contract(
        _cfg(),
        platform_verification_id="p",
        ami_id="ami-1",
        ami_resolved_at="",
        revisions=_revisions(),
        verification={},
        status=golden.VALID,
        verified_at="2026-09-06T00:00:00Z",
    )
    assert contract["invalidated_at"] is None
    assert contract["invalidated_reason"] is None


def test_invalid_contract_fills_invalidation_fields_with_default_reason():
    contract = golden.build_contract(
        _cfg(),
        platform_verification_id="p",
        ami_id="ami-1",
        ami_resolved_at="",
        revisions=_revisions(),
        verification={},
        status=golden.INVALID,
        verified_at="2026-09-06T00:00:00Z",
    )
    assert contract["invalidated_at"] == "2026-09-06T00:00:00Z"
    assert contract["invalidated_reason"] == "探针未全通过"


def test_invalid_contract_keeps_explicit_reason():
    contract = golden.build_contract(
        _cfg(),
        platform_verification_id="p",
        ami_id="ami-1",
        ami_resolved_at="",
        revisions=_revisions(),
        verification={},
        status=golden.INVALID,
        verified_at="2026-09-06T00:00:00Z",
        invalidated_reason="公开 AMI 已被厂商替换",
    )
    assert contract["invalidated_reason"] == "公开 AMI 已被厂商替换"


def test_build_contract_reads_public_ami_source_fields():
    contract = golden.build_contract(
        _cfg(),
        platform_verification_id="p",
        ami_id="ami-1",
        ami_resolved_at="",
        revisions=_revisions(),
        verification={},
        status=golden.VALID,
        verified_at="",
    )
    assert contract["source_ami_name"] == "al2023-ami-*"
    assert contract["source_ami_account"] == "amazon"


# --------------------------------------------------------------------------- 复验 id 递增


def test_next_platform_verification_id_increments_within_same_day():
    cfg = _cfg()
    existing = {"platform_verification_id": "plat-us-east-1-x86_64-20260906-004"}
    assert golden.next_platform_verification_id(cfg, existing, when="2026-09-06T09:00:00Z") == (
        "plat-us-east-1-x86_64-20260906-005"
    )


def test_next_platform_verification_id_restarts_on_new_day():
    cfg = _cfg()
    existing = {"platform_verification_id": "plat-us-east-1-x86_64-20260906-004"}
    assert golden.next_platform_verification_id(cfg, existing, when="2026-09-07T00:00:00Z") == (
        "plat-us-east-1-x86_64-20260907-001"
    )


def test_next_platform_verification_id_starts_at_001_without_history():
    cfg = _cfg()
    for existing in ({}, {"platform_verification_id": "plat-eu-west-1-arm64-20260906-009"}):
        assert golden.next_platform_verification_id(cfg, existing, when="2026-09-06T00:00:00Z") == (
            "plat-us-east-1-x86_64-20260906-001"
        )


# --------------------------------------------------------------------------- 漂移判定


def test_missing_contract_is_drift_not_clean():
    """源码注释写明的不变量：拿不到契约不等于"没有漂移"，应用验证此时无可引用。"""
    assert golden.DriftReport().drifted is True


def test_clean_drift_report_is_not_drifted():
    report = golden.DriftReport(contract_found=True)
    assert report.drifted is False


def _drift(monkeypatch, contract: dict | None, *, revisions=None, live_ami_id="ami-recorded"):
    """把 compute_revisions 换成可控值，只测 check_drift 自己的判定逻辑。"""
    monkeypatch.setattr(
        platformref, "compute_revisions", lambda cfg, ami: revisions if revisions is not None else _revisions()
    )
    cfg = _cfg()
    backend = FakeBackend()
    if contract is not None:
        import json

        backend.store[platformref.contract_key(cfg.region, cfg.architecture)] = json.dumps(contract).encode()
    return golden.check_drift(backend, cfg, live_ami_id=live_ami_id)


def test_check_drift_reports_missing_contract(monkeypatch):
    report = _drift(monkeypatch, None)
    assert report.contract_found is False
    assert report.drifted is True
    assert any("没有 Platform Contract" in r for r in report.reasons), report.reasons


def test_check_drift_clean_when_nothing_changed(monkeypatch):
    report = _drift(monkeypatch, _contract())
    assert report.drifted is False
    assert report.reasons == []
    assert report.contract_status == golden.VALID
    assert report.recorded_ami_id == "ami-recorded"


def test_check_drift_detects_public_ami_replacement(monkeypatch):
    """今天真实发生过的场景：厂商换了公开 AMI，契约必须判失效并要求复验。"""
    report = _drift(monkeypatch, _contract(ami_id="ami-old"), live_ami_id="ami-new")
    assert report.ami_drifted is True
    assert report.drifted is True
    assert report.live_ami_id == "ami-new"
    assert any("公开 AMI 已被厂商替换" in r for r in report.reasons), report.reasons


def test_check_drift_detects_each_revision_change(monkeypatch):
    changed = _revisions()
    changed["cfn_init_revision"] = "rev-b-cfn_init_revision"
    report = _drift(monkeypatch, _contract(), revisions=changed)
    assert set(report.revision_drifts) == {"cfn_init_revision"}
    assert report.revision_drifts["cfn_init_revision"] == {
        "recorded": "rev-a-cfn_init_revision",
        "current": "rev-b-cfn_init_revision",
    }
    assert report.drifted is True


def test_check_drift_ignores_revision_that_recorded_empty(monkeypatch):
    """契约里为空的 revision 不参与比对：空值不是"变更"，是历史契约缺字段。"""
    contract = _contract()
    contract["nginx_base_revision"] = ""
    changed = _revisions()
    changed["nginx_base_revision"] = "rev-b-nginx_base_revision"
    report = _drift(monkeypatch, contract, revisions=changed)
    assert report.revision_drifts == {}
    assert report.drifted is False


def test_check_drift_detects_expired_contract(monkeypatch):
    report = _drift(monkeypatch, _contract(platform_verified_at="2020-01-01T00:00:00Z"))
    assert report.expired is True
    assert report.drifted is True
    assert any("超复验周期" in r for r in report.reasons), report.reasons


def test_check_drift_unparseable_timestamp_counts_as_expired(monkeypatch):
    """坏时间戳必须往"需复验"方向失败，不能被当成"契约很新"。"""
    report = _drift(monkeypatch, _contract(platform_verified_at="not-a-timestamp"))
    assert report.expired is True


def test_check_drift_ami_comparison_skipped_for_custom_ami(monkeypatch):
    """base_ami_source != public 时不存在"厂商替换 AMI"这回事，不能拿 live 值判漂移。"""
    monkeypatch.setattr(platformref, "compute_revisions", lambda cfg, ami: _revisions())
    cfg = _cfg(base_ami_source="custom", platform={"custom_ami": {}})
    import json

    backend = FakeBackend({platformref.contract_key(cfg.region, cfg.architecture): json.dumps(_contract()).encode()})
    report = golden.check_drift(backend, cfg, live_ami_id="ami-totally-different")
    assert report.ami_drifted is False
    assert report.drifted is False


# --------------------------------------------------------------------------- 探针清单


def test_probe_plan_plus_cfn_validated_is_exactly_verification_keys():
    """run_probes 产出的键集合 + 编排器补的 cfn_signal_received == 契约承诺的十一个键。"""
    planned = [key for _step, key, _title, _how in golden.probe_plan()]
    assert "cfn_signal_received" not in planned
    assert set(planned) | {"cfn_validated", "cfn_signal_received"} == set(golden.VERIFICATION_KEYS)
    assert len(set(planned)) == len(planned)


def test_run_probes_emits_probes_in_contract_order_even_when_all_fail():
    """单个探针炸掉不能中断其余测量（源码注释），且产出顺序必须与契约字段顺序一致。"""
    probes = golden.run_probes(
        None,
        None,
        golden.Canary(stack_name="corenova-canary"),
        {},
        cfn_validated=True,
        change_set="cs-arn",
    )
    keys = [p.key for p in probes]
    expected = [k for k in EXPECTED_VERIFICATION_KEYS if k != "cfn_signal_received"]
    assert keys == expected
    assert len(probes) == 10
    assert probes[0].ok is True  # cfn_validated 由编排器给定，不经过实例内命令
    assert all(p.ok is False for p in probes[1:])
    assert all(p.detail for p in probes[1:])  # 失败也必须留下可读证据


def test_run_probes_truncates_probe_detail():
    class Boom:
        def __getattr__(self, _name):
            raise RuntimeError("x" * 2000)

    probes = golden.run_probes(
        Boom(), None, golden.Canary(stack_name="s", instance_id="i-1"), {}, cfn_validated=False, change_set=""
    )
    assert all(len(p.detail) <= 600 for p in probes)


def test_ec2_probe_fails_fast_without_instance_id():
    ctx = SimpleNamespace(aws=None, canary=golden.Canary(stack_name="s"))
    assert golden._probe_ec2_launched(ctx) == (False, "栈输出里没有 InstanceId")


def test_ec2_probe_rereads_instance_state_on_every_poll(monkeypatch):
    """CFN CREATE_COMPLETE 时 EC2 可能还是 pending；state 只在循环前读一次就会误判失败。"""
    reads = {"n": 0}
    states = ("pending", "running")
    checks = ("pending", "ok")

    class Ec2:
        def describe_instances(self, InstanceIds):
            return {"Reservations": [{"Instances": [{"State": {"Name": states[min(reads["n"], 1)]}}]}]}

        def describe_instance_status(self, InstanceIds, IncludeAllInstances):
            idx = min(reads["n"], 1)
            reads["n"] += 1
            return {"InstanceStatuses": [{"SystemStatus": {"Status": checks[idx]}}]}

    def fake_poll(probe, *, timeout_s, interval_s):
        value = None
        for _ in range(3):
            value = probe()
            if value is not None:
                return value
        return value

    monkeypatch.setattr(golden, "poll_until", fake_poll)
    ctx = SimpleNamespace(
        aws=SimpleNamespace(ec2=Ec2()),
        canary=golden.Canary(stack_name="s", instance_id="i-1"),
    )
    assert golden._probe_ec2_launched(ctx) == (True, "state=running system-status=ok")
    assert reads["n"] == 2


def test_ec2_probe_reports_not_ok_after_polls_exhausted(monkeypatch):
    monkeypatch.setattr(golden, "poll_until", lambda probe, **_kw: probe() or None)

    class Ec2:
        def describe_instances(self, InstanceIds):
            return {"Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]}

        def describe_instance_status(self, InstanceIds, IncludeAllInstances):
            return {"InstanceStatuses": [{"SystemStatus": {"Status": "initializing"}}]}

    ctx = SimpleNamespace(
        aws=SimpleNamespace(ec2=Ec2()),
        canary=golden.Canary(stack_name="s", instance_id="i-1"),
    )
    assert golden._probe_ec2_launched(ctx) == (False, "state=running system-status=initializing")


# --------------------------------------------------------------------------- 小工具函数


def test_as_cfn_parameters_is_sorted_key_value_pairs():
    assert golden.as_cfn_parameters({"B": "2", "A": "1"}) == [
        {"ParameterKey": "A", "ParameterValue": "1"},
        {"ParameterKey": "B", "ParameterValue": "2"},
    ]


def test_canary_parameters_scope_log_group_to_verification_id():
    from corenova.config import Config

    run_id = "plat-us-east-1-x86_64-20260909-001"
    params = golden.canary_parameters(
        Config.load(),
        "ami-0123456789abcdef0",
        {"SubnetIds": "subnet-123", "BaseSGId": "sg-123"},
        run_id,
    )

    assert params["CloudWatchLogGroupName"] == f"/corenova/canary/{run_id}"


def test_wait_change_set_includes_early_validation_detail(monkeypatch):
    class CloudFormation:
        def describe_change_set(self, **_kwargs):
            return {"Status": "FAILED", "StatusReason": "Early Validation failed"}

        def describe_events(self, **_kwargs):
            return {
                "OperationEvents": [
                    {
                        "LogicalResourceId": "AppLogGroup",
                        "ValidationStatusReason": "Log group already exists.",
                    }
                ]
            }

    monkeypatch.setattr(golden, "poll_until", lambda probe, **_kwargs: probe())

    with pytest.raises(RuntimeError, match="AppLogGroup: Log group already exists"):
        golden._wait_change_set(SimpleNamespace(cfn=CloudFormation()), "plan", "stack")


def test_cleanup_canary_volumes_deletes_only_explicitly_tagged_volume(monkeypatch):
    class Ec2:
        def __init__(self):
            self.deleted: list[str] = []

        def describe_volumes(self, *, VolumeIds):
            if VolumeIds[0] in self.deleted:
                raise RuntimeError("InvalidVolume.NotFound: volume does not exist")
            return {
                "Volumes": [
                    {
                        "VolumeId": VolumeIds[0],
                        "State": "available",
                        "Tags": [{"Key": "corenova:billing", "Value": "canary-temporary"}],
                    }
                ]
            }

        def delete_volume(self, *, VolumeId):
            self.deleted.append(VolumeId)

    ec2 = Ec2()
    monkeypatch.setattr(golden, "poll_until", lambda probe, **_kwargs: probe())

    clean, notes = golden._cleanup_canary_volumes(SimpleNamespace(ec2=ec2), ["vol-canary"])

    assert clean is True
    assert ec2.deleted == ["vol-canary"]
    assert notes == ["数据卷 vol-canary 已删除"]


def test_cleanup_canary_volumes_refuses_unlabelled_volume(monkeypatch):
    class Ec2:
        def describe_volumes(self, *, VolumeIds):
            return {"Volumes": [{"VolumeId": VolumeIds[0], "State": "available", "Tags": []}]}

        def delete_volume(self, **_kwargs):
            raise AssertionError("must not delete an unlabelled volume")

    monkeypatch.setattr(golden, "poll_until", lambda probe, **_kwargs: probe())

    clean, notes = golden._cleanup_canary_volumes(SimpleNamespace(ec2=Ec2()), ["vol-user"])

    assert clean is False
    assert notes == ["数据卷 vol-user 缺少 canary-temporary 标签，拒绝删除"]


def test_without_default_drops_only_default():
    spec = {"Type": "String", "Default": "x", "AllowedPattern": ".+"}
    assert golden._without_default(spec) == {"Type": "String", "AllowedPattern": ".+"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [("https://example.com/path", "example.com"), ("http://example.com", "example.com"),
     ("example.com", "example.com"), ("", "")],
)
def test_strip_scheme(value, expected):
    assert golden._strip_scheme(value) == expected


def test_ports_of_collapses_wide_range_to_endpoints():
    """全端口区间不能展开成 65536 个元素；只留端点足够做"是否放行 22"的判断。"""
    assert golden._ports_of({"IpProtocol": "tcp", "FromPort": 0, "ToPort": 65535}) == {0, 65535}


def test_ports_of_expands_narrow_range():
    assert golden._ports_of({"IpProtocol": "tcp", "FromPort": 80, "ToPort": 81}) == {80, 81}


def test_ports_of_ignores_other_protocols_and_bad_values():
    assert golden._ports_of({"IpProtocol": "icmp", "FromPort": 80, "ToPort": 80}) == set()
    assert golden._ports_of({"IpProtocol": "tcp", "FromPort": "x", "ToPort": 80}) == set()


def test_runtime_ports_treats_minus_one_as_all_traffic():
    """IpProtocol=-1 是"全部流量"，用 {0} 表示，不能被当成 0 端口。"""
    assert golden._runtime_ports({"IpProtocol": "-1"}) == {0}
    assert golden._runtime_ports({"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443}) == {443}


def test_ssh_errors_flags_only_real_ssh_markers():
    assert golden._ssh_errors("app.yaml", "Properties:\n  KeyName: my-key\n") != []
    assert golden._ssh_errors("app.yaml", "  CidrIp: 0.0.0.0/0\n  # SSHLocation removed\n") != []
    assert golden._ssh_errors("app.yaml", "Resources:\n  Instance:\n    Type: AWS::EC2::Instance\n") == []


def test_ssh_errors_does_not_match_substring_inside_identifier():
    """正则要求标记在行首或空白/引号之后：MyKeyName 这类标识符不算 SSH 痕迹。"""
    assert golden._ssh_errors("app.yaml", "  TagName: MyKeyName\n") == []


def test_canary_presets_pin_a_digest_not_a_tag():
    """冒烟镜像必须 digest 钉住，否则每次 Golden 跑的其实不是同一个镜像。"""
    image = golden.CANARY_PRESETS["ImageReference"]
    assert "@sha256:" in image
    assert not image.endswith(":latest")


def test_shipped_templates_pass_every_offline_rule():
    """static_template_errors 是 Golden 第 1-3 步的全部离线门禁，仓库现状必须零问题。"""
    from corenova.config import Config

    assert golden.static_template_errors(Config.load()) == []
