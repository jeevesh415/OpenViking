# 操作级 Telemetry 设计

## 1. 背景与目标

OpenViking 需要一套统一的 telemetry 机制，用来描述一次操作在执行过程中的关键观测信息。当前已经落地的是操作级 telemetry，主要覆盖：

- 请求耗时统计
- token 消耗统计
- 检索、队列、内存提取等阶段的摘要指标

这里统一使用 `telemetry`，而不是 `trace`，原因是这套抽象未来不只服务于“单次操作链路”，还要能承载非操作级数据，例如：

- 服务整体 token 消耗
- 各类后端能力的延迟与错误率
- 存储、向量库、队列等组件级指标
- 基于 OpenTelemetry 的 exporter / backend 对接

当前实现只对“操作级 telemetry”提供正式接口，但抽象命名和结构已经为后续扩展预留空间。

## 2. 设计原则

### 2.1 详细信息显式按需返回

详细 telemetry 由调用方通过 `telemetry` 参数显式请求，当前对外协议只返回结构化 summary，不返回事件流。

### 2.3 字段名直接面向用户

内部打点名与对外 summary 字段名保持一致，避免额外的“内部名 -> 外部名”转换层。

### 2.4 缺失分组不返回

如果某类操作天然不会产出某个 summary 分组，则该分组直接省略，不返回空对象或全 `null` 字段。

例如：

- `resources.add_resource` 不一定有 `memory`
- `session.commit` 一般没有 `semantic_nodes`
- 某些操作没有向量检索，就不返回 `vector`

## 3. 当前支持范围

### 3.1 HTTP 接口

当前已接入 operation telemetry 的接口：

- `POST /api/v1/search/find`
- `POST /api/v1/search/search`
- `POST /api/v1/resources`
- `POST /api/v1/skills`
- `POST /api/v1/sessions/{session_id}/commit`

说明：

- `session.commit` 仅在 `wait=true` 的同步模式下支持返回 telemetry
- `wait=false` 的异步任务模式当前不支持 telemetry，请求时会返回 `INVALID_ARGUMENT`

### 3.2 SDK 接口

当前已接入 operation telemetry 的 SDK 方法：

- `add_resource`
- `add_skill`
- `find`
- `search`
- `commit_session`

本地嵌入式 client 和 HTTP client 都遵循同一套 telemetry 请求语义。

## 4. 响应模型

服务端仍使用统一响应包裹结构：

```json
{
  "status": "ok",
  "result": { "...": "..." },
  "time": 0.031,
  "telemetry": {
    "id": "tm_9f6f4d6b0d0c4f4d93ce5adf82e71c18",
    "summary": {
      "operation": "search.find",
      "status": "ok",
      "duration_ms": 31.224,
      "tokens": {
        "total": 24,
        "llm": {
          "input": 12,
          "output": 6,
          "total": 18
        },
        "embedding": {
          "total": 6
        }
      },
      "vector": {
        "searches": 3,
        "scored": 26,
        "passed": 8,
        "returned": 5,
        "scanned": 26,
        "scan_reason": ""
      }
    }
  }
}
```

说明：

- `telemetry` 只在调用方显式请求时返回
- `telemetry.id` 是不透明标识，只用于关联，不要求调用方解析语义

## 5. telemetry 请求语义

`telemetry` 字段支持两种形态：

### 5.1 布尔形态

```json
{
  "telemetry": true
}
```

语义：

- 返回 `telemetry.id + telemetry.summary`

### 5.2 对象形态

```json
{
  "telemetry": {
    "summary": true
  }
}
```

语义：

- `summary` 默认值为 `true`
- 适合只看结构化摘要

当前支持的合法组合如下：

| 请求值 | 语义 |
| --- | --- |
| `false` | 不返回 `telemetry` |
| `true` | 返回 `id + summary` |
| `{"summary": true}` | 返回 `id + summary` |
| `{"summary": false}` | 不返回 `telemetry` |

以下请求非法：

```json
{
  "telemetry": {
    "events": true
  }
}
```

