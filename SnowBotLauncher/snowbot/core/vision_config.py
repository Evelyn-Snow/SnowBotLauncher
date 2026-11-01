"""AstrBot 视觉模式的配置写入逻辑。

AstrBot 有两条图片处理路径：
- 配置了 default_image_caption_provider_id：先把图片转成文字描述，再交给主模型。
- 未配置描述提供商：带图片的请求会切换到支持 image 的 fallback 提供商，
  视觉模型因此能同时看到人格、聊天历史和图片。
"""

from __future__ import annotations

DEFAULT_CAPTION_PROMPT = (
    "请用中文描述这张图片或表情包：画面主体、人物动作、可见文字、情绪和梗；"
    "如果是表情包，说明它表达的态度。看不清的部分不要编造。"
)


def _vision_settings(profile: dict) -> tuple[dict, dict]:
    """返回可安全写入的 provider_settings 与 agent_runner.config.model。"""
    settings = profile.get("provider_settings")
    if not isinstance(settings, dict):
        settings = {}
        profile["provider_settings"] = settings
    agent_runner = profile.get("agent_runner")
    if not isinstance(agent_runner, dict):
        agent_runner = {}
        profile["agent_runner"] = agent_runner
    runner_config = agent_runner.get("config")
    if not isinstance(runner_config, dict):
        runner_config = {}
        agent_runner["config"] = runner_config
    model_cfg = runner_config.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {}
        runner_config["model"] = model_cfg
    return settings, model_cfg


def apply_vision_mode(
    profile: dict, pid: str, old_id: str = "", context_mode: bool = True
) -> None:
    """把视觉提供商写入 AstrBot 配置。

    上下文模式会清空图片描述提供商，并把视觉模型加入 fallback；描述模式则
    设置描述提供商，并把视觉模型移出 fallback。old_id 用于切换提供商时
    清理上一项，避免旧视觉模型仍被选中。
    """
    settings, model_cfg = _vision_settings(profile)
    fallback_ids = [
        str(item)
        for item in (model_cfg.get("fallback_provider_ids") or [])
        if str(item) and str(item) not in {pid, old_id}
    ]
    if context_mode:
        fallback_ids.append(pid)
        settings["default_image_caption_provider_id"] = ""
    else:
        settings["default_image_caption_provider_id"] = pid
        if not str(settings.get("image_caption_prompt") or "").strip():
            settings["image_caption_prompt"] = DEFAULT_CAPTION_PROMPT
    model_cfg["fallback_provider_ids"] = fallback_ids


def clear_vision_mode(profile: dict, *ids: str) -> None:
    """关闭图片视觉：清空描述提供商，并移除启动器写入的 fallback 项。"""
    settings, model_cfg = _vision_settings(profile)
    caption_id = str(settings.get("default_image_caption_provider_id") or "")
    remove_ids = {str(item) for item in ids if str(item)} | {caption_id}
    settings["default_image_caption_provider_id"] = ""
    model_cfg["fallback_provider_ids"] = [
        str(item)
        for item in (model_cfg.get("fallback_provider_ids") or [])
        if str(item) and str(item) not in remove_ids
    ]
