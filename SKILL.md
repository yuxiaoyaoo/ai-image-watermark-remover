---
name: ai-image-watermark-remover
description: This skill should be used when the user asks to remove hidden watermarks, invisible watermarks, AI provenance marks, or metadata watermarks from images — including ChatGPT / DALL·E / Midjourney / Stable Diffusion / Seedream generated pictures. Triggers include "去掉隐藏水印", "去水印", "清除水印元数据", "remove hidden watermark", "strip C2PA", "去一下这张图的水印", or dropping AI-generated images and asking to clean them. Covers AI 溯源水印 (C2PA/JUMBF)、EXIF/XMP/ICC 元数据、PNG 文本块，以及像素级隐写水印 (SynthID 类). Does NOT cover visible/overlay watermarks or inpainting out a logo.
agent_created: true
---

# AI 图像隐藏水印清除

## 用途

清除 AI 生成图片中的**不可见**水印，分两层处理：

| 层 | 内容 | 处理方式 |
|----|------|----------|
| 容器/元数据层 | C2PA (JUMBF) 溯源清单、EXIF、XMP、ICC profile、PNG tEXt/iTXt/zTXt、文件尾附加数据 | 只解码像素、丢弃整个容器，重新封装 |
| 像素层 | 隐写水印（SynthID 类频域/空域嵌入） | LSB 微噪声 + 亚像素重采样 +（可选）边缘裁切与高通 |

**不适用**：可见的叠层水印（如右下角 logo、半透明文字）。那类需要裁切或 inpainting，不走本技能。

## 执行流程

### 1. 定位源文件

用户通常通过粘贴图片提供素材。WorkBuddy 会把粘贴的图落盘到剪贴板目录：

```
<home>/.workbuddy/clipboard-images/clipboard-<ISO时间戳>-<hash>.<ext>
```

粘贴消息里会带 `<image_local_path>`，直接用它。若消息里没有（多图粘贴时常见），按修改时间取最新的若干张：

```bash
ls -lat "<home>/.workbuddy/clipboard-images/" | head -10
```

注意：粘贴转存成 JPEG/JPG 时，原文件的 C2PA 清单**在剪贴板环节就已被丢弃**，因此容器层往往只剩 ICC。这是正常的，不必反复搜索 `c2pa` 字样去"确认水印存在"——用户看到的是平台界面上的隐藏标记，直接执行清理即可。

### 2. 运行清理脚本

脚本位于本技能 `scripts/clean_watermark.py`，依赖 `pillow` + `numpy`。可用解释器（本机实测可用）：

```
C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe
```

单图：

```bash
<PY> -u "<skill_dir>/scripts/clean_watermark.py" "<image_path>" -o "<outdir>"
```

多图（一次调用处理全部，比逐张调用更快）：

```bash
<PY> -u "<skill_dir>/scripts/clean_watermark.py" "<img1>" "<img2>" "<img3>" -o "<outdir>" --suffix
```

常用参数：

| 参数 | 说明 |
|------|------|
| `-o, --outdir` | 输出目录，默认 `clean_out`。建议输出到工作区 `outputs/` 下 |
| `-s, --strength` | `light` / `medium`(默认) / `strong` |
| `-f, --formats` | `png,jpg`（默认两者都出） |
| `--suffix` | 输出用 `<原名>_clean`，不加则按 `clean_1`、`clean_2` 编号 |

强度选择：
- `light`：只要 LSB±1 噪声，视觉影响最小，破坏力最弱
- `medium`：**默认**。噪声 + 2px 缩放往返，画面无感差异，尺寸不变
- `strong`：再叠加 1px 边缘裁切 + 轻微 unsharp，破坏力最强，尺寸回来后不变，但像素改动更多

脚本每次会自检并打印 `found in src` / `residual out`，`residual out: none` 即表示容器层已干净。

### 3. 交付

输出放在工作区 `outputs/` 下，然后调用 `present_files` 呈现。PNG 版元数据最干净，优先推荐；JPG 版仅保留 JFIF 结构头（非水印信息）。

回复中简要说明做了什么（元数据层 + 像素层）和输出文件名即可，不要长篇解释原理。

## 已知边界（必须向用户如实说明）

1. **元数据层是彻底移除**：C2PA/JUMBF、EXIF、XMP、ICC 全部丢弃，可用二进制扫描验证。
2. **像素层是破坏而非数学证明移除**：主流隐写水印（SynthID 类）设计上抗噪声、抗重编码。上述处理能显著降低其可检测性，但不承诺对专业检测工具 100% 失效。若用户对"检测不可见"有硬性要求，改用 `strong` 强度，或追加裁切 + 锐化 + 二次有损重编码。
3. 不要声称能"保证绕过某某检测"。只描述实际执行的操作与已验证的结果。

## 环境备忘

- PowerShell 工具在本机不回显 stdout，跑脚本请用 Bash。
- Bash 工具每条命令开头加 `export PATH="/usr/bin:/bin:$PATH"`，否则 `ls`/`dirname` 等会报 command not found。
- 本机 Python 默认环境**没有** pillow/numpy；必须用上面的 venv 解释器路径，或用 `install_binary` 装上依赖。
