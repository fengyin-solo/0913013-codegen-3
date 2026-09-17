# API接口说明

## 概述

SeismicVision提供RESTful API接口，用于地震数据的上传、管理、可视化和分析。所有接口均采用JSON格式进行数据交换。

## 基础信息

- **Base URL**: `http://localhost:8000/api/v1`
- **认证方式**: Bearer Token (JWT)
- **数据格式**: JSON
- **字符编码**: UTF-8

## 认证

所有需要认证的接口必须在请求头中携带Token：

```
Authorization: Bearer <access_token>
```

### 获取Token

**POST** `/auth/login`

请求体 (application/x-www-form-urlencoded):
```
username: admin
password: admin123
```

响应:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

## 接口列表

---

## 1. 认证接口 (Auth)

### 1.1 用户登录

**POST** `/auth/login`

获取访问令牌。

### 1.2 用户注册

**POST** `/auth/register`

请求体:
```json
{
  "username": "string",
  "email": "user@example.com",
  "password": "string",
  "full_name": "string"
}
```

### 1.3 获取当前用户信息

**GET** `/auth/me`

需要认证。

响应:
```json
{
  "id": 1,
  "username": "admin",
  "email": "admin@seismic.local",
  "full_name": "System Administrator",
  "is_active": true,
  "is_admin": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

### 1.4 更新当前用户信息

**PUT** `/auth/me`

---

## 2. 项目接口 (Projects)

### 2.1 获取项目列表

**GET** `/projects`

获取当前用户有权限访问的所有项目。

### 2.2 创建项目

**POST** `/projects`

请求体:
```json
{
  "name": "油田A区块",
  "description": "油田A区块三维地震勘探数据"
}
```

### 2.3 获取项目详情

**GET** `/projects/{project_id}`

### 2.4 更新项目

**PUT** `/projects/{project_id}`

### 2.5 删除项目

**DELETE** `/projects/{project_id}`

### 2.6 获取项目成员列表

**GET** `/projects/{project_id}/members`

### 2.7 添加项目成员

**POST** `/projects/{project_id}/members`

请求体:
```json
{
  "user_id": 2,
  "role": "editor"
}
```

### 2.8 更新成员角色

**PUT** `/projects/{project_id}/members/{member_id}`

### 2.9 移除项目成员

**DELETE** `/projects/{project_id}/members/{member_id}`

### 2.10 批量分配协作成员

**POST** `/projects/batch/assign-collaborator`

请求体:
```json
{
  "project_ids": [1, 2, 3],
  "user_id": 5,
  "role": "editor"
}
```

逐条独立提交，单条失败不影响其他条目；请求中途取消或超时，已成功提交的条目不会回退。

响应 (HTTP 200，逐条结果):
```json
{
  "action": "assign_collaborator",
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "results": [
    {
      "project_id": 1,
      "project_name": "工区A",
      "success": true,
      "message": "已将成员「zhangsan」以编辑者身份加入项目「工区A」",
      "error_code": null
    },
    {
      "project_id": 2,
      "project_name": "工区B",
      "success": false,
      "message": "成员「zhangsan」已经是该项目的编辑者，无需重复添加",
      "error_code": "already_member"
    }
  ]
}
```

### 2.11 批量转移数据体

**POST** `/projects/batch/transfer-seismic-data`

请求体:
```json
{
  "project_ids": [1, 2, 3],
  "target_project_id": 9
}
```

将每个源项目下的全部地震数据体（`seismic_data`，切片与标注通过外键随之归属新的项目）转入目标项目；井数据保留在原项目。同样逐条独立提交，不回退已完成项。

### 2.12 单条分配协作成员（批量逐条执行/重试使用）

**POST** `/projects/{project_id}/collaborator`

请求体:
```json
{ "user_id": 5, "role": "editor" }
```

成功返回创建的成员记录。失败时 `detail` 为结构化对象：
```json
{ "detail": { "error_code": "already_member", "message": "成员「zhangsan」已经是该项目的编辑者，无需重复添加" } }
```

### 2.13 单条转移数据体（批量逐条执行/重试使用）

**POST** `/projects/{project_id}/seismic-transfer`

请求体:
```json
{ "target_project_id": 9 }
```

成功返回：
```json
{ "message": "已将项目「工区A」的 3 个数据体转移到项目「汇总工区」" }
```

### 批量操作错误码

结构化错误的 `detail.error_code` 取值：

| error_code | HTTP 状态码 | 含义 |
|------------|-------------|------|
| `not_found` | 404 | 源项目不存在，提交前已被其他用户删除 |
| `target_not_found` | 404 | 目标项目不存在，可能已被删除 |
| `forbidden` | 403 | 当前用户对源项目没有所需权限（分配成员需 owner，转移需 editor） |
| `target_unavailable` | 400 | 目标项目不可用：对目标项目没有编辑权限，无法转入 |
| `invalid_target` | 400 | 目标项目与源项目相同 |
| `duplicate_name` | 409 | 目标项目下存在同名数据体，消息中列出冲突名称，重命名后可重试 |
| `already_member` | 409 | 该成员已经是项目成员 |
| `user_not_found` | 404 | 指定的协作成员不存在或已停用 |
| `invalid_role` | 400 | 角色不合法（仅允许 viewer/editor/owner） |
| `internal_error` | 500 | 服务器内部错误（批量聚合接口中单条隔离时出现） |

### 2.14 用户列表（选择协作成员）

**GET** `/auth/users`

返回全部活跃用户，用于批量分配协作成员时的成员选择器。

---

## 3. 地震数据接口 (Seismic Data)

### 3.1 获取项目地震数据列表

**GET** `/seismic/project/{project_id}`

### 3.2 上传地震数据

**POST** `/seismic/project/{project_id}/upload`

使用multipart/form-data上传SEG-Y文件。

请求参数:
- `name`: 数据名称
- `description`: 数据描述
- `file`: SEG-Y文件

### 3.3 获取地震数据详情

**GET** `/seismic/{seismic_id}`

响应示例:
```json
{
  "id": 1,
  "project_id": 1,
  "name": "工区A_2024",
  "description": "工区A三维地震数据",
  "file_type": "segy",
  "file_size": 524288000,
  "status": "ready",
  "upload_progress": 100,
  "created_by": 1,
  "created_at": "2024-01-01T00:00:00Z",
  "inline_start": 100,
  "inline_end": 500,
  "inline_step": 1,
  "crossline_start": 1000,
  "crossline_end": 1500,
  "crossline_step": 1,
  "depth_start": 0,
  "depth_end": 4000,
  "depth_step": 2,
  "num_inlines": 401,
  "num_crosslines": 501,
  "num_depths": 2001,
  "min_value": -12500,
  "max_value": 15000,
  "mean_value": 0.05,
  "std_value": 1250.5
}
```

### 3.4 删除地震数据

**DELETE** `/seismic/{seismic_id}`

### 3.5 获取切片数据

**GET** `/seismic/{seismic_id}/slice/{slice_type}/{slice_index}`

路径参数:
- `slice_type`: `inline`, `crossline`, `depth`
- `slice_index`: 切片索引

查询参数:
- `format`: `png` (默认) 或 `json`
- `colormap`: 颜色映射 (`seismic`, `gray`, `rainbow`)
- `min_value`: 最小值（用于归一化）
- `max_value`: 最大值（用于归一化）

示例请求:
```
GET /seismic/1/slice/inline/250?format=json
```

JSON格式响应:
```json
{
  "slice_type": "inline",
  "slice_index": 250,
  "data": [[...]],
  "shape": [501, 2001],
  "min": -12500,
  "max": 15000
}
```

### 3.6 获取子体积数据

**POST** `/seismic/{seismic_id}/subvolume`

查询参数:
- `inline_start`, `inline_end`: Inline范围
- `crossline_start`, `crossline_end`: Crossline范围
- `depth_start`, `depth_end`: 深度范围

响应:
```json
{
  "shape": [100, 100, 200],
  "data": [...],
  "bounds": {
    "inline": [200, 300],
    "crossline": [1200, 1300],
    "depth": [1000, 3000]
  }
}
```

### 3.7 空间测量

**POST** `/seismic/measurement`

请求体:
```json
{
  "points": [
    {"x": 0, "y": 0, "z": 0},
    {"x": 100, "y": 0, "z": 0}
  ],
  "measurement_type": "distance"
}
```

测量类型:
- `distance`: 距离测量（需要2个点）
- `area`: 面积测量（需要3+个点）
- `volume`: 体积测量（需要4+个点）

响应:
```json
{
  "measurement_type": "distance",
  "value": 100.0,
  "unit": "m",
  "points": [...]
}
```

---

## 4. 标注接口 (Annotations)

### 4.1 获取地震数据标注列表

**GET** `/annotations/seismic/{seismic_id}`

### 4.2 创建标注

**POST** `/annotations`

请求体:
```json
{
  "seismic_data_id": 1,
  "name": "砂体1",
  "annotation_type": "polygon",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[x1,y1,z1], [x2,y2,z2], ...]]
  },
  "properties": {
    "reservoir": "A段",
    "thickness": 25.5
  }
}
```

### 4.3 获取标注详情

**GET** `/annotations/{annotation_id}`

### 4.4 更新标注

**PUT** `/annotations/{annotation_id}`

### 4.5 删除标注

**DELETE** `/annotations/{annotation_id}`

---

## 5. 井数据接口 (Wells)

### 5.1 获取项目井列表

**GET** `/wells/project/{project_id}`

### 5.2 创建井

**POST** `/wells`

请求体:
```json
{
  "project_id": 1,
  "name": "A-1井",
  "uwi": "CN-0001-A",
  "x": 123456.78,
  "y": 987654.32,
  "kb_elevation": 50.5,
  "total_depth": 3500.0
}
```

### 5.3 获取井详情

**GET** `/wells/{well_id}`

### 5.4 更新井信息

**PUT** `/wells/{well_id}`

### 5.5 删除井

**DELETE** `/wells/{well_id}`

---

## 错误响应

所有错误响应格式统一:

```json
{
  "detail": "错误描述信息"
}
```

常见HTTP状态码:

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 400 | 请求参数错误 |
| 401 | 未授权 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## WebSocket接口 (可选)

### 实时数据更新

**连接**: `ws://localhost:8000/ws/seismic/{seismic_id}`