原因是当前对外 telemetry 已收敛为 summary-only，不再接受事件流选择参数。

## 6. telemetry 的职责划分

### 6.1 `telemetry.summary`

`summary` 是结构化的操作摘要，用于：

- 调试
- 排障
- 离线分析
- 上报到外部观测系统

当前 summary 的核心字段包括：

- `operation`
- `status`
- `duration_ms`
- `tokens`
- `resource`
- `queue`
- `vector`
- `semantic_nodes`
- `memory`
- `errors`

其中：

- 顶层基础字段 `operation`、`status`、`duration_ms` 始终存在
- 其余分组按是否有产出决定是否返回
- 数值型 `0` 会在返回前自动省略；如果某个分组因此变为空对象，则整个分组一并省略

### 6.3 `telemetry.id`

`telemetry.id` 是请求级关联标识，用于把一次操作的 summary 与内部异步链路统计关联起来。

## 7. summary 字段约定

### 7.1 总体结构

当前对外返回的 telemetry 结构固定为：

```json
{
  "telemetry": {
    "id": "tm_xxx",
    "summary": {
      "operation": "session.commit",
      "status": "ok",
      "duration_ms": 48.1,
      "tokens": { "...": "..." },
      "resource": { "...": "..." },
      "vector": { "...": "..." },
      "queue": { "...": "..." },
      "semantic_nodes": { "...": "..." },
      "memory": { "...": "..." },
      "errors": { "...": "..." }
    }
  }
}
```

说明：

- `telemetry.id` 是请求级关联 ID
- `summary` 是本次操作的结构化摘要
- `summary.tokens`、`resource`、`vector`、`queue`、`semantic_nodes`、`memory`、`errors` 按需出现
- 数值型 `0` 字段默认不返回；`false`、`null`、非空字符串仍按原语义保留

### 7.2 顶层字段字典

#### `telemetry.id`

- 类型：`string`
- 含义：当前 operation collector 的不透明关联标识
- 出现条件：调用方请求 telemetry 且 `summary` 被返回时
- 备注：只用于关联内部异步链路，不保证可读语义

#### `summary.operation`

- 类型：`string`
- 含义：操作名
- 单位：无
- 出现条件：总是出现
- 当前常见值：`search.find`、`search.search`、`resources.add_resource`、`skills.add_skill`、`session.commit`

#### `summary.status`

- 类型：`string`
- 含义：collector 结束状态
- 单位：无
- 出现条件：总是出现
- 当前常见值：`ok`、`error`

#### `summary.duration_ms`

- 类型：`number`
- 含义：整个 operation 的总耗时
- 单位：毫秒
- 出现条件：总是出现
- 备注：这是请求级总耗时，不等于任一子分组耗时简单求和

### 7.3 `tokens` 字段字典

示例：

```json
{
  "tokens": {
    "llm": {
      "input": 11,
      "output": 7,
      "total": 18
    },
    "embedding": {
      "total": 1
    }
  }
}
```

#### `summary.tokens.total`

- 类型：`integer`
- 含义：本次操作累计 token 总量
- 单位：token
- 出现条件：累计值非 0 时出现
- 来源：LLM token 与 embedding token 的总和

#### `summary.tokens.llm.input`

- 类型：`integer`
- 含义：LLM 输入 token 累计值
- 单位：token
- 出现条件：累计值非 0 时出现

#### `summary.tokens.llm.output`

- 类型：`integer`
- 含义：LLM 输出 token 累计值
- 单位：token
- 出现条件：累计值非 0 时出现

#### `summary.tokens.llm.total`

- 类型：`integer`
- 含义：LLM 总 token 累计值
- 单位：token
- 出现条件：累计值非 0 时出现

#### `summary.tokens.embedding.total`

- 类型：`integer`
- 含义：embedding 模型 token 累计值
- 单位：token
- 出现条件：累计值非 0 时出现
- 备注：当前不区分 embedding input/output，只保留总量

### 7.4 `resource` 字段字典

资源导入过程摘要示例：

