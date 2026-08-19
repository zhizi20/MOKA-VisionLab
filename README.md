# AI-DetectLab

本地视觉检测实验室：登记 YOLO 权重、图片/视频检测、画框标注（含 YOLO 预标与 MobileSAM 点选），再训练并回写模型库。

默认账号 `admin` / `admin123`。后端 **8000**，前端 **5174**。

## 功能

- 登录（JWT，无注册、无 RBAC）
- 模型管理：上传 `.pt`，或一键登记 Ultralytics 内置 `yolo11n.pt`
- 图片检测、视频检测（异步任务 + 下载结果）
- 数据集：上传图片、视频抽帧、划分 train/val、生成 `data.yaml`
- 标注：Canvas 画框、YOLO 预标、MobileSAM 点击生成框
- 训练：Ultralytics `YOLO.train`，`best.pt` 自动登记到模型列表

## 环境

- Python 3.12（推荐独立 `backend/.venv`）
- Node.js 18+
- CPU 可跑；有 NVIDIA GPU 时训练页可选 GPU 0

不使用 HuggingFace / ModelScope 拉取、不做 pt→onnx、不接 CVAT。SAM 走 Ultralytics `SAM("mobile_sam.pt")`。

## 启动

```powershell
# 后端（在 backend 目录）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py

# 前端（另开终端，frontend 目录）
npm install
npm run dev
```

也可运行 `backend\scripts\setup_venv.ps1` 再 `backend\scripts\run_backend.ps1`。

浏览器打开 http://127.0.0.1:5174

## 推荐流程

1. 模型管理 → 一键登记 YOLO11n（首次推理会下载权重）
2. 数据集 → 新建类别 → 上传图片或视频抽帧
3. 标注 → 画框 / 预标 / SAM 点选 → 保存
4. 数据集 → 构建（至少 2 张已标注图）
5. 训练任务 → 创建并启动（CPU 会较慢）
6. 用产出的 `best.pt` 做图片/视频检测

SQLite 文件在 `backend/app.db`，上传与训练产物在 `backend/uploads/`。
