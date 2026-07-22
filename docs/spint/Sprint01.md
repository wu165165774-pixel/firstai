# Sprint 01：工程初始化（v0.1.0）

## 目标

建立 NovelForge 的基础工程，使项目能够：

-   使用 Docker Compose 启动
-   运行 FastAPI
-   通过 `/api/v1/health` 提供健康检查
-   使用 `.env` 管理配置
-   为后续多模型、Memory、RAG 打下基础

------------------------------------------------------------------------

## 技术栈

-   Python 3.12
-   FastAPI
-   Uvicorn
-   Docker / Docker Compose
-   Pydantic Settings
-   Loguru
-   Git

------------------------------------------------------------------------

## 当前目录（核心）

``` text
backend/
├── app/
│   ├── api/
│   ├── config/
│   ├── core/
│   └── main.py
├── Dockerfile
├── pyproject.toml
├── .env
└── .env.example
```

------------------------------------------------------------------------

## 已完成内容

-   项目目录初始化
-   Dockerfile
-   docker-compose.yml
-   FastAPI 启动
-   Health API
-   基础配置读取
-   Git 初始化

------------------------------------------------------------------------

## Docker

启动：

``` bash
docker compose up --build
```

停止：

``` bash
docker compose down
```

查看容器：

``` bash
docker ps
```

------------------------------------------------------------------------

## Health API

地址：

``` text
GET /api/v1/health
```

Swagger：

``` text
http://localhost:18080/docs
```

------------------------------------------------------------------------

## Git

首次版本：

``` bash
git add .
git commit -m "feat: initialize backend foundation"
git tag v0.1.0
```

------------------------------------------------------------------------

## 本 Sprint 踩坑记录

### 1. Dockerfile CMD

错误：

``` text
unknown instruction: "uvicorn"
```

原因：

JSON 形式的 CMD 被错误换行。

正确写法：

``` dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2. docker-compose YAML

错误：

``` text
mapping values are not allowed in this context
```

原因：

YAML 缩进或粘贴格式错误。

------------------------------------------------------------------------

## Sprint 01 验收

-   [x] Docker 构建成功
-   [x] FastAPI 启动成功
-   [x] Swagger 可访问
-   [x] Health API 正常
-   [x] Git 可提交

------------------------------------------------------------------------

## 下一 Sprint

Sprint 02：Core Framework

将完成：

-   统一响应
-   错误码
-   全局异常
-   日志升级
-   中间件基础
