# C++17 / O0、O3 验证（2026-11-04）

本轮按用户要求，所有 C++ 翻译单元（main、x、y、补充 runtime 用例）
统一使用 `-std=c++17`，与 Kotlin/Native runtime 一致。依据为 Kotlin reference
提交 `ec112ef9ec3e4446f2d07188f626dce8364eb433` 的
`kotlin-native/runtime/build.gradle.kts:157`。覆盖上游源码中的其他 `-std`，
没有修改测试源码、生成器或断言。框架配置提交为 `f89022c`。

## 范围与复现

两套编译器、DevEco SDK 6.1.1.125 / API 24、OHOS ARM64 真机、ma1 环境
与[初次报告](VALIDATION.md)相同。仍仅 AA、AB、BA，main 使用 A。
默认优化等级为 O3，增加 `--optimization 0` 可跑 O0。

生成规模对应 `RUN_ALL_COMPAT_TESTS`：上游 `.exp` 为生成器增加 `-n 15000`，
本驱动的 `--generated-size full` 传入相同参数；执行入口是双 SO 驱动，
不直接运行 DejaGnu。保留 C++ 生成器 `-c` 产生的全部样本和空基类定义，
但原本 C++14/17 混合部分的两侧现在都按 C++17 编译。

两轮均包含 110 个固定/补充入口及 576 个生成程序组；生成样本实例仍为
51,804 个。576 份布局头文件在 O0、O3 和初次测试之间逐字节相同。
每轮 3,312 条目标编译命令已审计：1,295 条 C、2,017 条 C++（包含报错命令），
C++ 均只有一个 `-std=c++17`；优化选项均为各轮选定的 O0 或 O3。
两轮编译器、SDK、runtime 和驱动哈希一致。

```sh
python3 contrib/ohos-abi-compat/run.py \
  --sdk-native "$OHOS_NATIVE_HOME" --llvm-b "$JB_LLVM_HOME" \
  --suite all --generated-size full --mode shared --optimization 0 \
  --out "$O0_OUTPUT"
# 编译后使用同一 SDK/LLVM/out，追加 --execute-only --device "$DEVICE_ID"。
# O3 使用 --optimization 3 和新的输出目录。
```

## 结果

| 集合 | O0 通过 / 运行失败 | O3 通过 / 运行失败 |
| --- | ---: | ---: |
| 固定/补充集 | 258 / 0 | 258 / 0 |
| 生成集 | 1,585 / 143 | 1,588 / 140 |
| 合计 | 1,843 / 143 | 1,846 / 140 |

两轮各 662 个程序组成功编译，共执行 1,986 次；另外均有 23 组
`UNSUPPORTED` 和 1 组 `BUILD_FAIL`。O0 有 60 个运行失败组，O3 有 59 个。
框架原有 6 个单测通过。

`g++.dg/compat/eh/unexpected1` 在 C++17 编译失败：原用例的
`throw (Two)` 和 `std::set_unexpected` 已被该标准移除。
保留 `BUILD_FAIL`，没有降级语言标准、改成 noexcept 或放宽错误来绕过。
本轮没有新增上游测试修改；此前 `eh/new1` 的必要修正仍由独立提交 `090bd7e` 记录。

## 优化等级差异

逐项核对全部结果，唯一差异为 `generated/g++.dg/t153`：

| 组合 | O0 | O3 |
| --- | ---: | ---: |
| AA | 139 | 0 |
| AB | 139 | 0 |
| BA | 139 | 0 |

对此用原有 `DBG` 输出再做 O0 objects/shared 对照，六次均以 139 退出，
复现了 SIGSEGV 类型失败。它也发生在 AA，且不限于双 SO 模式。
尚未定位触发样本及根因，不能据此认定为新的跨编译器 ABI 缺陷或排除用例问题。
其余 1,983 次 O0/O3 退出码一致；原先的 140 次失败在 O0 仍存在，
因此降低优化等级没有消除那批失败。

初次报告使用 gnu++14 / C++14、17 混合配置，保留作历史记录，不与本轮合并计数。
用户提出统一 C++17 前启动的混合标准 O0 构建已停止，也未计入本轮结果。

逐组/逐组合退出码见 [TSV 对照表](results-cxx17-2026-11-04.tsv)，
环境、原始文件哈希、跳过原因及 t153 重放结果见
[JSON 记录](results-cxx17-2026-11-04.json)。原始源码、二进制和设备日志位于 ma1
当前会话工作区。没有运行 BB，没有新增 seed 或循环 fuzz。