```json
{
  "resource": {
    "request": {
      "duration_ms": 152.3
    },
    "process": {
      "duration_ms": 101.7,
      "parse": {
        "duration_ms": 38.1,
        "warnings_count": 1
      },
      "finalize": {
        "duration_ms": 22.4
      },
      "summarize": {
        "duration_ms": 31.8
      }
    },
    "wait": {
      "duration_ms": 46.9
    },
    "watch": {
      "duration_ms": 0.8
    },
    "flags": {
      "wait": true,
      "build_index": true,
      "summarize": false,
      "watch_enabled": false
    }
  }
}
```

出现条件：

- 仅在 `resources.add_resource` 这类资源导入操作记录了 `resource.*` 指标时出现
- 该分组与 `queue`、`semantic_nodes` 是互补关系，可以同时出现
- 数值型 `0` 子字段会被省略；布尔 flag 即使为 `false` 仍保留

#### `summary.resource.request.duration_ms`

- 类型：`number`
- 含义：`add_resource` 请求主流程总耗时
- 单位：毫秒
- 备注：覆盖参数校验、资源处理、可选等待和可选 watch 管理

#### `summary.resource.process.duration_ms`

- 类型：`number`
- 含义：资源处理主流程耗时
- 单位：毫秒
- 备注：覆盖 parse、finalize、首次落盘和 summarize/vectorize 等资源处理步骤

#### `summary.resource.process.parse.duration_ms`

- 类型：`number`
- 含义：资源解析阶段耗时
- 单位：毫秒

#### `summary.resource.process.parse.warnings_count`

- 类型：`integer`
- 含义：解析阶段产生的 warning 数量
- 单位：条

#### `summary.resource.process.finalize.duration_ms`

- 类型：`number`
- 含义：`TreeBuilder.finalize_from_temp()` 阶段耗时
- 单位：毫秒

#### `summary.resource.process.summarize.duration_ms`

- 类型：`number`
- 含义：资源总结与向量化阶段耗时
- 单位：毫秒
- 备注：当前 `build_index=true` 时也会走该阶段，因为 vectorization 由 summarize 流程承载

#### `summary.resource.wait.duration_ms`

- 类型：`number`
- 含义：`wait=true` 时等待队列完成的耗时
- 单位：毫秒
- 备注：与 `summary.queue` 中的完成统计互补，不重复表达队列条数

#### `summary.resource.watch.duration_ms`

- 类型：`number`
- 含义：watch 任务创建、更新或取消的处理耗时
- 单位：毫秒

#### `summary.resource.flags.wait`

- 类型：`boolean`
- 含义：本次请求是否指定了 `wait=true`

#### `summary.resource.flags.build_index`

- 类型：`boolean`
- 含义：本次请求是否启用了 `build_index`

#### `summary.resource.flags.summarize`

- 类型：`boolean`
- 含义：本次请求是否显式启用了 `summarize`

#### `summary.resource.flags.watch_enabled`

- 类型：`boolean`
- 含义：本次请求是否启用了 watch 创建或更新
- 备注：仅当存在 watch manager、提供了 `to`、未跳过 watch 管理且 `watch_interval > 0` 时为 `true`

### 7.5 `queue` 字段字典

队列相关摘要示例：

```json
{
  "queue": {
    "semantic": {
      "processed": 1
    },
    "embedding": {
      "processed": 1
    }
  }
}
```

出现条件：

- 仅在 `resources.add_resource(wait=true)` 这类需要等待队列处理完成、并且实际记录了 queue 指标时出现

#### `summary.queue.semantic.processed`

- 类型：`integer`
- 含义：本次操作关联的 semantic queue 已处理消息数
- 单位：条

#### `summary.queue.semantic.error_count`

- 类型：`integer`
- 含义：本次操作关联的 semantic queue 错误数
- 单位：次

#### `summary.queue.embedding.processed`

- 类型：`integer`
- 含义：本次操作关联的 embedding queue 已处理消息数
- 单位：条

#### `summary.queue.embedding.error_count`

- 类型：`integer`
- 含义：本次操作关联的 embedding queue 错误数
- 单位：次

