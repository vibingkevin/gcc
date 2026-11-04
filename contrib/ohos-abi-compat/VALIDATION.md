# OHOS ABI 验证记录（2026-11-04）

本轮在 ma1 构建、OHOS ARM64 真机执行；所有目标源码使用 `-O3`，仅跑
`AA / AB / BA`，main 始终由 A 编译、链接。A/B 表示 x/y 两个方向使用的
编译器；`shared` 模式各自生成 `libx.so`、`liby.so`。

## 环境与源码

- GCC 基线：`00513d11fb2b5a6b9a036ff3cb170e06e78ca18b`。
- A：DevEco Clang 15.0.4，源码 `99548401bd80576251755b185ab95945e5fe7884`。
- B：JetBrains Clang 21.1.6，源码 `c2e420df942a21f93c15248b4fb9259737fa58c1`，macOS ARM dev-97 包。
- 两侧共用 DevEco native SDK `6.1.1.125`、API 24 的 sysroot、头文件、resource-dir 和 `libc++_shared.so`。
- 目标：`aarch64-unknown-linux-ohos`，设备 API 24；Python 3.9.6，构建并发 4。
- 固定集源码版本 `090bd7e550e9dab6bfcd82ae27d118329b846622`；生成集构建版本 `a3fc24b1fed806899af060e00e5d8f07e0b3aa02`，之后的 new1 修正不涉及生成集。

本机 API 26 的早期构建和中止任务不计入下述设备结果。

## 测试规模与结果

一个程序组由 main/x/y 三份翻译单元组成，每组运行三个编译器组合。
固定集包含 108 个上游入口及 2 个补充入口；其中 23 个明确不适用，
其余 87 个程序组共 261 次双 SO 执行全部通过。

生成集使用未修改的上游生成器，传入 `-n 15000`，C++ 保留原有 `-c` 模式，
C 生成器禁用 Clang 不支持的 decimal 类型。实际生成 C 201 组、C++ 375 组，
合计 576 个程序组。它们展开为 C 18,153、C++ 33,651 个布局样本，合计
51,804 个样本实例；这不是 51,804 个独立可执行文件，也不是失败数量。
C++ 中 188 组使用默认 gnu++14，187 组是上游的 C++14/C++17 混合测试，
后者的样本编号会重新开始，不能仅按编号去重。

| 集合 | AA 通过/失败 | AB 通过/失败 | BA 通过/失败 | 合计 |
| --- | ---: | ---: | ---: | --- |
| 固定集（shared） | 87 / 0 | 87 / 0 | 87 / 0 | 261 通过，23 组不适用 |
| C 生成集（shared） | 179 / 22 | 201 / 0 | 179 / 22 | 559 通过，44 失败 |
| C++ 生成集（shared） | 341 / 34 | 350 / 25 | 338 / 37 | 1,029 通过，96 失败 |
| 固定 + 生成 | 607 / 56 | 638 / 25 | 604 / 59 | 1,849 通过，140 失败 |

生成集 517 组全部通过，59 组至少一个组合失败。所有 140 个失败保留为
`RUN_FAIL`，没有转为跳过或预期失败；不能把 140 次失败解释为 140 个独立 ABI 缺陷。

补充验证：冒烟 10 组 × 两种链接模式 × 三个组合，共 60 次通过；
故意制造布局差异的负例在两种模式共 6 次均返回 1 并输出
`ABI_LAYOUT_MISMATCH`；框架 6 个单测通过。

不适用的 23 组均保留名称及原因：14 组 decimal，7 组有上游目标限制，
1 组需要 Clang 不支持的 `-funsigned-bitfields`，1 组含 Clang 不支持的结构体内 VLA。
详细结果、编译器与原始产物哈希见 [results-2026-11-04.json](results-2026-11-04.json)。

## 失败定位

生成器、生成源码及上游布局断言均未修改。诊断仅增加 `-DDBG`，启用上游已有的
`fail 样本编号.断言编号` 输出，并对照 objects/shared 模式。

59 个原失败组全部完成 DBG 重放，objects/shared × AA/AB/BA 共 354 次：
280 次失败、74 次通过，每项退出码均与原 shared 结果一致；59 份生成布局头文件
也逐字节相同。全部失败只命中 `.17` 和 `.71` 两类断言，涉及空结构体、零长度数组、
零宽位域等边界；这完成了失败分类，并非逐个样本的根因证明。

