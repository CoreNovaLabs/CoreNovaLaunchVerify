#!/usr/bin/env python3
"""把 network.yaml + app.yaml 合并成**单栈**的一键部署模板（用户自有 AWS 账号用）。

产出自包含模板：VPC/子网/SG + EC2 + cfn-init 装机 + 应用容器（镜像引用参数化）。
- contracts/app-schema.md §7（单容器）、architecture.md §9（自助部署=用户自己账号）
- platform-contract.md §8（SSM 运维，22 入站关闭，无 KeyPair）
- AMI：默认用 AWS 公共 SSM 参数动态引用（Canonical Ubuntu 24.04，部署时解析最新）；
  用户显式传 AmiId 时覆盖。动态引用只能出现在资源属性里，不能进 Parameter Default，
  所以用反向 Condition（AmiId 为空）+ Fn::If 实现——同时避开 CFN 对 Fn::Not 的解析怪癖。

    python scripts/verify/build_user_template.py --out data/templates/corenova-one-click.template.yaml
    python scripts/verify/build_user_template.py --publish-s3   # 追加：发布到公开读桶（深链 URL 源）

输出与 app.yaml 的注释版不同属预期（yaml.safe_dump，注释不保留；canary.yaml 同理）。
"""

from __future__ import annotations

import argparse
import copy
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXED = ROOT / "templates" / "cloudformation" / "fixed"

# app.yaml 里这三个参数表达"挂到已有网络栈"；单栈模板由本模板自己的网络资源取代。
DROP_PARAMS = ("SubnetId", "SecurityGroupId", "NetworkStackName")

SSM_PUBLIC_AMI = (
    "{{resolve:ssm-public:/aws/service/canonical/ubuntu/server/24.04/stable/"
    "current/amd64/hvm/ebs-gp3/ami-id}}"
)


def build() -> dict:
    net = yaml.safe_load((FIXED / "network.yaml").read_text(encoding="utf-8"))
    app = yaml.safe_load((FIXED / "app.yaml").read_text(encoding="utf-8"))

    conditions: dict = {}
    for src in (net, app):
        for k, v in (src.get("Conditions") or {}).items():
            conditions[k] = copy.deepcopy(v)
    # 反向条件：AmiId 留空 => ImageId 用 SSM 公共参数（CFN 对 Fn::Not 嵌套有解析怪癖）
    conditions["UseSsmPublicAmi"] = {"Fn::Equals": [{"Ref": "AmiId"}, ""]}

    resources: dict = {}
    for name, spec in net["Resources"].items():
        resources[name] = copy.deepcopy(spec)
    for name, spec in app["Resources"].items():
        spec = copy.deepcopy(spec)
        text = yaml.safe_dump(spec, sort_keys=False)
        text = (
            text.replace("Ref: SubnetId\n", "Ref: PublicSubnetA\n")
            .replace("Ref: SecurityGroupId\n", "Ref: BaseSG\n")
            .replace("Ref: NetworkStackName\n", "Ref: AWS::StackName\n")
            .replace(
                "ImageId:\n          Ref: AmiId\n",
                "ImageId:\n          Fn::If:\n"
                "            - UseSsmPublicAmi\n"
                "            - " + SSM_PUBLIC_AMI + "\n"
                "            - Ref: AmiId\n",
            )
        )
        resources[name] = yaml.safe_load(text)

    parameters: dict = {}
    for src in (net, app):
        for k, v in src["Parameters"].items():
            if k in DROP_PARAMS:
                continue
            v = copy.deepcopy(v)
            if k == "AmiId":
                # 放宽为 String：允许留空走动态引用（Image::Id 类型不允许空默认值）
                v["Type"] = "String"
                v["Default"] = ""
                v["Description"] = (
                    "Optional. Leave empty to use the latest Canonical Ubuntu 24.04 "
                    "LTS AMI via the AWS public SSM parameter."
                )
            parameters[k] = v

    outputs: dict = {}
    for src in (net, app):
        for k, v in (src.get("Outputs") or {}).items():
            outputs[k] = copy.deepcopy(v)

    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": (
            "CoreNova Launch — one-click deploy of a CoreNova-verified application "
            "into your own AWS account. Single stack: VPC + SSM-only EC2 host "
            "(Docker via cfn-init, port 22 closed) running the exact image that "
            "passed verification. Docs: https://corenova-website.pages.dev/docs/verification"
        ),
        "Parameters": parameters,
        "Conditions": conditions,
        "Resources": resources,
        "Outputs": outputs,
        "Metadata": {
            "AWS::CloudFormation::Interface": {
                "ParameterGroups": [
                    {"Label": {"default": "Application"}, "Parameters": [
                        "AppName", "ImageReference", "ContainerPort", "HealthCheckPath",
                    ]},
                    {"Label": {"default": "Host"}, "Parameters": [
                        "InstanceType", "DiskGb", "AmiId",
                    ]},
                ],
                "ParameterLabels": {
                    "ImageReference": {
                        "default": "Image (exact tag) — keep the digest-pinned value"
                    },
                    "AppName": {"default": "Application name"},
                },
            }
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=str(ROOT / "data" / "templates" / "corenova-one-click.template.yaml"),
    )
    ap.add_argument(
        "--publish-s3",
        action="store_true",
        help="发布到公开读 S3 桶（TEMPLATE_S3_BUCKET；put 后匿名 GET 探测，不可读即失败）",
    )
    args = ap.parse_args()

    tpl = build()
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(tpl, sort_keys=False, allow_unicode=True, width=10_000),
        encoding="utf-8",
    )
    print(f"written: {out_path}")
    print(
        f"  params: {len(tpl['Parameters'])}  resources: {len(tpl['Resources'])}"
        f"  outputs: {len(tpl['Outputs'])}  conditions: {len(tpl['Conditions'])}"
    )

    text = out_path.read_text(encoding="utf-8")
    for bad in ("Ref: SubnetId\n", "Ref: SecurityGroupId\n", "Ref: NetworkStackName\n"):
        if bad in text:
            print(f"FAIL: merged template still references {bad.strip()}")
            return 1
    print("rewire check: OK")

    if args.publish_s3:
        # 深链 templateURL 的唯一事实源（deployment-contract.md §2.4）：
        # 模板活在公开桶里，站点不再自托管副本。发布失败必须让本脚本退出非零。
        sys.path.insert(0, str(ROOT))
        from corenova import template_publish
        from corenova.config import Config

        try:
            info = template_publish.publish(Config.load(), text.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - 发布失败要红给 CI 看，不吞
            print(f"FAIL: S3 发布失败：{type(exc).__name__}: {exc}")
            return 1
        print(f"published: {info['url']} ({info['bytes']} bytes, {info['readable_via']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
