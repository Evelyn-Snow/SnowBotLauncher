# 生活画面

按场景生成二次元生活插画，不是角色海报生成器。

## 构图模式

| 模式 | 画面 |
|---|---|
| `scene` | 只拍桌面、书、食物、画纸、窗外；她不出镜 |
| `partial` | 只露手、背影、侧脸、肩膀或画面边缘；脸大多不在画面里 |
| `candid` | 抓拍、动态模糊、跑出画面、轻微手抖、构图不完美 |
| `group` | 她在人群里，其他人物在背景虚化、不细化脸 |
| `portrait` | 正面半身/立绘；只在明确说“看看你/你的脸/自拍”时使用 |

`auto` 默认优先 `scene` / `partial` / `candid`，不会默认正脸。

## 角色一致性

- `character_ref.png`：角色母版，人物出镜时作为参考图
- `character.json`：发型、瞳色、衣橱、表情索引；按场景自动选日常/图书馆/居家/雪夜/正式套
- `scene` 模式不传参考图，避免每张都变成角色图

## 安全与边界

- 不生成真实人物肖像、主人/朋友的脸、证件、屏幕截图、聊天记录
- 场景描述先脱敏：QQ 号、链接、本机路径、密码/证件/健康等敏感词会被拒绝
- 其他人物只做背景虚化，不细化脸
- 群聊默认关闭；开启后也必须被 @/点名
- 生成失败不发送，也不让模型承诺“等会儿给你看”

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| `owner_only` | true | 只对主人开放 |
| `allow_groups` | false | 群聊生成（需被点名） |
| `allow_portrait` | true | 允许正面半身；`auto` 不会默认选 |
| `allow_other_people` | true | 允许背景人物 |
| `max_per_day` | 2 | 每天最多 |
| `cooldown_minutes` | 30 | 两张间隔 |
| `model` | doubao-seedream-5-0-pro-260628 | 图像模型 |
| `api_key_file` | 空 | 本机 Key 文件路径；不要提交 Key |
| `character_ref` | `C:/Evelyn_Snow/角色/character_ref.png` | 母版图 |
| `character_spec` | `C:/Working_Files/AIMade/SnowBotArtwork/spec/character.json` | 设定 |
| `output_dir` | `C:/Working_Files/AIMade/SnowBotArtwork/generated` | 生成图目录 |

## 工具

`share_life_image(scene, composition="auto", reason="")`：想分享生活画面时调用；生成后直接发到当前聊天，图片元数据存同目录 `.json`。
