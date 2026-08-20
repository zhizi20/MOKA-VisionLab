# MOKA-VisionLab

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

双击仓库根目录的 `start.bat`。不要用 `powershell -File start.ps1` 作为首选（旧脚本会因编码解析失败）。

会弹出「后端」「前端」两个黑窗口，并打开浏览器。关掉那两个窗口即停止服务。

| 用途 | 地址 |
|------|------|
| **网页界面（用这个）** | http://127.0.0.1:5174 |
| 登录页 | http://127.0.0.1:5174/login |
| 后端 API（不是页面） | http://127.0.0.1:8000 |
| 健康检查 | http://127.0.0.1:8000/api/health |

默认账号 `admin` / `admin123`。局域网同一网段可用本机 IP 的 `5174` 端口。

首次需要环境时：

```powershell
powershell -File backend\scripts\setup_venv.ps1
cd frontend
npm install
```

只开后端、不经过前端时，浏览器访问 `http://127.0.0.1:8000/` 会看到说明页。

也可手动启动：

```powershell
# 后端（在 backend 目录）
.\.venv\Scripts\python.exe app.py

# 前端（另开终端，frontend 目录）
npm run dev
```

## 推荐流程

1. 模型管理 → 一键登记 YOLO11n（首次会从 HuggingFace 镜像 / GitHub 代理下载权重；直连 github.com 在国内常超时）
2. 数据集 → 新建类别 → 上传图片或视频抽帧
3. 标注 → 画框 / 预标 / SAM 点选 → 保存
4. 数据集 → 构建（至少 2 张已标注图）
5. 训练任务 → 创建并启动。本机 CPU 默认保护：batch≤4、imgsz≤640。更好的机器在 `backend/.env` 写 `DETECTLAB_CPU_SAFE=0` 后重启后端即可放松限制。
6. 用产出的 `best.pt` 做图片/视频检测

SQLite 文件在 `backend/app.db`。本地文件在 `backend/uploads/`，按名称分目录：

```
uploads/
  datasets/<数据集名>/     raw 图、标注、yolo/data.yaml
  training/<任务名>/       训练日志与曲线图
  models/builtin/          官方 YOLO 权重
  models/custom/           上传的权重
  models/trained/          训练产出的 best.pt
  videos/source/           检测/抽帧用的原视频
  videos/results/          检测结果视频
  tmp/                     临时 ndjson
```
