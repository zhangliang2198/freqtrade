from pathlib import Path
from typing import Dict, Any, Optional, List
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
import logging

logger = logging.getLogger(__name__)

class PromptManager:
    """
    使用 Jinja2 的提示词模板管理器（支持新的目录结构）
    
    加载和渲染不同决策点的提示词模板。
    模板存储在 user_data/llm_prompts/ 目录中，按风格分文件夹组织。
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

        # 检测并初始化目录结构
        self.use_new_structure = self._detect_structure()
        
        if self.use_new_structure:
            self._init_new_structure()
        else:
            self._init_legacy_structure()

        logger.info(
            f"提示词管理器已初始化，模板目录: {template_dir}, "
            f"提示词风格: {self.prompt_style}, "
            f"使用{'新' if self.use_new_structure else '旧'}目录结构"
        )

    def _detect_structure(self) -> bool:
        """检测是否使用新的目录结构"""
        default_dir = self.template_dir / "default"
        aggressive_dir = self.template_dir / "aggressive"
        conservative_dir = self.template_dir / "conservative"
        
        # 如果三个风格文件夹都存在，认为已迁移
        return all(dir.exists() for dir in [default_dir, aggressive_dir, conservative_dir])

    def _init_new_structure(self):
        """初始化新结构的 Jinja2 环境"""
        self.envs = {}
        for style in ["default", "aggressive", "conservative"]:
            style_dir = self.template_dir / style
            if style_dir.exists():
                self.envs[style] = Environment(loader=FileSystemLoader(str(style_dir)))
                logger.debug(f"为风格 '{style}' 初始化 Jinja2 环境: {style_dir}")
            else:
                # 回退到根目录
                self.envs[style] = Environment(loader=FileSystemLoader(str(self.template_dir)))
                logger.warning(f"风格目录 {style_dir} 不存在，回退到根目录")

    def _init_legacy_structure(self):
        """初始化旧结构的 Jinja2 环境"""
        try:
            self.env = Environment(loader=FileSystemLoader(str(self.template_dir)))
            logger.debug("使用旧目录结构初始化 Jinja2 环境")
        except ImportError:
            raise ImportError(
                "PromptManager 需要 Jinja2 包。"
                "请使用以下命令安装: pip install jinja2>=3.0.0"
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
        if self.use_new_structure:
            return self._build_prompt_new_structure(decision_point, context)
        else:
            return self._build_prompt_legacy_structure(decision_point, context)

    def _build_prompt_new_structure(self, decision_point: str, context: Dict[str, Any]) -> str:
        """使用新结构构建提示词"""
        # 获取对应风格的环境
        env = self.envs.get(self.prompt_style, self.envs["default"])
        template_name = f"{decision_point}.j2"
        
        try:
            template = env.get_template(template_name)
            prompt = template.render(**context)
            logger.debug(f"成功渲染模板: {self.prompt_style}/{template_name}")
            return prompt
            
        except TemplateNotFound:
            # 回退到默认风格
            if self.prompt_style != "default":
                logger.warning(
                    f"在 {self.prompt_style} 文件夹中找不到 {template_name}，"
                    f"回退到 default 风格"
                )
                try:
                    default_env = self.envs["default"]
                    template = default_env.get_template(template_name)
                    prompt = template.render(**context)
                    logger.info(f"成功使用默认模板: default/{template_name}")
                    return prompt
                except TemplateNotFound:
                    pass
            
            # 如果仍然找不到，抛出错误
            raise FileNotFoundError(
                f"找不到提示词模板: {self.template_dir / self.prompt_style / template_name}\n"
                f"请在 {self.template_dir / self.prompt_style} 目录中创建 {template_name} 文件\n"
                f"当前 prompt_style: {self.prompt_style}\n"
                f"可用选项: default, conservative, aggressive"
            )
            
        except Exception as e:
            logger.error(f"渲染模板 {self.prompt_style}/{template_name} 失败: {e}", exc_info=True)
            raise

    def _build_prompt_legacy_structure(self, decision_point: str, context: Dict[str, Any]) -> str:
        """使用旧结构构建提示词"""
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

    def list_available_templates(self) -> Dict[str, List[str]]:
        """
        列出可用的模板文件
        
        Returns:
            按风格分组的模板文件列表
        """
        if self.use_new_structure:
            templates = {}
            for style in ["default", "aggressive", "conservative"]:
                style_dir = self.template_dir / style
                if style_dir.exists():
                    templates[style] = [f.name for f in style_dir.glob("*.j2")]
                else:
                    templates[style] = []
            return templates
        else:
            # 旧结构：按文件名分组
            templates = {"default": [], "aggressive": [], "conservative": []}
            for file_path in self.template_dir.glob("*.j2"):
                name = file_path.name
                if "_" in name:
                    parts = name.split("_")
                    if len(parts) == 2 and parts[1].endswith(".j2"):
                        style = parts[1].replace(".j2", "")
                        if style in templates:
                            templates[style].append(name)
                            continue
                templates["default"].append(name)
            return templates