三个 AA 通过、AB/BA 失败的程序组是 `g++.dg/t031`、`t033`、`t184`，
分别命中样本 3869、4558、16634；诊断日志与原样本定义均收录在 JSON 中。

### 跨版本空聚合体传参差异

`generated/g++.dg/t031` 的样本 3869：

```c++
T(3869,struct{long double b[0];}a[6];,)
```

原始和 DBG 重放均为 AA 通过、AB/BA 失败，objects/shared 行为一致。
失败为 `3869.17`（中间的指针参数不等于预期）和 `3869.71`（后续变参
`long long` 不等于 2）。在原始编译命令上仅添加 `-S -emit-llvm` 后观察到：

```llvm
; A 的调用与定义：两个空聚合体占用 i8 参数位置
@_Z9check38695S3869PS_S_(i8, ptr, i8)
; B 的调用与定义：省略两个空聚合体参数
@_Z9check38695S3869PS_S_(ptr)
```

A/B 对同一符号采用不同调用签名，导致指针所处参数位置不同。这个实例证明
在 GNU 零长度数组扩展形成的空聚合体边界上存在跨版本调用约定不兼容；
不代表普通结构体或所有 C++ 接口都不兼容。尚未定位引入差异的 LLVM 提交，
也没有判定哪一版本符合该扩展的预期 ABI。

### A 的空聚合体变参处理

`generated/gcc.dg/t001` 的样本 94：

```c
T(94,struct atal16{}a;,)
```

AA、BA 失败，AB 通过；两种链接模式均出现 `94.71`。原始 LLVM IR 显示
A 的 `va_arg` 在消费这个大小为零、对齐为 16 的结构体时仍对齐通用寄存器
读取偏移，B 省略该步骤。随后读取的 `long long` 因此不同。
这属于 A 单工具链也能触发的失败，不能算成仅由 A/B 混编引起的问题。

`generated/g++.dg/t006` 的 1085 也在 AA、BA 报 `.71`；
`t016` 的 1644 在 AA 报 `.71`、AB 报 `.17/.71`、BA 报 `.17`，
表明同一程序组可能同时包含基线问题与跨版本差异，不能只按组级结果归因。

## 唯一上游测试修改：eh/new1

独立提交 [090bd7e](https://github.com/vibingkevin/gcc/commit/090bd7e550e9dab6bfcd82ae27d118329b846622)
仅修改 `gcc/testsuite/g++.dg/compat/eh/new1_x.C`；commit message 已记录原因和实测证据。

原用例在两套 Clang 的 `-O3` 下省略了要检查的 new[]/delete[] 调用。
诊断还发现 objects 模式的进程初始化会提前调用覆盖的分配函数，将 `ret` 置零，
因此原 objects 通过并没有验证目标路径，而 shared 的三个组合均以 134 退出。
`-fno-assume-sane-operator-new` 不能恢复目标调用，`-fno-builtin` 可以。

修正只增加该选项，并在目标操作前重置 `ret = 1`。保持 `-O3`，保留
原 `p == ptr` 检查、构造异常路径及失败条件，没有调整预期结果。
修正后 objects/shared × AA/AB/BA 六次均通过，固定全集随后复验通过。

## 重跑与边界

```sh
python3 contrib/ohos-abi-compat/run.py \
  --sdk-native "$OHOS_NATIVE_HOME" --llvm-b "$JB_LLVM_HOME" \
  --suite generated --generated-size full --mode shared \
  --out "$RUN_OUTPUT"
# 在同一输出目录上追加 --execute-only --device "$DEVICE_ID" 执行已有产物。
```

重放代表失败，使用新的输出目录：

```sh
python3 contrib/ohos-abi-compat/run.py \
  --sdk-native "$OHOS_NATIVE_HOME" --llvm-b "$JB_LLVM_HOME" \
  --suite generated --generated-size full --case 'generated/g++.dg/t031' \
  --mode both --layout-debug --device "$DEVICE_ID" --out "$REPRO_OUTPUT"
```

原始 environment/report/build 日志、生成源码、IR 与设备 results.tar.gz 留在
ma1 当前会话工作区；Git 仅保存摘要及证据，不提交工具链或测试二进制。
所有正式固定/生成集的 3,315 条目标编译命令已核对仅使用 `-O3`，组合仅 AA/AB/BA。
没有执行 BB，没有新增 seed、多 seed 循环或改写生成器。当前结果是本次固定
生成序列和指定 SDK/设备上的覆盖，不构成全 ABI 兼容保证。
