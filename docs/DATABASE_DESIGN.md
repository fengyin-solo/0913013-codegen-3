# 数据库设计文档

## 概述

本文档描述了SeismicVision系统的数据库设计，包括数据模型、表结构、索引设计和数据关系。

## 数据库选型

- **主数据库**: PostgreSQL 15
  - 支持复杂查询和事务
  - 支持JSON类型存储灵活数据
  - 优秀的并发性能
  - 支持空间数据扩展（PostGIS可选）

- **缓存数据库**: Redis 7
  - 用于缓存热点切片数据
  - 会话管理
  - 任务队列

## ER图

```
users ─────┐
   │       │
   │       └─ created_by ── projects
   │                           │
   └─ project_members ─────────┘
                               │
                               ├─ seismic_data ─────┐
                               │                    │
                               │                    ├─ seismic_slices
                               │                    │
                               │                    └─ annotations
                               │
                               └─ wells ── well_logs
```

## 表结构详解

### 1. 用户表 (users)

存储系统用户信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 用户ID |
| username | VARCHAR(50) | UNIQUE NOT NULL | 用户名 |
| email | VARCHAR(100) | UNIQUE NOT NULL | 邮箱 |
| hashed_password | VARCHAR(255) | NOT NULL | 哈希后的密码 |
| full_name | VARCHAR(100) | | 全名 |
| is_active | BOOLEAN | DEFAULT true | 是否激活 |
| is_admin | BOOLEAN | DEFAULT false | 是否管理员 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | | 更新时间 |

**索引**:
- `idx_users_username` ON users(username)
- `idx_users_email` ON users(email)

---

### 2. 项目表 (projects)

存储项目基本信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 项目ID |
| name | VARCHAR(200) | NOT NULL | 项目名称 |
| description | TEXT | | 项目描述 |
| created_by | INTEGER | REFERENCES users(id) | 创建者ID |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | | 更新时间 |

**索引**:
- `idx_projects_created_by` ON projects(created_by)
- `idx_projects_name` ON projects(name)

---

### 3. 项目成员表 (project_members)

管理项目成员及其角色。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键ID |
| project_id | INTEGER | REFERENCES projects(id) NOT NULL | 项目ID |
| user_id | INTEGER | REFERENCES users(id) NOT NULL | 用户ID |
| role | VARCHAR(20) | DEFAULT 'viewer' | 角色: viewer/editor/owner |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 添加时间 |

**索引**:
- `idx_project_members_project_user` ON project_members(project_id, user_id) UNIQUE
- `idx_project_members_user` ON project_members(user_id)

**角色说明**:
- `viewer`: 查看者，只能查看数据
- `editor`: 编辑者，可以上传、编辑数据，创建标注
- `owner`: 所有者，拥有所有权限，可管理成员

---

### 4. 地震数据表 (seismic_data)

存储地震数据的元信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 数据ID |
| project_id | INTEGER | REFERENCES projects(id) NOT NULL | 项目ID |
| name | VARCHAR(200) | NOT NULL | 数据名称 |
| description | TEXT | | 描述 |
| file_type | VARCHAR(20) | DEFAULT 'segy' | 文件类型 |
| file_path | VARCHAR(500) | | 存储路径 |
| storage_type | VARCHAR(20) | DEFAULT 'minio' | 存储类型 |
| file_size | FLOAT | | 文件大小(字节) |
| **维度信息** | | | |
| inline_start | INTEGER | | Inline起始值 |
| inline_end | INTEGER | | Inline结束值 |
| inline_step | INTEGER | | Inline步长 |
| crossline_start | INTEGER | | Crossline起始值 |
| crossline_end | INTEGER | | Crossline结束值 |
| crossline_step | INTEGER | | Crossline步长 |
| depth_start | FLOAT | | 深度/时间起始 |
| depth_end | FLOAT | | 深度/时间结束 |
| depth_step | FLOAT | | 深度/时间步长 |
| num_inlines | INTEGER | | Inline数量 |
| num_crosslines | INTEGER | | Crossline数量 |
| num_depths | INTEGER | | 深度采样数 |
| **统计信息** | | | |
| min_value | FLOAT | | 最小值 |
| max_value | FLOAT | | 最大值 |
| mean_value | FLOAT | | 平均值 |
| std_value | FLOAT | | 标准差 |
| **状态信息** | | | |
| status | VARCHAR(20) | DEFAULT 'uploading' | 状态 |
| upload_progress | FLOAT | DEFAULT 0.0 | 上传进度 |
| error_message | TEXT | | 错误信息 |
| created_by | INTEGER | REFERENCES users(id) | 上传者ID |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | | 更新时间 |

**索引**:
- `idx_seismic_project` ON seismic_data(project_id)
- `idx_seismic_status` ON seismic_data(status)
- `idx_seismic_created_by` ON seismic_data(created_by)

**状态说明**:
- `uploading`: 上传中
- `processing`: 处理中（解析SEG-Y）
- `ready`: 就绪
- `error`: 错误

---

### 5. 地震切片表 (seismic_slices)

缓存预生成的切片数据。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 切片ID |
| seismic_data_id | INTEGER | REFERENCES seismic_data(id) NOT NULL | 地震数据ID |
| slice_type | VARCHAR(20) | NOT NULL | 切片类型: inline/crossline/depth |
| slice_index | INTEGER | NOT NULL | 切片索引 |
| data_path | VARCHAR(500) | | 原始数据路径 |
| thumbnail_path | VARCHAR(500) | | 缩略图路径 |
| width | INTEGER | | 宽度 |
| height | INTEGER | | 高度 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 创建时间 |