### 7.6 `vector` 字段字典

向量检索摘要示例：

```json
{
  "vector": {
    "searches": 2,
    "scored": 5,
    "passed": 3,
    "returned": 2,
    "scanned": 5,
    "scan_reason": ""
  }
}
```

出现条件：

- 仅在实际发生向量检索或向量候选过滤时出现，例如 `search.find`、`search.search`、memory dedup 等路径

#### `summary.vector.searches`

- 类型：`integer`
- 含义：向量检索调用次数
- 单位：次

#### `summary.vector.scored`

- 类型：`integer`
- 含义：被打分的候选向量数
- 单位：个

#### `summary.vector.passed`

- 类型：`integer`
- 含义：通过阈值或后续过滤条件的候选数
- 单位：个

#### `summary.vector.returned`

- 类型：`integer`
- 含义：最终返回给上层逻辑的结果数
- 单位：个

#### `summary.vector.scanned`

- 类型：`integer`
- 含义：底层扫描过的向量数
- 单位：个
- 备注：优先使用 gauge，缺失时回退到 counter

#### `summary.vector.scan_reason`

- 类型：`string`
- 含义：扫描策略说明或原因
- 单位：无
- 备注：未记录时返回空字符串

### 7.7 `semantic_nodes` 字段字典

语义 DAG / 节点级摘要示例：

```json
{
  "semantic_nodes": {
    "total": 4,
    "done": 3,
    "pending": 1
  }
}
```

出现条件：

- 仅在资源导入等待语义 DAG 完成且 DAG 统计可用时出现

#### `summary.semantic_nodes.total`

- 类型：`integer | null`
- 含义：本次操作关联 DAG 的总节点数

#### `summary.semantic_nodes.done`

- 类型：`integer | null`
- 含义：已完成节点数

#### `summary.semantic_nodes.pending`

- 类型：`integer | null`
- 含义：待处理节点数

#### `summary.semantic_nodes.running`

- 类型：`integer | null`
- 含义：处理中节点数

### 7.8 `memory` 字段字典

会话提交等 memory 提取类操作示例：

```json
{
  "memory": {
    "extracted": 4,
    "extract": {
      "duration_ms": 842.3,
      "candidates": {
        "total": 7,
        "standard": 5,
        "tool_skill": 2
      },
      "actions": {
        "created": 3,
        "merged": 1,
        "skipped": 3
      },
      "stages": {
        "prepare_inputs_ms": 8.4,
        "llm_extract_ms": 410.2,
        "normalize_candidates_ms": 6.7,
        "tool_skill_stats_ms": 1.9,
        "profile_create_ms": 12.5,
        "tool_skill_merge_ms": 43.0,
        "dedup_ms": 215.6,
        "create_memory_ms": 56.1,
        "merge_existing_ms": 22.7,
        "create_relations_ms": 18.2,
        "flush_semantic_ms": 9.0
      }
    }
  }
}
```

出现条件：

- `summary.memory` 仅在 session commit / memory extract 相关操作产出 memory 指标时出现
- `summary.memory.extract` 仅在 memory extract 细分指标存在时出现

#### `summary.memory.extracted`

- 类型：`integer | null`
- 含义：本次操作最终抽取出的 memory 数量
- 单位：个
- 备注：这是结果数，不是候选数

#### `summary.memory.extract.duration_ms`

- 类型：`number`
- 含义：`extract_long_term_memories()` 主流程总耗时
- 单位：毫秒

#### `summary.memory.extract.candidates.total`

- 类型：`integer`
- 含义：extract 阶段产出的候选总数
- 单位：个

#### `summary.memory.extract.candidates.standard`

- 类型：`integer`
- 含义：普通 memory candidate 数量，不含 tools/skills candidate
- 单位：个

#### `summary.memory.extract.candidates.tool_skill`

- 类型：`integer`
- 含义：tools/skills candidate 数量
- 单位：个

#### `summary.memory.extract.actions.created`

- 类型：`integer`
- 含义：最终新建的 memory 数量
- 单位：个

