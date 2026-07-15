# CavaVox

双路 cavacore 离线音频频谱可视化工具。加载预分离的混音 + 人声 WAV 文件，分别使用独立 cavacore 实例计算 FFT 频谱，人声以覆盖色叠加在背景频谱上实时渲染。

## 使用

```bash
# 激活环境
source .venv/bin/activate

# 基本用法
python main.py --mix mix.wav --vocal-file vocals.wav

# 只显示人声频谱（去掉白色背景）
python main.py --mix mix.wav --vocal-file vocals.wav --vocal

# 调整帧偏移补偿
python main.py --mix mix.wav --vocal-file vocals.wav --offset 20
```

## 构建

依赖：FFTW3、CMake、C 编译器。

```bash
# Fedora
sudo dnf install fftw3 fftw3-devel cmake gcc

# 构建共享库
mkdir -p dll/build && cd dll/build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build .
# libcavacore.so 自动复制到项目根目录
```

## 依赖

```bash
uv sync
```
