#!/usr/bin/env python3
"""Read experiments.yaml for the shell scripts.

usage: exp_config.py get KEY                 e.g. get global.c1  (dotted path; prints the value)
       exp_config.py eval EXPR [--n N]       e.g. eval "2.0*c1*N" --n 3   -> 600
       exp_config.py cmd EXP RUN [ARG]       the run_experiment.sh / boot_test.sh line for one run;
                                             ARG = N for sweeps (E2a/E2b), a variant name for E5/E6/E7
       exp_config.py list                    every experiment with its runs and N / variants

Expressions may use numbers, + - * / ( ), c1 and N. Nothing else is evaluated.
"""

from __future__ import annotations

import argparse
import ast
import operator
import os
import shlex
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("HSL_EXPERIMENTS", HERE / "experiments.yaml"))

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

# variant name -> extra run_experiment.sh options
VARIANT_FLAGS = {
    "none": [],
    "ssm_level1": ["--degrade", "1"],
    "auto_shed": ["--auto-shed"],
    "alb": [],
    "cloudfront": ["--target", "cloudfront"],
}


def load(path: Path = CONFIG) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def evaluate(expr: str | float | int, names: dict[str, float]) -> float:
    if isinstance(expr, int | float):
        return float(expr)

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in names:
            return float(names[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        raise ValueError(f"unsupported expression: {expr!r}")

    return ev(ast.parse(str(expr), mode="eval"))


def fmt_num(x: float) -> str:
    return str(int(round(x))) if abs(x - round(x)) < 1e-9 or abs(x) >= 10 else f"{x:g}"


def resolve_env(env: dict, c1: float, n: int | None) -> list[str]:
    names = {"c1": c1, **({"N": n} if n is not None else {})}
    out = []
    for k, v in (env or {}).items():
        try:
            val = fmt_num(evaluate(v, names))
        except (ValueError, SyntaxError):
            val = str(v)  # plain strings such as MIX=match_only or HOLD=3m
        out.append(f"{k}={val}")
    return out


def get(cfg: dict, key: str):
    cur = cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(key)
        cur = cur[part]
    return cur


def command(cfg: dict, exp: str, run: int, arg: str | None = None) -> list[str]:
    try:
        e = cfg["experiments"][exp]
    except KeyError:
        raise SystemExit(f"unknown experiment {exp!r}; see `exp_config.py list`") from None
    c1 = float(cfg["global"]["c1"])
    exp_id, extra, n = exp, [], None

    if "boot_test" in e:
        variant = arg or "baked"
        if variant not in e.get("variants", []):
            raise SystemExit(f"{exp}: variant must be one of {e.get('variants')}")
        bt = e["boot_test"]
        return [
            "boot_test.sh",
            "--label",
            variant,
            "--from",
            str(bt["from"]),
            "--to",
            str(bt["to"]),
            f"{exp}_{variant}",
            str(run),
        ]

    if "mode_sweep" in e:
        if arg is None or int(arg) not in e["mode_sweep"]:
            raise SystemExit(f"{exp}: give N, one of {e['mode_sweep']}")
        n = int(arg)
        mode = f"static {n}"
        exp_id = f"{exp}_N{n}"
    else:
        mode = e["mode"]
    if "variants" in e:
        variant = arg or e["variants"][0]
        if variant not in e["variants"]:
            raise SystemExit(f"{exp}: variant must be one of {e['variants']}")
        extra = VARIANT_FLAGS[variant]
        exp_id = f"{exp}_{variant}"
    return ["run_experiment.sh", *extra, exp_id, str(run), mode, e["profile"], *resolve_env(e.get("env"), c1, n)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get")
    g.add_argument("key")
    v = sub.add_parser("eval")
    v.add_argument("expr")
    v.add_argument("--n", type=int)
    c = sub.add_parser("cmd")
    c.add_argument("exp")
    c.add_argument("run", type=int)
    c.add_argument("arg", nargs="?")
    sub.add_parser("list")
    a = ap.parse_args(argv)
    cfg = load()

    if a.cmd == "get":
        val = get(cfg, a.key)
        print(val if not isinstance(val, dict | list) else yaml.safe_dump(val, default_flow_style=True).strip())
    elif a.cmd == "eval":
        names = {"c1": float(cfg["global"]["c1"]), **({"N": a.n} if a.n is not None else {})}
        print(fmt_num(evaluate(a.expr, names)))
    elif a.cmd == "cmd":
        print(shlex.join(command(cfg, a.exp, a.run, a.arg)))
    else:
        for name, e in cfg["experiments"].items():
            choices = e.get("mode_sweep") or e.get("variants") or ""
            print(f"{name:5} runs={e.get('runs', 1)}  {('choices=' + str(choices)) if choices else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