#### `summary.memory.extract.actions.merged`

- 类型：`integer`
- 含义：最终合并到已有 memory 或 tool/skill memory 的次数
- 单位：次

#### `summary.memory.extract.actions.deleted`

- 类型：`integer`
- 含义：最终删除旧 memory 的次数
- 单位：次

#### `summary.memory.extract.actions.skipped`

- 类型：`integer`
- 含义：最终被跳过的 candidate 数量
- 单位：个

#### `summary.memory.extract.stages.prepare_inputs_ms`

- 类型：`number`
- 含义：LLM 提取前的数据准备耗时
- 单位：毫秒
- 范围：ToolPart 收集、消息格式化、语言检测、prompt 渲染

#### `summary.memory.extract.stages.llm_extract_ms`

- 类型：`number`
- 含义：候选提取 LLM 调用耗时
- 单位：毫秒

#### `summary.memory.extract.stages.normalize_candidates_ms`

- 类型：`number`
- 含义：LLM 返回解析与普通 candidate 归一化耗时
- 单位：毫秒

#### `summary.memory.extract.stages.tool_skill_stats_ms`

- 类型：`number`
- 含义：tool/skill 统计聚合、名称校准与 tool/skill candidate 处理耗时
- 单位：毫秒

#### `summary.memory.extract.stages.profile_create_ms`

- 类型：`number`
- 含义：`profile` memory 的创建或更新耗时
- 单位：毫秒

#### `summary.memory.extract.stages.tool_skill_merge_ms`

- 类型：`number`
- 含义：tool memory / skill memory 合并耗时
- 单位：毫秒

#### `summary.memory.extract.stages.dedup_ms`

- 类型：`number`
- 含义：普通 candidate dedup 判定耗时
- 单位：毫秒

#### `summary.memory.extract.stages.create_memory_ms`

- 类型：`number`
- 含义：普通 candidate 新建 memory 的耗时
- 单位：毫秒

#### `summary.memory.extract.stages.merge_existing_ms`

- 类型：`number`
- 含义：普通 candidate 合并到已有 memory 的耗时
- 单位：毫秒

#### `summary.memory.extract.stages.delete_existing_ms`

- 类型：`number`
- 含义：删除旧 memory 的耗时
- 单位：毫秒

#### `summary.memory.extract.stages.create_relations_ms`

- 类型：`number`
- 含义：为新产出的 memory 创建 used URI relations 的耗时
- 单位：毫秒

#### `summary.memory.extract.stages.flush_semantic_ms`

- 类型：`number`
- 含义：semantic queue flush 的耗时
- 单位：毫秒

注意：

- `stages.*_ms` 是阶段累计耗时；同一阶段多次执行时会累加
- `summary.memory.extract.duration_ms` 是整个 extract 主流程耗时
- 两者不保证严格相加完全一致，因为还可能存在未单独拆出的逻辑、循环开销和控制流开销

### 7.9 `errors` 字段字典

发生错误时可返回：

```json
{
  "errors": {
    "stage": "resource_processor.parse",
    "error_code": "PROCESSING_ERROR",
    "message": "..."
  }
}
```

无错误时，该分组可以省略。

#### `summary.errors.stage`

- 类型：`string`
- 含义：错误记录时标记的逻辑阶段名

#### `summary.errors.error_code`

- 类型：`string`
- 含义：错误代码或异常类型

#### `summary.errors.message`

- 类型：`string`
- 含义：错误描述

## 8. 缺失字段裁剪策略

summary 采用“按分组裁剪”的策略，而不是固定返回整套字段。

这样做有几个直接收益：

- 避免返回大量与当前操作无关的空字段
- 降低调用方理解成本
- 更适合未来扩展新的 telemetry 分组

调用方应按“字段是否存在”来判断某类指标是否可用，而不是假设所有分组总会返回。

### 8.1 `resources.add_resource`

可能返回：

```json
{
  "operation": "resources.add_resource",
  "status": "ok",
  "duration_ms": 152.3,
  "tokens": { "...": "..." },
  "resource": { "...": "..." },
  "semantic_nodes": { "...": "..." },
  "queue": { "...": "..." }
}
```

