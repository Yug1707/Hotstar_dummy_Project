import csv

import monitor_asg
import sample_cpu
from common import GroupState
from fakes import instance


def test_instance_lifecycle_timestamps(tmp_path):
    tr = monitor_asg.InstanceTracker()
    assert tr.update(100.0, [instance("i-1", "Pending")], {}, {"i-1": 90.0})
    assert tr.update(130.0, [instance("i-1")], {"i-1": "initial"}, {})
    assert tr.update(145.0, [instance("i-1")], {"i-1": "healthy"}, {})
    assert not tr.update(150.0, [instance("i-1")], {"i-1": "healthy"}, {})  # nothing new
    assert tr.update(400.0, [], {}, {})  # gone from the ASG -> terminated
    r = tr.rows["i-1"]
    assert (r["launch_time"], r["first_seen_ts"], r["in_service_ts"], r["first_healthy_ts"], r["terminated_ts"]) == (
        "90.000",
        "100.000",
        "130.000",
        "145.000",
        "400.000",
    )
    tr.write(tmp_path / "instances.csv")
    rows = list(csv.DictReader((tmp_path / "instances.csv").open()))
    assert rows[0]["instance_id"] == "i-1" and list(rows[0]) == monitor_asg.INSTANCE_COLS


def test_missing_launch_time_is_retried():
    tr = monitor_asg.InstanceTracker()
    tr.update(1.0, [instance("i-1", "Pending")], {}, {})
    assert tr.missing_launch_times() == ["i-1"]
    tr.update(2.0, [instance("i-1", "Pending")], {}, {"i-1": 0.5})
    assert tr.missing_launch_times() == []


def test_timeline_row_matches_columns():
    st = GroupState(desired=3, in_service=2, pending=1, healthy=2, initial=1)
    row = monitor_asg.timeline_row(10.0, st)
    assert len(row) == len(monitor_asg.TIMELINE_COLS)
    assert row[1:] == [3, 2, 1, 0, 2, 0, 1, 0]


def test_stats_rows_with_missing_instance():
    insts = [{"id": "i-1"}, {"id": "i-2"}]
    rows = monitor_asg.stats_rows(5.0, insts, [{"rps": 12.5, "shed_total": 3}, None])
    assert rows[0][:3] == ["5.000", "i-1", 12.5] and rows[0][monitor_asg.STATS_COLS.index("shed_total")] == 3
    assert rows[1][1] == "i-2" and set(rows[1][2:]) == {""}


def test_cpu_percent(tmp_path):
    p = tmp_path / "stat"
    p.write_text("cpu  100 0 100 700 100 0 0 0 0 0\n")
    a = sample_cpu.read_proc_stat(str(p))
    p.write_text("cpu  200 0 200 1300 100 0 0 0 0 0\n")
    b = sample_cpu.read_proc_stat(str(p))
    assert sample_cpu.percent(a, b) == 25.0  # 200 busy of 800 jiffies
    f = tmp_path / "cpu.csv"
    f.write_text("ts,cpu_percent,load1\n1,12.5,0.1\n2,61.0,0.3\n")
    assert sample_cpu.max_of(f) == 61.0
    assert sample_cpu.max_of(tmp_path / "missing.csv") == -1.0


# ---- lab lock (conditional write semantics with a fake S3) ---------------------------------------
class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None):  # noqa: N803
        from botocore.exceptions import ClientError

        if IfNoneMatch == "*" and Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Key] = Body


def test_lab_lock_is_exclusive():
    import lab_lock

    s3 = FakeS3()
    assert lab_lock.acquire(s3, "b", "E3", "1")
    assert not lab_lock.acquire(s3, "b", "E4c", "1")
    assert b'"exp": "E3"' in s3.objects["lab.lock"]