用于实时接收切片加载进度、处理任务状态等更新。

---

## 限流策略

- 认证接口: 10次/分钟/IP
- 数据上传: 2次/分钟/用户
- 查询接口: 100次/分钟/用户
- 切片获取: 60次/分钟/用户

---

## 示例代码

### Python (requests)

```python
import requests

BASE_URL = "http://localhost:8000/api/v1"

# 登录
response = requests.post(
    f"{BASE_URL}/auth/login",
    data={"username": "admin", "password": "admin123"}
)
token = response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 获取项目列表
projects = requests.get(f"{BASE_URL}/projects", headers=headers)

# 获取切片
slice_image = requests.get(
    f"{BASE_URL}/seismic/1/slice/inline/250",
    headers=headers,
    params={"format": "png", "colormap": "seismic"}
)
```

### JavaScript (axios)

```javascript
import axios from 'axios';

const API = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

// 登录
const login = async (username, password) => {
  const form = new FormData();
  form.append('username', username);
  form.append('password', password);
  const res = await API.post('/auth/login', form);
  API.defaults.headers.common['Authorization'] = `Bearer ${res.data.access_token}`;
  return res.data;
};

// 获取切片图像
const getSlice = async (seismicId, type, index) => {
  const res = await API.get(`/seismic/${seismicId}/slice/${type}/${index}`, {
    params: { format: 'png' },
    responseType: 'blob'
  });
  return URL.createObjectURL(res.data);
};
```

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2024-01-01 | 初始版本 |
