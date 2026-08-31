"""one-click 模板公开 S3 分发的行为测试（deployment-contract.md §2.4）。

关键断言：put 之后匿名 GET 探测不过（非 200 / 字节不一致）必须抛错 --
深链指向一个读不到的模板，比不发还糟。
"""

from __future__ import annotations

import pytest

from corenova import template_publish


class Cfg:
    """最小 config 替身：只暴露 template_publish 需要的字段。"""

    def __init__(self, bucket: str = "corenovalaunch-templates", region: str = "us-east-1"):
        self.template_bucket = bucket
        self.template_s3_region = region


class AclDisabledError(Exception):
    """形状对齐 botocore ClientError：response.Error.Code（外加字符串兜底）。

    真实 PutObject 带 ACL 报 AccessControlListNotSupported；测试覆盖两种历史错误码。
    """

    def __init__(self, code: str = "AccessControlListNotSupported"):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self, acl_disabled: bool = False):
        self.acl_disabled = acl_disabled
        self.calls: list[dict] = []

    def put_object(self, **kw):
        self.calls.append(kw)
        if self.acl_disabled and kw.get("ACL"):
            raise AclDisabledError()


def ok_probe(url, **kw):
    return 200, {}, DATA


DATA = b"AWSTemplateFormatVersion: '2010-09-09'\n"


# ---------------------------------------------------------------- URL 形态


def test_public_url_is_cfn_native_virtual_host_form():
    assert template_publish.public_template_url("corenovalaunch-templates") == (
        "https://corenovalaunch-templates.s3.us-east-1.amazonaws.com/"
        "corenova-one-click.template.yaml"
    )
    assert template_publish.public_template_url("b", "eu-west-1") == (
        "https://b.s3.eu-west-1.amazonaws.com/corenova-one-click.template.yaml"
    )


# ---------------------------------------------------------------- put + 探测


def test_publish_puts_public_read_and_probes():
    s3 = FakeS3()
    info = template_publish.publish(Cfg(), DATA, s3=s3, probe=ok_probe)
    assert s3.calls == [{
        "Bucket": "corenovalaunch-templates",
        "Key": template_publish.TEMPLATE_KEY,
        "Body": DATA,
        "ContentType": template_publish.TEMPLATE_CONTENT_TYPE,
        "ACL": "public-read",
    }]
    assert info["url"] == template_publish.public_template_url("corenovalaunch-templates")
    assert info["readable_via"] == "object-acl:public-read"


def test_publish_acl_disabled_bucket_puts_without_acl():
    """2023+ 新桶默认禁对象 ACL：put 回退为不带 ACL，公开读交给桶策略，探测仍是唯一判据。"""
    s3 = FakeS3(acl_disabled=True)
    info = template_publish.publish(Cfg(), DATA, s3=s3, probe=ok_probe)
    assert len(s3.calls) == 2
    assert s3.calls[0]["ACL"] == "public-read"
    assert "ACL" not in s3.calls[1]
    assert info["readable_via"].startswith("bucket-policy")


@pytest.mark.parametrize("code", ["AccessControlListNotSupported", "AccessControlListNotEnabled"])
def test_publish_recognizes_both_acl_disabled_error_codes(code):
    """真实环境报 NotSupported、部分路径报 NotEnabled--两种都必须触发回退，不能裸抛。"""
    class RaiseOnce:
        def __init__(self):
            self.calls = []

        def put_object(self, **kw):
            self.calls.append(kw)
            if kw.get("ACL"):
                raise AclDisabledError(code)

    s3 = RaiseOnce()
    info = template_publish.publish(Cfg(), DATA, s3=s3, probe=ok_probe)
    assert len(s3.calls) == 2
    assert info["readable_via"].startswith("bucket-policy")


@pytest.mark.parametrize("status,body", [(403, b""), (404, b""), (200, b"stale bytes")])
def test_publish_fails_when_not_publicly_readable(status, body):
    def probe(url, **kw):
        return status, {}, body

    with pytest.raises(RuntimeError, match="公开可读性探测失败"):
        template_publish.publish(Cfg(), DATA, s3=FakeS3(), probe=probe)


def test_publish_requires_configured_bucket():
    with pytest.raises(RuntimeError, match="TEMPLATE_S3_BUCKET"):
        template_publish.publish(Cfg(bucket=""), DATA, s3=FakeS3(), probe=ok_probe)


def test_publish_rejects_empty_template():
    with pytest.raises(ValueError):
        template_publish.publish(Cfg(), b"", s3=FakeS3(), probe=ok_probe)