这里不应强行返回 `memory`。

### 8.2 `search.find`

可能返回：

```json
{
  "operation": "search.find",
  "status": "ok",
  "duration_ms": 31.2,
  "tokens": { "...": "..." },
  "vector": { "...": "..." }
}
```

这里不应强行返回 `queue`、`semantic_nodes`、`memory`。

### 8.3 `session.commit`

可能返回：

```json
{
  "operation": "session.commit",
  "status": "ok",
  "duration_ms": 48.1,
  "tokens": { "...": "..." },
  "memory": {
    "extracted": 4,
    "extract": { "...": "..." }
  }
}
```

这里不应强行返回 `semantic_nodes`。

## 9. 成本模型

当前 collector 只采集 summary 所需的数据：

- 采集 counters / gauges
- 记录 error 状态
- 构造最终 summary
- 不保留事件列表

## 10. 实现结构

### 10.1 核心类型

核心实现位于：

- `openviking/telemetry/operation.py`
- `openviking/telemetry/request.py`
- `openviking/telemetry/context.py`
- `openviking/telemetry/registry.py`

主要对象包括：

- `OperationTelemetry`
- `TelemetrySnapshot`
- `TelemetrySelection`

### 10.2 请求解析

`openviking/telemetry/request.py` 负责统一解析 `telemetry` 请求参数：

- 支持 `bool | object`
- 归一化为 `TelemetrySelection`
- 校验非法字段，例如 `events`

这样 server、local client、HTTP client 都共享同一套语义。

### 10.3 服务端集成

`openviking/server/telemetry.py` 负责：

- 根据请求创建 collector
- 根据 selection 决定是否附带 `summary`

router 层的职责是：

1. 创建 collector
2. 绑定 operation 上下文
3. 执行实际业务逻辑
4. 按请求返回 `telemetry`

### 10.4 本地与 HTTP client

本地 client 和 HTTP client 都暴露同样的 `telemetry` 参数语义：

```python
await client.find("memory dedup", telemetry=True)
await client.find("memory dedup", telemetry={"summary": True})
```

其中：

- local client 在本地生成 telemetry 并拼回结果
- HTTP client 负责参数校验并透传给服务端

## 11. 异步链路与跨组件聚合

当前 operation telemetry 不只覆盖同步请求栈，也支持部分异步处理链路的数据回流。

典型场景包括：

- 请求线程触发语义队列处理
- 请求线程触发 embedding 处理
- 后台处理线程继续向同一个 operation collector 记录指标

实现方式是：

- collector 生成 `telemetry.id`
- 后续消息携带该 `id`
- 后台组件通过 registry 找回原 collector
- 在新的执行上下文中重新绑定 collector

这样一次操作的最终 summary 可以覆盖：

- 请求入口逻辑
- 检索过程
- embedding 处理
- semantic queue 处理
- memory 提取结果

## 12. 与 OpenTelemetry 的关系

当前方案不是直接把 OpenTelemetry 暴露为业务接口，而是先定义 OpenViking 自己的 telemetry 抽象。

这样做的好处是：

- 对调用方暴露稳定、简单的产品接口
- 不把业务接口和具体观测框架强绑定
- 后续可以新增 OpenTelemetry backend，而不影响现有 SDK / HTTP 语义

可以把 OpenTelemetry 看作未来的一种底层实现或导出方式，而不是当前对外协议本身。

## 13. 未来扩展方向

当前文档描述的是 operation telemetry，但未来需要兼容更广义的 telemetry 数据源。

推荐的扩展方向：

- 服务级 token 消耗聚合
- 存储、向量库、模型服务的接口耗时
- 队列吞吐、失败率、积压长度
- 与 OpenTelemetry exporter 的桥接
- 更长期的指标聚合、采样和导出

这些扩展不要求沿用完全相同的 summary schema，但应复用统一的 telemetry 抽象和运行时。

## 14. 使用示例

