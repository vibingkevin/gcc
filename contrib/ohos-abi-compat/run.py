#!/usr/bin/env python3
"""使用 DevEco/JB Clang 运行 GCC compat，固定 -O3 和 AA/AB/BA。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TARGET = "aarch64-unknown-linux-ohos"
PAIRS = ("AA", "AB", "BA")
SMOKE = {
    "gcc.dg/compat/scalar-by-value-1", "gcc.dg/compat/struct-by-value-1",
    "gcc.dg/compat/struct-return-2", "gcc.dg/compat/struct-align-1",
    "gcc.dg/compat/vector-1", "g++.dg/compat/abi/vbase8-10",
    "g++.dg/compat/eh/ctor1", "g++.dg/compat/init/byval1",
}


class Unsupported(Exception):
    pass


class CommandError(Exception):
    pass


def command(argv, log, timeout=180):
    argv = [str(x) for x in argv]
    with Path(log).open("a") as output:
        output.write("$ " + shlex.join(argv) + "\n")
        output.flush()
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=output, stderr=output, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise CommandError(f"命令超时，见 {log}") from error
    if result.returncode:
        raise CommandError(f"命令退出 {result.returncode}，见 {log}")


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dg_directives(text):
    # 仅解析声明式数据；不执行来自测试源码的 Tcl。
    for match in re.finditer(r"\{\s*(dg-[\w-]+)\b", text):
        depth = 0
        quoted = False
        escaped = False
        end = None
        for index in range(match.start(), len(text)):
            char = text[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
        if end is None:
            raise Unsupported("未闭合的 dg 指令")
        tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}]|[^\s{}]+', text[match.start():end])
        stack = [[]]
        for token in tokens:
            if token == "{":
                stack.append([])
            elif token == "}":
                node = stack.pop()
                stack[-1].append(node)
            else:
                stack[-1].append(shlex.split(token)[0] if token.startswith('"') else token)
        yield stack[0][0]


def target_matches(expr):
    if isinstance(expr, str):
        if "-" in expr or "*" in expr or "?" in expr:
            return fnmatch.fnmatchcase(TARGET, expr)
        known = {"lp64": True, "ilp32": False, "int32plus": True,
                 "alloca": True, "exceptions_enabled": True,
                 "dfp": False, "dfprt": False, "sse2_runtime": False,
                 "avx_runtime": False, "avx": False}
        if expr not in known:
            raise Unsupported(f"尚未支持的目标条件：{expr}")
        return known[expr]
    if expr and expr[0] == "target":
        return target_matches(expr[1:])
    if expr and expr[0] == "!":
        return not target_matches(expr[1:])
    for operator in ("||", "&&"):
        if operator in expr:
            index = expr.index(operator)
            left, right = target_matches(expr[:index]), target_matches(expr[index + 1:])
            return (left or right) if operator == "||" else (left and right)
    return any(target_matches(x) for x in expr)


def source_options(path):
    flags = []
    for directive in dg_directives(path.read_text()):
        kind, *args = directive
        if kind == "dg-options":
            if len(args) == 1 or target_matches(args[1]):
                flags = shlex.split(args[0])
        elif kind == "dg-require-effective-target":
            if not target_matches(args[0]):
                raise Unsupported(f"需要 {args[0]}")
        elif kind == "dg-require-compat-dfp":
            raise Unsupported("两套 Clang 不支持 GCC decimal floating point")
        elif kind == "dg-skip-if":
            if len(args) > 2:
                raise Unsupported("尚未支持带选项过滤的 dg-skip-if")
            if target_matches(args[1]):
                raise Unsupported(args[0])
        elif kind != "dg-prune-output":
            raise Unsupported(f"尚未支持的指令：{kind}")
    if "-funsigned-bitfields" in flags:
        raise Unsupported("Clang 不支持 -funsigned-bitfields，不能静默忽略")
    # 用户明确要求所有编译均使用 -O3，包括源码内指定其他优化等级的用例。
    return [flag for flag in flags if not re.fullmatch(r"-O(?:[0-3sgz]|fast)?", flag)]


def case_from_main(main, name):
    stem = main.name.replace("_main", "")
    return {"id": name, "sources": [main, main.with_name(stem.replace(main.suffix, "_x" + main.suffix)),
                                     main.with_name(stem.replace(main.suffix, "_y" + main.suffix))]}


def discover(args):
    cases = []
    if args.suite in ("smoke", "fixed", "all"):
        for language in ("gcc.dg", "g++.dg"):
            directory = ROOT / "gcc/testsuite" / language / "compat"
            for main in sorted(directory.rglob("*_main.*")):
                name = str(main.relative_to(ROOT / "gcc/testsuite")).rsplit("_main.", 1)[0]
                if args.suite != "smoke" or name in SMOKE:
                    cases.append(case_from_main(main, name))
    if args.suite in ("smoke", "fixed", "all", "selftest", "negative"):
        for name in (["layout"] if args.suite == "negative" else ["layout", "runtime"]):
            suffix = ".c" if name == "layout" else ".C"
            case = case_from_main(HERE / "fixtures" / (name + "_main" + suffix), "probe/" + name)
            case["negative"] = args.suite == "negative"
            cases.append(case)
    if args.suite in ("generated", "all"):
        c_dir = ROOT / "gcc/testsuite/gcc.dg/compat"
        for language in ("gcc.dg", "g++.dg"):
            source = ROOT / "gcc/testsuite" / language / "compat"
            output = args.out / "generated" / language
            output.mkdir(parents=True)
            generator = output / "generate"
            flags = ["-DSKIP_DECIMAL_FLOAT"] if language == "gcc.dg" else []
            command([args.host_cc, *flags, source / "struct-layout-1_generate.c",
                     c_dir / "generate-random.c", c_dir / "generate-random_r.c", "-o", generator],
                    output / "generator.log")
            flags = ["-c"] if language == "g++.dg" else []
            if args.generated_size == "full":
                flags += ["-n", "15000"]
            command([generator, "-s", source, "-d", output, *flags], output / "generator.log")
            for main in sorted(output.glob("*_main.*")):
                cases.append(case_from_main(main, "generated/" + language + "/" + main.stem.removesuffix("_main")))
    if args.case:
        cases = [case for case in cases if any(fnmatch.fnmatchcase(case["id"], pattern) for pattern in args.case)]
    if not cases:
        raise ValueError("没有匹配的测试用例")
    return cases


class Builder:
    def __init__(self, args):
        self.args = args
        self.sdk = args.sdk_native
        self.llvm = {"A": self.sdk / "llvm", "B": args.llvm_b}
        self.resources = Path(subprocess.check_output([self.llvm["A"] / "bin/clang", "-print-resource-dir"], text=True).strip())
        self.libs = self.sdk / "llvm/lib/aarch64-linux-ohos"

    def driver(self, compiler, cxx):
        return self.llvm[compiler] / "bin" / ("clang++" if cxx else "clang")

    def common(self, compiler):
        return ["--target=" + TARGET, "--sysroot=" + str(self.sdk / "sysroot"),
                "-resource-dir=" + str(self.resources), "-O3", "-fPIC"]

    def compile(self, source, dest, compiler, options, log):
        cxx = source.suffix == ".C"
        flags = (["-std=gnu++14", "-nostdinc++", "-isystem",
                  str(self.sdk / "llvm/include/libcxx-ohos/include/c++/v1")] if cxx else
                 ["-std=gnu17", "-DSKIP_DECIMAL_FLOAT", "-Wno-error=implicit-function-declaration", "-Wno-error=implicit-int"])
        command([self.driver(compiler, cxx), *self.common(compiler), *flags, *options,
                 "-O3", "-c", source, "-o", dest], log, self.args.compile_timeout)

    def link(self, objects, dest, compiler, cxx, options, log, shared=False):
        flags = ["--ld-path=" + str(self.llvm[compiler] / "bin/ld.lld"), "-L" + str(self.libs)]
        flags += (["-shared", "-Wl,-soname," + dest.name] if shared else
                  ["-pie", "-Wl,--export-dynamic", "-Wl,--no-as-needed"])
        command([self.driver(compiler, cxx), *self.common(compiler), *options, *flags,
                 *objects, "-o", dest], log, self.args.compile_timeout)

    def build(self, case):
        directory = self.args.out / "build" / case["id"]
        directory.mkdir(parents=True)
        log = directory / "build.log"
        result = {"id": case["id"], "status": "BUILD_FAIL", "runs": [],
                  "negative": case.get("negative", False),
                  "historical_abi_break": "/break/" in case["id"], "log": str(log)}
        try:
            if case["id"] == "gcc.dg/compat/struct-by-value-22":
                raise Unsupported("Clang 不支持结构体内 VLA；禁用后此用例将没有断言，故整例跳过")
            options = [source_options(source) for source in case["sources"]]
            result["sources"] = [{"path": str(source), "sha256": sha256(source)} for source in case["sources"]]
            result["source_options"] = options
            main, x, y = case["sources"]
            cxx = main.suffix == ".C"
            result["stage"] = "compile"
            self.compile(main, directory / "main.o", "A", options[0], log)
            for compiler in "AB":
                for index, source in enumerate((x, y), 1):
                    part = "xy"[index - 1]
                    extra = ["-DABI_NEGATIVE"] if case.get("negative") and part == "y" else []
                    self.compile(source, directory / (part + compiler + ".o"), compiler, options[index] + extra, log)
            modes = ["objects", "shared"] if self.args.mode == "both" else [self.args.mode]
            result["stage"] = "link"
            for mode in modes:
                for pair in PAIRS:
                    run = self.args.out / "payload" / case["id"] / mode / pair
                    run.mkdir(parents=True)
                    objects = [directory / "main.o"]
                    for part, compiler in zip("xy", pair):
                        obj = directory / (part + compiler + ".o")
                        if mode == "shared":
                            library = run / ("lib" + part + ".so")
                            self.link([obj], library, compiler, cxx, [], log, shared=True)
                            objects.append(library)
                        else:
                            objects.append(obj)
                    self.link(objects, run / "test", "A", cxx, options[0], log)
                    if mode == "shared":
                        inspect = subprocess.check_output([self.llvm["A"] / "bin/llvm-readelf", "-d", run / "test"], text=True)
                        if not all("[lib" + part + ".so]" in inspect for part in "xy"):
                            raise CommandError("主程序没有同时依赖 libx.so 和 liby.so")
                        (run / "dynamic.txt").write_text(inspect)
                    result["runs"].append({"path": str(run.relative_to(self.args.out / "payload")), "mode": mode, "pair": pair})
            result["status"] = "BUILT"
            result["stage"] = "built"
        except Unsupported as error:
            result.update(status="UNSUPPORTED", reason=str(error))
        except (CommandError, subprocess.CalledProcessError) as error:
            result["reason"] = str(error)
        return result


def parse_results(text):
    result = {}
    for line in text.splitlines():
        path, code = line.split("\t")
        if path in result:
            raise ValueError(f"重复的设备结果：{path}")
        result[path] = int(code)
    return result


def run_status(code, output, negative=False):
    if negative:
        if code == 1 and "ABI_LAYOUT_MISMATCH" in output.splitlines():
            return "XFAIL"
        return "XPASS" if code == 0 else "RUN_FAIL"
    return "PASS" if code == 0 else "TIMEOUT" if code == 124 else "RUN_FAIL"


def execute(args, builder, results):
    payload = args.out / "payload"
    payload.mkdir(exist_ok=True)
    shutil.copy2(builder.libs / "libc++_shared.so", payload)
    remote = "/data/local/tmp/gcc-abi-" + uuid.uuid4().hex
    runs = [run for result in results if result["status"] == "BUILT" for run in result["runs"]]
    lines = ["#!/system/bin/sh", "cd " + shlex.quote(remote) + " || exit 125", ": > results.tsv"]
    for run in runs:
        path = run["path"]
        lines += [f"(cd {shlex.quote(path)} && LD_LIBRARY_PATH={shlex.quote(remote)}:. timeout -k 5 {args.timeout} ./test) > {shlex.quote(path + '/run.log')} 2>&1",
                  f"printf '%s\\t%s\\n' {shlex.quote(path)} \"$?\" >> results.tsv"]
    lines += ["echo COMPLETE > complete"]
    (payload / "run.sh").write_text("\n".join(lines) + "\n")
    archive = args.out / "payload.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload, arcname=".")
    log = args.out / "device.log"
    hdc = [args.hdc, "-t", args.device]
    command(hdc + ["shell", "uname -a; param get const.ohos.apiversion; timeout -k 1 2 sh -c 'exit 0'"], log)
    (args.out / "remote.json").write_text(json.dumps({"device": args.device, "directory": remote}, indent=2))
    try:
        command(hdc + ["shell", "mkdir -p " + remote], log)
        command(hdc + ["file", "send", archive, remote + "/payload.tar.gz"], log)
        command(hdc + ["shell", f"cd {remote} && tar -xzf payload.tar.gz && sh run.sh"],
                log, max(120, len(runs) * (args.timeout + 6) + 60))
        command(hdc + ["shell", f"cd {remote} && tar -czf results.tar.gz results.tsv complete $(find . -name run.log)"], log)
        command(hdc + ["file", "recv", remote + "/results.tar.gz", args.out / "results.tar.gz"], log)
        with tarfile.open(args.out / "results.tar.gz") as tar:
            if tar.extractfile("complete").read().strip() != b"COMPLETE":
                raise CommandError("设备测试没有完成")
            codes = parse_results(tar.extractfile("results.tsv").read().decode())
            outputs = {member.name.removeprefix("./").removesuffix("/run.log"):
                       tar.extractfile(member).read().decode(errors="replace")
                       for member in tar.getmembers() if member.isfile() and member.name.endswith("/run.log")}
        expected = {run["path"] for run in runs}
        if set(codes) != expected or set(outputs) != expected:
            raise CommandError("设备结果集合与计划执行集合不一致")
        for result in results:
            if result["status"] != "BUILT":
                continue
            for run in result["runs"]:
                code = codes[run["path"]]
                run["exit_code"] = code
                run["status"] = run_status(code, outputs[run["path"]], result["negative"])
            result["status"] = "PASS" if all(run["status"] in ("PASS", "XFAIL") for run in result["runs"]) else "RUN_FAIL"
    finally:
        command(hdc + ["shell", "rm -rf " + remote], log)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-native", type=Path, required=True)
    parser.add_argument("--llvm-b", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="必须是新目录，防止混入旧结果")
    parser.add_argument("--suite", choices=("smoke", "fixed", "generated", "all", "selftest", "negative"), default="smoke")
    parser.add_argument("--generated-size", choices=("default", "full"), default="default")
    parser.add_argument("--mode", choices=("shared", "objects", "both"), default="shared")
    parser.add_argument("--case", action="append", help="用例 ID glob，可重复")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--compile-timeout", type=int, default=180)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--host-cc", default="cc")
    parser.add_argument("--hdc", default="hdc")
    parser.add_argument("--device", help="省略时只构建，不报告运行通过；调用者须先持有设备租约")
    parser.add_argument("--execute-only", action="store_true", help="执行 out 中尚未运行的构建结果，不重新编译")
    args = parser.parse_args()
    for name in ("sdk_native", "llvm_b", "out"):
        setattr(args, name, getattr(args, name).resolve())
    builder = Builder(args)
    if args.execute_only:
        if not args.device:
            parser.error("--execute-only 需要 --device")
        saved = json.loads((args.out / "environment.json").read_text())
        if saved["runtime_sha256"] != sha256(builder.libs / "libc++_shared.so"):
            parser.error("SDK runtime 与构建时不一致")
        results = json.loads((args.out / "report.json").read_text())
        if any("exit_code" in run for row in results for run in row["runs"]):
            parser.error("此目录已经执行过；重放请使用新的输出目录")
        started = time.monotonic()
        execute(args, builder, results)
        return finish(args, results, started)
    args.out.mkdir(parents=True, exist_ok=False)
    metadata = {"configuration": vars(args), "target": TARGET, "pairs": PAIRS, "optimization": "-O3",
                "source_commit": subprocess.check_output(["git", "-C", ROOT, "rev-parse", "HEAD"], text=True).strip(),
                "compilers": {key: {"path": str(builder.driver(key, False)), "sha256": sha256(builder.driver(key, False)),
                                      "version": subprocess.check_output([builder.driver(key, False), "--version"], text=True)} for key in "AB"},
                "runtime_sha256": sha256(builder.libs / "libc++_shared.so"), "driver_sha256": sha256(__file__)}
    package = args.sdk_native / "oh-uni-package.json"
    if package.exists():
        metadata["sdk"] = json.loads(package.read_text())
    (args.out / "environment.json").write_text(json.dumps(metadata, indent=2, default=str, ensure_ascii=False) + "\n")
    cases = discover(args)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(builder.build, cases))
    report = args.out / "report.json"
    report.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    if args.device:
        execute(args, builder, results)
    return finish(args, results, started)


def finish(args, results, started):
    (args.out / "report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    summary = {"cases": len(results), "status": dict(Counter(x["status"] for x in results)),
               "runs": dict(Counter(run.get("status", "BUILT") for x in results for run in x["runs"])),
               "seconds": round(time.monotonic() - started, 2)}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    return int(any(x["status"] not in ("BUILT", "PASS", "UNSUPPORTED") for x in results))


if __name__ == "__main__":
    raise SystemExit(main())
