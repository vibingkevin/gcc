# OHOS 跨编译器 ABI 测试

复用 GCC C/C++ compat 用例及原始布局生成器，检查 DevEco Clang 15（A）与
JB Clang 21.1.6（B）的 OHOS ARM64 互操作。两侧共用 DevEco native SDK，
固定 `-O3`，只运行 `AA / AB / BA`。main 始终由 A 编译、链接。

Python 3.9+，宿主 C 编译器、DevEco native SDK、JB LLVM dev 包即可运行；
无需构建 GCC，也不需要安装 DejaGnu。

```sh
python3 contrib/ohos-abi-compat/run.py \
  --sdk-native "$OHOS_NATIVE_HOME" --llvm-b "$JB_LLVM_HOME" \
  --suite smoke --mode both --out "$RUN_OUTPUT"
```

`--out` 必须是新目录。省略 `--device` 时只构建，状态为 `BUILT`，不算测试通过。
运行设备前，由调用者按照所在环境规则取得设备租约，再追加 `--device DEVICE_ID`。
驱动只访问指定设备，不管理或强制释放他人的租约。

建议先完成构建，再取得租约并使用同一组路径参数追加
`--execute-only --device DEVICE_ID`。这会执行已有产物，避免编译期间占用设备。
已经执行过的目录不能再次覆盖；单例重放使用新的 `--out` 和相同 `--case`。

## 模式与范围

- `--mode shared`：x/y 各自生成 SO，main 同时依赖两个 SO，默认模式。
- `--mode objects`：原来的目标文件混编方式，用来定位是否为动态链接问题。
- `--mode both`：同时运行以上两种模式。
- `--suite smoke`：8 个固定代表用例和 2 个补充用例。
- `--suite fixed`：全部 108 个固定入口和 2 个补充用例。
- `--suite generated`：执行未经修改的上游生成器，默认伪随机状态固定。
- `--suite all`：固定和生成式用例；`--generated-size full` 传入上游 `-n 15000`。
- `--suite selftest`：结构体/双向调用和 C++ runtime 跨 SO 补充用例。
- `--suite negative`：故意使 y 侧结构体 packed，预期每个组合返回 1；返回 0 是失败。
- `--case 'g++.dg/compat/eh/*'`：按 ID 过滤，可重复指定。

补充 C++ 用例覆盖跨库创建/销毁对象、虚调用、RTTI、异常、string/vector/shared_ptr。
C++ 布局生成器保留上游 `-c` 模式；C 生成器按 Clang 能力禁用 decimal 类型。
本阶段没有增加 seed 接口，也没有多 seed 循环。

生成式用例失败时，可用相同 `--generated-size`、`--case` 和新输出目录重放，
追加 `--layout-debug` 启用上游已有的 `DBG` 输出；日志中的 `fail n.m`
分别是布局样本编号和断言编号。该选项仅增加 `-DDBG`，不改变断言或跳过检查。
用 `--mode both` 对照目标文件混编与双 SO，以区分动态链接问题。

## 结果与边界

`environment.json` 记录编译器版本和哈希、SDK、配置、源码版本。
`report.json` 按用例和组合记录结果；`summary.json` 提供汇总。
每个用例的 `build.log` 包含可重放命令，`results.tar.gz` 包含设备日志和原始退出码。
输出目录保留生成源码和二进制，不写入 Git。

所有源码中的优化等级都被统一为 `-O3`。保留适用的语言、布局等其他选项。
目标条件按 OHOS AArch64 处理；不支持的条件或指令明确报告 `UNSUPPORTED`。
未知编译错误保留为 `BUILD_FAIL`，不能自动变成跳过。`break/` 用例标记为历史 ABI
变化用例，失败需要结合原用例说明判断，不能直接声称发现新回归。

SO 使用各自编译器的链接器，main 使用 A；实际部署同一份 SDK 的
`libc++_shared.so`。每组独立进程运行，以退出码和完整结果集合确认完成。
设备需要允许执行测试二进制，并提供 `sh`、`tar`、`timeout`。

```sh
python3 -m unittest discover -s contrib/ohos-abi-compat -p 'test_*.py' -v
```

本轮实测规模、失败分类及上游用例修改原因见 [VALIDATION.md](VALIDATION.md)。