**索引**:
- `idx_slices_seismic_type_index` ON seismic_slices(seismic_data_id, slice_type, slice_index) UNIQUE

---

### 6. 井表 (wells)

存储井位信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 井ID |
| project_id | INTEGER | REFERENCES projects(id) NOT NULL | 项目ID |
| name | VARCHAR(100) | NOT NULL | 井名 |
| uwi | VARCHAR(50) | | 统一井标识 |
| x | FLOAT | | X坐标 |
| y | FLOAT | | Y坐标 |
| kb_elevation | FLOAT | | 补心海拔 |
| total_depth | FLOAT | | 总深度 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 创建时间 |

**索引**:
- `idx_wells_project` ON wells(project_id)
- `idx_wells_uwi` ON wells(uwi)

---

### 7. 测井曲线表 (well_logs)

存储测井曲线数据。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 曲线ID |
| well_id | INTEGER | REFERENCES wells(id) NOT NULL | 井ID |
| log_name | VARCHAR(50) | NOT NULL | 曲线名称 |
| log_type | VARCHAR(50) | | 曲线类型 |
| unit | VARCHAR(20) | | 单位 |
| depth_start | FLOAT | | 起始深度 |
| depth_end | FLOAT | | 结束深度 |
| depth_step | FLOAT | | 采样间隔 |
| data_path | VARCHAR(500) | | 数据路径 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 创建时间 |

**索引**:
- `idx_logs_well` ON well_logs(well_id)

---

### 8. 标注表 (annotations)

存储用户创建的标注信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 标注ID |
| seismic_data_id | INTEGER | REFERENCES seismic_data(id) NOT NULL | 地震数据ID |
| owner_id | INTEGER | REFERENCES users(id) NOT NULL | 所有者ID |
| name | VARCHAR(200) | | 标注名称 |
| annotation_type | VARCHAR(50) | NOT NULL | 标注类型 |
| geometry | JSON | | 几何数据(GeoJSON) |
| properties | JSON | | 属性数据 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | | 更新时间 |

**索引**:
- `idx_annotations_seismic` ON annotations(seismic_data_id)
- `idx_annotations_owner` ON annotations(owner_id)
- `idx_annotations_type` ON annotations(annotation_type)

**标注类型**:
- `point`: 点标注
- `line`: 线标注
- `polygon`: 多边形标注
- `horizon`: 层位解释
- `fault`: 断层解释

---

### 9. 处理任务表 (processing_tasks)

跟踪数据处理任务。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 任务ID |
| task_type | VARCHAR(50) | NOT NULL | 任务类型 |
| seismic_data_id | INTEGER | REFERENCES seismic_data(id) | 关联地震数据 |
| status | VARCHAR(20) | DEFAULT 'pending' | 状态 |
| progress | FLOAT | DEFAULT 0.0 | 进度(0-100) |
| parameters | JSON | | 任务参数 |
| result_path | VARCHAR(500) | | 结果路径 |
| error_message | TEXT | | 错误信息 |
| created_by | INTEGER | REFERENCES users(id) | 创建者 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 创建时间 |
| started_at | TIMESTAMPTZ | | 开始时间 |
| completed_at | TIMESTAMPTZ | | 完成时间 |

**索引**:
- `idx_tasks_status` ON processing_tasks(status)
- `idx_tasks_created_by` ON processing_tasks(created_by)

**任务类型**:
- `segy_import`: SEG-Y导入
- `slice_generation`: 切片预生成
- `attribute_computation`: 属性计算
- `noise_suppression`: 噪声压制

## 数据库优化建议

### 外键与级联策略

| 子表 | 外键 | 删除父记录时 |
|------|------|--------------|
| project_members | project_id → projects.id, user_id → users.id | `ON DELETE CASCADE` |
| seismic_data | project_id → projects.id | `ON DELETE CASCADE` |
| seismic_slices | seismic_data_id → seismic_data.id | `ON DELETE CASCADE` |
| wells | project_id → projects.id | `ON DELETE CASCADE` |
| well_logs | well_id → wells.id | `ON DELETE CASCADE` |
| annotations | seismic_data_id → seismic_data.id, owner_id → users.id | `ON DELETE CASCADE` |
| processing_tasks | seismic_data_id → seismic_data.id | `ON DELETE SET NULL` |

数据体批量转移只更新 `seismic_data.project_id`（数据体的 id 不变），因此 `seismic_slices`、`annotations` 等下游记录无需改动，归属自动随数据体变更。

### 索引策略
1. 所有外键字段创建索引
2. 频繁查询的组合字段创建复合索引
3. 大表考虑分区（按项目或时间）

### 查询优化
1. 使用EXPLAIN ANALYZE分析慢查询
2. 适当使用物化视图缓存统计数据
3. 地震数据元信息查询走索引，避免全表扫描

### 备份策略
1. 每日全量备份 + 增量备份
2. 关键表（users, projects, seismic_data）实时备份
3. 大对象存储（MinIO）独立备份策略

### 性能调优
1. `shared_buffers`: 系统内存的25%
2. `work_mem`: 4MB-64MB，根据查询复杂度调整
3. `maintenance_work_mem`: 64MB-256MB
4. `effective_cache_size`: 系统内存的50%-75%

## 数据迁移

使用Alembic进行数据库版本管理：

```bash
# 创建迁移脚本
alembic revision --autogenerate -m "description"

# 执行迁移
alembic upgrade head

# 回滚
alembic downgrade -1
```
