from pathlib import Path
from typing import Dict, Any, Optional
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
import logging

logger = logging.getLogger(__name__)

class PromptManager:
    """
    使用 Jinja2 的提示词模板管理器

    加载和渲染不同决策点的提示词模板。
    模板必须存储在 user_data/llm_prompts/ 目录中。
    """

    def __init__(self, config: Dict[str, Any], user_data_dir: Optional[str] = None):
        """
        初始化提示词管理器

        Args:
            config: LLM 配置字典（保留以兼容现有代码）
            user_data_dir: user_data 目录的可选路径
        """
        # 确定模板目录
        if user_data_dir:
            template_dir = Path(user_data_dir) / "llm_prompts"
        else:
            template_dir = Path("user_data/llm_prompts")

        # 确保模板目录存在
        if not template_dir.exists():
            raise FileNotFoundError(
                f"提示词模板目录不存在: {template_dir}\n"
                f"请创建该目录并添加提示词模板文件（如 entry.j2, exit.j2 等）"
            )

        self.template_dir = template_dir

        # 获取提示词风格配置
        self.prompt_style = config.get("prompt_style", "default")
        if self.prompt_style not in ["default", "conservative", "aggressive"]:
            logger.warning(
                f"无效的 prompt_style 配置: {self.prompt_style}，"
                f"将使用默认风格。有效选项: default, conservative, aggressive"
            )
            self.prompt_style = "default"

        # 初始化 Jinja2 环境
        try:
            self.env = Environment(loader=FileSystemLoader(str(template_dir)))
        except ImportError:
            raise ImportError(
                "PromptManager 需要 Jinja2 包。"
                "请使用以下命令安装: pip install jinja2>=3.0.0"
            )

        logger.info(
            f"提示词管理器已初始化，模板目录: {template_dir}, "
            f"提示词风格: {self.prompt_style}"
        )

    def build_prompt(self, decision_point: str, context: Dict[str, Any]) -> str:
        """
        从模板构建提示词

        Args:
            decision_point: 决策点名称 (例如, "entry", "exit")
            context: 用于渲染模板的上下文数据

        Returns:
            渲染后的提示词字符串

        Raises:
            FileNotFoundError: 如果找不到模板文件
            Exception: 如果渲染模板失败
        """
        # 根据 prompt_style 确定模板名称
        if self.prompt_style == "default":
            template_name = f"{decision_point}.j2"
        else:
            # 优先使用带风格后缀的模板，如 entry_conservative.j2
            template_name = f"{decision_point}_{self.prompt_style}.j2"

        try:
            template = self.env.get_template(template_name)
            prompt = template.render(**context)
            logger.debug(f"成功渲染模板: {template_name}")
            return prompt

        except TemplateNotFound:
            # 如果找不到带风格的模板，尝试回退到默认模板
            if self.prompt_style != "default":
                logger.warning(
                    f"找不到提示词模板: {template_name}，"
                    f"尝试使用默认模板: {decision_point}.j2"
                )
                try:
                    fallback_template_name = f"{decision_point}.j2"
                    template = self.env.get_template(fallback_template_name)
                    prompt = template.render(**context)
                    logger.info(f"成功使用默认模板: {fallback_template_name}")
                    return prompt
                except TemplateNotFound:
                    pass

            # 如果仍然找不到，抛出错误
            raise FileNotFoundError(
                f"找不到提示词模板: {self.template_dir / template_name}\n"
                f"请在 {self.template_dir} 目录中创建 {template_name} 文件\n"
                f"当前 prompt_style: {self.prompt_style}\n"
                f"可用选项: default, conservative, aggressive"
            )

        except Exception as e:
            logger.error(f"渲染模板 {template_name} 失败: {e}", exc_info=True)
            raise
