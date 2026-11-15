"""In-memory stand-ins for the boto3 clients the harness uses (no AWS, no moto)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace


class FakeASG:
    def __init__(self, desired: int = 1, min_size: int = 1, max_size: int = 6, instances: list[dict] | None = None):
        self.desired, self.min, self.max = desired, min_size, max_size
        self.policies: dict[str, dict] = {}
        self.scheduled: dict[str, dict] = {}
        self.instances = instances or []
        self.activities: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    def _rec(self, name: str, kw: dict) -> None:
        self.calls.append((name, kw))

    # describe
    def describe_auto_scaling_groups(self, AutoScalingGroupNames):  # noqa: N803
        return {
            "AutoScalingGroups": [
                {
                    "AutoScalingGroupName": AutoScalingGroupNames[0],
                    "DesiredCapacity": self.desired,
                    "MinSize": self.min,
                    "MaxSize": self.max,
                    "Instances": self.instances,
                }
            ]
        }

    def describe_policies(self, AutoScalingGroupName):  # noqa: N803
        return {"ScalingPolicies": [{"PolicyName": n, **p} for n, p in self.policies.items()]}

    def describe_scheduled_actions(self, AutoScalingGroupName):  # noqa: N803
        return {"ScheduledUpdateGroupActions": [{"ScheduledActionName": n, **a} for n, a in self.scheduled.items()]}

    def describe_scaling_activities(self, AutoScalingGroupName, MaxRecords):  # noqa: N803
        return {"Activities": self.activities}

    # mutate
    def delete_policy(self, AutoScalingGroupName, PolicyName):  # noqa: N803
        self._rec("delete_policy", {"PolicyName": PolicyName})
        del self.policies[PolicyName]

    def delete_scheduled_action(self, AutoScalingGroupName, ScheduledActionName):  # noqa: N803
        self._rec("delete_scheduled_action", {"ScheduledActionName": ScheduledActionName})
        del self.scheduled[ScheduledActionName]

    def update_auto_scaling_group(self, AutoScalingGroupName, MinSize, MaxSize, DesiredCapacity):  # noqa: N803
        self._rec("update", {"MinSize": MinSize, "MaxSize": MaxSize, "DesiredCapacity": DesiredCapacity})
        self.min, self.max, self.desired = MinSize, MaxSize, DesiredCapacity

    def put_scaling_policy(self, AutoScalingGroupName, PolicyName, **kw):  # noqa: N803
        self._rec("put_scaling_policy", {"PolicyName": PolicyName, **kw})
        self.policies[PolicyName] = kw

    def put_scheduled_update_group_action(self, AutoScalingGroupName, ScheduledActionName, **kw):  # noqa: N803
        self._rec("put_scheduled", {"ScheduledActionName": ScheduledActionName, **kw})
        self.scheduled[ScheduledActionName] = kw

    def set_desired_capacity(self, AutoScalingGroupName, DesiredCapacity, HonorCooldown):  # noqa: N803
        self._rec("set_desired", {"DesiredCapacity": DesiredCapacity, "HonorCooldown": HonorCooldown})
        if not self.min <= DesiredCapacity <= self.max:
            raise ValueError("desired outside min/max")
        self.desired = DesiredCapacity


class FakeELB:
    def __init__(self, targets: dict[str, str] | None = None):
        self.targets = targets or {}

    def describe_target_health(self, TargetGroupArn):  # noqa: N803
        return {
            "TargetHealthDescriptions": [
                {"Target": {"Id": i, "Port": 8000}, "TargetHealth": {"State": s}} for i, s in self.targets.items()
            ]
        }


class FakeEC2:
    def __init__(self, ips: dict[str, str] | None = None):
        self.ips = ips or {}

    def describe_instances(self, InstanceIds):  # noqa: N803
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": i,
                            "PrivateIpAddress": self.ips.get(i, "10.0.0.1"),
                            "Placement": {"AvailabilityZone": "ap-south-1a"},
                            "LaunchTime": datetime(2026, 11, 18, 10, 0, tzinfo=UTC),
                        }
                        for i in InstanceIds
                    ]
                }
            ]
        }


class FakeCW:
    """get_metric_data that returns one datapoint per query per page, over two pages."""

    def __init__(self):
        self.calls = 0

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, ScanBy, NextToken=None):  # noqa: N803
        self.calls += 1
        t = StartTime if NextToken is None else EndTime
        return {
            "MetricDataResults": [
                {"Id": q["Id"], "Timestamps": [t], "Values": [float(self.calls)]} for q in MetricDataQueries
            ],
            **({} if NextToken else {"NextToken": "page2"}),
        }


def instance(iid: str, state: str = "InService", az: str = "ap-south-1a") -> dict:
    return {"InstanceId": iid, "LifecycleState": state, "AvailabilityZone": az, "HealthStatus": "Healthy"}


def clients(asg=None, elb=None, ec2=None, cw=None) -> SimpleNamespace:
    return SimpleNamespace(asg=asg or FakeASG(), elb=elb or FakeELB(), ec2=ec2 or FakeEC2(), cw=cw or FakeCW())
