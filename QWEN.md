# Cava Vocal Overlay (CAVA_4)

## 项目概览

双路 cavacore 离线音频频谱可视化工具。加载两路预分离的 WAV 音频文件（混音 + 人声），使用两个独立 cavacore 实例分别计算 FFT 频谱柱状图，然后通过 OpenCV 实时渲染——人声频谱以覆盖色叠加在背景频谱之上，同时通过 pygame 播放混音音频。

核心算法复用 [cava](https://github.com/karlstav/cava) 的 `cavacore.c` 引擎（FFTW3 驱动），通过 ctypes 调用，保证可视化精度与原生 cava 一致。上游核心源码 (`cavacore.c`/`cavacore.h`) 已剥离至 `dll/` 目录独立维护。

## 目录结构

```
Cava_4/
├── main.py                  # 主程序：预处理 + 实时渲染
├── cavacore_wrap.py         # ctypes 封装层：cava_init / cava_execute / cava_destroy
├── libcavacore.so           # Linux 构建的 cavacore 共享库
├── cavacore.dll             # Windows 预编译的 cavacore 共享库
├── CMakeLists_cavacore_dll.txt  # 构建共享库的 CMake 配置（根级别）
├── pyproject.toml           # Python 项目配置（uv 管理）
├── diff_analysis.md         # 与 cava 原生管线的逐环节对比分析文档
├── cache/                   # 预处理缓存（.npz 文件）
├── dll/                     # cavacore 核心源码与构建系统
│   ├── CMakeLists.txt       # 构建配置（跨平台）
│   ├── cavacore.c           # 核心 FFT 可视化引擎（来自上游 cava）
│   ├── cavacore.h           # C API 头文件
│   ├── cavacore_helper.c    # ctypes 安全 getter 函数（规避 struct padding）
│   ├── CAVACORE.md          # cavacore 引擎设计文档
│   ├── test_init.c          # C 级集成测试
│   └── build/               # 构建输出（gitignored）
├── .venv/                   # Python 虚拟环境（uv 管理）
└── .gitignore
```

## 核心技术栈

| 层 | 技术 |
|----|------|
| 核心引擎 | C（cavacore.c, FFTW3） |
| Python 绑定 | ctypes |
| 音频加载 | soundfile (libsndfile) |
| 重采样 | librosa |
| 实时渲染 | OpenCV (cv2) |
| 音频播放 | pygame.mixer |
| 数值计算 | NumPy |
| 预处理缓存 | np.savez_compressed（MD5 缓存键) |

## 管线流程

```
WAV(混音) ──┐
             ├─ librosa 重采样 → float32 → [双独立 cavacore 实例] ──→ bar_data ──→ 缓存(npy)
WAV(人声) ──┘                                                                    ↓
                                                        ┌── OpenCV 矩形渲染 (背景白 + 人声黄)
                                                        ├── pygame 音频播放 (混音)
                                                        └── 实时帧同步 (elapsed * fps + offset)
```

### 预处理阶段 (`precompute_bars`)
1. 加载双 WAV 文件，截齐到等长，可选重采样到 22050 Hz 单声道
2. 初始化两个独立 `CavaPlan` 实例
3. 逐帧调用 `cava_execute`：每帧覆盖 `1/framerate` 秒音频
4. 输出缩放 `* sensitivity/100`，clamp 到 [0, 1]
5. 缓存为 `.npz` 文件（key 基于文件大小 + mtime + 关键参数 MD5）

### 渲染阶段 (`render`)
1. pygame.mixer 播放混音音频
2. OpenCV 窗口逐帧绘制：背景频谱（白色矩形）+ 人声频谱（黄色矩形覆盖）
3. 帧同步通过 `time.time() - t0` 计算当前帧索引，支持 `latency_offset` 补偿

## 依赖安装

按照 `diff_analysis.md` 和构建文档，项目依赖包括：

```bash
# Python 依赖
pip install numpy opencv-python pygame soundfile librosa

# C 构建依赖（构建 cavacore.dll 时需要）
# Fedora:
sudo dnf install fftw3 fftw3-devel cmake gcc
```

## 构建 cavacore.dll

```bash
mkdir -p build_dll && cd build_dll
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build .
# DLL 会自动复制到项目根目录
```

替代方案（使用 `dll/` 目录的 CMakeLists.txt）：
```bash
mkdir -p dll/build && cd dll/build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build .
```

## 运行

```bash
# 先修改 main.py 底部的 CONFIG 字典配置音频文件路径
python main.py

# 仅显示人声频谱（去掉白色背景）
python main.py --vocal

# 指定帧偏移补偿（覆盖 CONFIG 中的 latency_offset）
python main.py --offset 20
```

## 关键配置

配置来源有两层：
1. **~/.config/cava/config** — 读取 `[general]`, `[smoothing]`, `[output]` 节（与 cava 原生一致）
2. **main.py CONFIG 字典** — 覆盖音频路径、窗口尺寸、颜色和 `latency_offset` 等自定义参数

关键参数：
- `latency_offset`: FFT 半窗延迟补偿（帧数），默认 18
- `framerate`: 目标帧率，决定每帧采样数 = `sample_rate / framerate`
- `sensitivity`: 灵敏度百分比（乘到 cavacore 输出上）
- `bars`: 显示柱数

## 开发约定

- **配置读取**: 尽量复用 cava 原生 config 格式，新增参数写在 `CONFIG` 字典中
- **缓存策略**: 预处理结果缓存在 `cache/` 目录，key 由文件 stat + 参数 MD5 决定
- **DLL 构建**: 始终使用 `CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS`（见 `dll/CMakeLists.txt`），避免修改 `cavacore.h` 源码
- **ctypes 安全**: 通过 `cavacore_helper.c` 提供 getter 函数读取 struct 字段，而非直接解析内存布局
- **测试文件**: 以 `_` 开头的 Python 文件为临时调试脚本（不提交），`test_*.py` 为保留的测试文件，`dll/test_init.c` 为 C 级集成测试
- **音频文件路径**: 本地开发使用 `G:\Music\htdemucs_ft\` 下的 demucs 分离产物，Linux 部署需修改 CONFIG 路径
- **项目文档**: 详细算法对比分析见 `diff_analysis.md`
