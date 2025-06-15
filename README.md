# 文档统计分析系统

一个基于Flask的飞书文档统计分析系统，支持Wiki和Docx文档的访问数据统计和可视化分析。

## 功能特性

- 📊 **文档统计**: 获取飞书Wiki和Docx文档的访问统计信息
- 🔐 **用户授权**: 支持飞书用户授权，使用个人访问令牌
- 🌐 **ngrok集成**: 支持ngrok隧道，本地开发时可生成公网可访问的重定向URI
- 📈 **数据可视化**: 提供多种图表展示统计数据
- 🌳 **树形结构**: 支持Wiki文档的层级结构展示
- 🎯 **批量处理**: 支持同时分析多个文档链接

## 新增功能：ngrok 隧道管理

### 功能概述

为了方便本地开发测试飞书授权功能，系统集成了 ngrok 隧道管理功能：

- **自动隧道管理**: 通过 Web 界面管理 ngrok 隧道
- **动态重定向URI**: 自动生成公网可访问的重定向 URI
- **一键配置**: 复制重定向 URI 到飞书开放平台
- **状态监控**: 实时查看隧道状态和连接信息

### 使用方法

1. **访问管理页面**: 打开 `http://localhost:5000/ngrok`
2. **启动隧道**: 点击"启动 ngrok 隧道"按钮
3. **获取重定向URI**: 复制生成的重定向 URI
4. **配置飞书应用**: 在飞书开放平台设置重定向 URL
5. **测试授权**: 使用公网 URL 测试飞书授权功能

### 环境变量配置

在 `.env` 文件中添加：

```env
# 启用 ngrok 功能
USE_NGROK=true
```

## 新增功能：飞书用户授权

### 授权流程

1. **前端授权**: 用户在前端页面点击"飞书授权"按钮
2. **跳转授权**: 系统跳转到飞书授权页面
3. **用户确认**: 用户在飞书页面确认授权
4. **获取令牌**: 系统使用授权码获取user_access_token
5. **JWT存储**: 将user_access_token封装为JWT token存储在浏览器sessionStorage中
6. **数据访问**: 使用JWT token访问文档数据

### 授权优势

- **个人权限**: 使用用户个人权限访问文档，无需应用权限
- **安全可靠**: 通过飞书官方授权流程，安全可靠
- **动态管理**: 支持动态授权和退出授权
- **状态检查**: 实时检查授权状态
- **JWT存储**: 使用JWT token安全存储，30分钟自动过期
- **无状态**: 不依赖服务器session，支持分布式部署

### JWT Token特性

- **存储位置**: 浏览器sessionStorage（页面关闭后自动清除）
- **过期时间**: 30分钟自动过期
- **安全机制**: 使用HS256算法签名，防止篡改
- **无刷新**: 不包含refresh_token，过期后需要重新授权
- **自动清理**: 过期后自动清除，需要重新授权

## 安装和配置

### 1. 环境要求

- Python 3.7+
- Flask
- lark-oapi
- ngrok (可选，用于本地开发)

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

创建 `.env` 文件并配置以下变量：

```env
# 飞书应用配置
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret

# 可选：默认用户访问令牌（如果不使用授权功能）
FEISHU_USER_ACCESS_TOKEN=your_user_access_token

# JWT配置（可选，系统会自动生成）
JWT_SECRET=your_jwt_secret_key

# ngrok配置（可选，用于本地开发）
USE_NGROK=true
```

### 4. 飞书应用配置

1. 在[飞书开放平台](https://open.feishu.cn/)创建应用
2. 配置应用权限：
   - `authen:user_access_token` - 获取用户访问令牌
   - `wiki:wiki:read` - 读取Wiki文档
   - `drive:file:read` - 读取文档文件
3. 配置重定向URL：
   - 生产环境：`https://your-domain.com/auth/callback`
   - 本地开发：使用 ngrok 生成的重定向 URI

## 使用方法

### 1. 启动服务

```bash
python flask_app.py
```

### 2. 访问系统

打开浏览器访问 `http://localhost:5000`

### 3. ngrok 隧道管理（本地开发）

1. 访问 `http://localhost:5000/ngrok`
2. 启动 ngrok 隧道
3. 复制重定向 URI
4. 在飞书开放平台配置重定向 URL
5. 使用公网 URL 测试授权功能

### 4. 授权流程

1. 点击"飞书授权"按钮
2. 在飞书授权页面确认授权
3. 授权成功后返回系统
4. 开始分析文档数据

### 5. 分析文档

1. 添加飞书文档链接
2. 点击"开始分析"
3. 查看统计结果和图表

## API接口

### ngrok 管理接口

- `GET /ngrok` - ngrok 管理页面
- `GET /ngrok/start` - 启动 ngrok 隧道
- `GET /ngrok/stop` - 停止 ngrok 隧道
- `GET /ngrok/status` - 获取隧道状态
- `GET /ngrok/redirect-uri` - 获取重定向 URI

### 授权相关接口

- `GET /auth` - 跳转到飞书授权页面
- `GET /auth/callback` - 处理授权回调
- `GET /auth/status` - 获取授权状态
- `GET /auth/logout` - 退出授权

### 数据接口

- `POST /stats` - 获取文档统计信息

## 测试功能

### 基础测试

访问 `http://localhost:5000/test` 可以测试系统各项功能：

- API连接测试
- 授权功能测试
- 图表渲染测试
- 链接解析测试

### ngrok 功能测试

```bash
python test_ngrok.py
```

### 授权功能测试

```bash
python test_auth.py
```

## 注意事项

1. **ngrok 使用**: 仅用于本地开发测试，生产环境请使用固定域名
2. **授权有效期**: user_access_token有有效期限制，过期需要重新授权
3. **权限范围**: 只能访问用户有权限的文档
4. **安全考虑**: 在生产环境中应使用数据库存储token
5. **HTTPS**: 生产环境建议使用HTTPS

## 故障排除

### ngrok 相关问题

- **隧道启动失败**: 检查网络连接和 ngrok 安装
- **重定向 URI 无效**: 确保在飞书开放平台正确配置
- **隧道连接不稳定**: 检查防火墙设置

### 授权失败

- 检查应用配置是否正确
- 确认重定向URL配置
- 检查应用权限设置

### 数据获取失败

- 确认用户对文档有访问权限
- 检查token是否过期
- 验证文档链接格式

## 开发说明

### 核心文件

- `flask_app.py` - 主应用文件
- `auth_utils.py` - 授权相关功能
- `ngrok_utils.py` - ngrok 隧道管理
- `doc_stats_utils.py` - 文档解析和统计功能
- `templates/index.html` - 主页面
- `templates/ngrok.html` - ngrok 管理页面
- `templates/test.html` - 测试页面

### 主要功能模块

- 授权管理模块
- ngrok 隧道管理模块
- 文档解析模块
- 数据统计模块
- 可视化模块

## 许可证

MIT License 