### 14.1 返回 telemetry summary

```bash
curl -X POST http://localhost:8080/api/v1/search/find \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "memory dedup",
    "limit": 5,
    "telemetry": true
  }'
```

### 14.2 只返回 summary

```bash
curl -X POST http://localhost:8080/api/v1/search/find \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "memory dedup",
    "limit": 5,
    "telemetry": {
      "summary": true
    }
  }'
```

### 14.3 `session.commit` 返回 memory extract 分解耗时

```bash
curl -X POST http://localhost:8080/api/v1/sessions/<session-id>/commit \
  -H 'Content-Type: application/json' \
  -d '{
    "telemetry": true
  }'
```

可能返回：

```json
{
  "telemetry": {
    "id": "tm_xxx",
    "summary": {
      "operation": "session.commit",
      "status": "ok",
      "duration_ms": 1081.2,
      "tokens": {
        "total": 1324,
        "llm": {
          "input": 1200,
          "output": 96,
          "total": 1296
        },
        "embedding": {
          "total": 28
        }
      },
      "memory": {
        "extracted": 5,
        "extract": {
          "duration_ms": 842.3,
          "candidates": {
            "total": 7,
            "standard": 5,
            "tool_skill": 2
          },
          "actions": {
            "created": 3,
            "merged": 1,
            "deleted": 0,
            "skipped": 3
          },
          "stages": {
            "prepare_inputs_ms": 8.4,
            "llm_extract_ms": 410.2,
            "normalize_candidates_ms": 6.7,
            "tool_skill_stats_ms": 1.9,
            "profile_create_ms": 12.5,
            "tool_skill_merge_ms": 43.0,
            "dedup_ms": 215.6,
            "create_memory_ms": 56.1,
            "merge_existing_ms": 22.7,
            "delete_existing_ms": 0.0,
            "create_relations_ms": 18.2,
            "flush_semantic_ms": 9.0
          }
        }
      }
    }
  }
}
```

### 14.4 `resources.add_resource` 返回资源处理分解耗时

```bash
curl -X POST http://localhost:8080/api/v1/resources \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "/tmp/demo.md",
    "reason": "telemetry demo",
    "wait": true,
    "telemetry": true
  }'
```

可能返回：

```json
{
  "telemetry": {
    "id": "tm_xxx",
    "summary": {
      "operation": "resources.add_resource",
      "status": "ok",
      "duration_ms": 152.3,
      "tokens": {
        "total": 48,
        "llm": {
          "input": 36,
          "output": 12,
          "total": 48
        },
        "embedding": {
          "total": 0
        }
      },
      "resource": {
        "request": {
          "duration_ms": 152.3
        },
        "process": {
          "duration_ms": 101.7,
          "parse": {
            "duration_ms": 38.1,
            "warnings_count": 1
          },
          "finalize": {
            "duration_ms": 22.4
          },
          "summarize": {
            "duration_ms": 31.8
          }
        },
        "wait": {
          "duration_ms": 46.9
        },
        "watch": {
          "duration_ms": 0.8
        },
        "flags": {
          "wait": true,
          "build_index": true,
          "summarize": false,
          "watch_enabled": false
        }
      },
      "semantic_nodes": {
        "total": 4,
        "done": 4
      },
      "queue": {
        "semantic": {
          "processed": 1
        },
        "embedding": {
          "processed": 1
        }
      }
    }
  }
}
```

### 14.5 Python SDK

```python
result = await client.find("memory dedup", telemetry={"summary": True})

print(result.telemetry["summary"]["tokens"]["total"])
```

## 15. 新接口接入规范

新接口如果需要接入 operation telemetry，建议遵循以下规则：

1. 为该操作创建 `OperationTelemetry` collector。
2. 用上下文绑定覆盖整个操作生命周期。
3. 在内部关键阶段记录 counters、gauges 和错误状态。
4. 仅在调用方请求时返回 `telemetry`。
5. summary 只返回本次操作真实产出的分组。

这样可以保持默认低成本，同时为调用方提供稳定、可分析的结构化摘要。
