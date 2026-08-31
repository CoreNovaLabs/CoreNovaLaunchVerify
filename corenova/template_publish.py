"""one-click 用户模板的公开 S3 分发（深链 templateURL 的唯一事实源）。

深链（Repo A 的 Generate Template）把 `templateURL` 指向
``https://<bucket>.s3.us-east-1.amazonaws.com/corenova-one-click.template.yaml`` --
CloudFormation 控制台原生支持该直链形态，点击即进创建向导。因此模板必须
由 Repo C 发布且公开可读：

- 模板内容 **app 无关**，只在 `templates/cloudformation/fixed/*.yaml` 变化时变化，
  所以发布挂在 `build_user_template.py` 之后（`publish-template.yml` 路径过滤触发），
  不挂每次验证的 PUBLISHING（`publish.py`）--后者随 app 版本走，且默认无 AWS。
- 公开桶是**附加分发渠道**，不是第二个事实源后端：桶里只放这一个对象，
  verified JSON / 截图 / Platform Contract 仍走 dir|r2 后端（repo-structure §4.2.1）。
- 发布成立的判据与两阶段提交 P3 同一精神：匿名 GET 探到 200 且字节一致才算成功，
  探测不过 = 没发布（抛错让 workflow 红掉），绝不静默宣称成功。
"""

from __future__ import annotations

from typing import Any, Callable

from .util import http_request, log

TEMPLATE_KEY = "corenova-one-click.template.yaml"
TEMPLATE_CONTENT_TYPE = "application/x-yaml"

# probe 形状与 corenova.util.http_request 一致：(status, headers, body)
Probe = Callable[..., tuple[int, dict[str, str], bytes]]


def public_template_url(bucket: str, region: str = "us-east-1") -> str:
    """虚拟主机风格直链（CFN 控制台原生支持，Repo A 深链引用的同一形态）。"""
    return f"https://{bucket}.s3.{region}.amazonaws.com/{TEMPLATE_KEY}"


def _acl_disabled(exc: BaseException) -> bool:
    """桶禁用对象 ACL（2023+ 新桶默认 Object Ownership = bucket owner enforced）。

    两种错误码都见过：PutObject 带 ACL 是 AccessControlListNotSupported，
    旧文档/部分路径是 AccessControlListNotEnabled--按码匹配，字符串兜底。
    """
    resp = getattr(exc, "response", None) or {}
    code = (resp.get("Error") or {}).get("Code", "")
    return code in ("AccessControlListNotSupported", "AccessControlListNotEnabled") or any(
        marker in str(exc) for marker in ("AccessControlListNotSupported", "AccessControlListNotEnabled")
    )


def _client(cfg) -> Any:
    import boto3

    return boto3.client("s3", region_name=cfg.template_s3_region)


def publish(
    cfg: Any,
    data: bytes,
    *,
    s3: Any | None = None,
    probe: Probe = http_request,
) -> dict[str, Any]:
    """put 模板到公开读桶，并以匿名 GET 探测公开可读性。

    桶的公开读有两种合法形态，put 都兼容、探测统一把关：
    ① 对象 ACL `public-read`（桶需放行 ACL）；② 桶策略 Allow s3:GetObject（桶禁用 ACL 时唯一途径）。
    """
    bucket = cfg.template_bucket
    if not bucket:
        raise RuntimeError(
            "未配置 one-click 模板分发桶：设 TEMPLATE_S3_BUCKET（或 config/verify.yaml "
            "template_s3.bucket），桶需预先创建并允许公开读（us-east-1）。"
        )
    if not data:
        raise ValueError("模板内容为空，拒绝发布")

    s3 = s3 or _client(cfg)
    url = public_template_url(bucket, cfg.template_s3_region)
    put = {"Bucket": bucket, "Key": TEMPLATE_KEY, "Body": data, "ContentType": TEMPLATE_CONTENT_TYPE}
    try:
        s3.put_object(**put, ACL="public-read")
        mode = "object-acl:public-read"
    except Exception as exc:  # noqa: BLE001 - boto3 的 ClientError 无独立基类可窄化
        if not _acl_disabled(exc):
            raise
        s3.put_object(**put)
        mode = "bucket-policy（桶禁用 ACL，公开读依赖桶策略）"
    log(f"template put: s3://{bucket}/{TEMPLATE_KEY} ({len(data)} bytes, {mode})")

    status, _, body = probe(url, timeout=30, retries=3)
    if status != 200 or body != data:
        raise RuntimeError(
            f"公开可读性探测失败（HTTP {status}，收到 {len(body)} bytes / 期望 {len(data)}）：{url} "
            "-- 检查桶策略或对象 ACL（Block Public Access 需对该桶放行）。深链指向读不到的模板，等于没发布。"
        )
    return {"bucket": bucket, "key": TEMPLATE_KEY, "url": url, "bytes": len(data), "readable_via": mode}
