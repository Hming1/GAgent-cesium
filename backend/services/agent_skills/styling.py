"""Layer styling Skill."""

from services.agent_skills.base import AgentSkill, SelectorToolMetadata, ToolDisplayMetadata
from services.tools.styling_tools import (
    apply_intelligent_color_scheme,
    auto_style_new_layers,
    check_and_auto_style_layers,
    color_layers_by_attribute,
    style_map_layers,
)


STYLING_SKILL = AgentSkill(
    id="styling",
    display_name="Layer Styling",
    description="按用户要求调整地图图层的颜色、透明度、线宽和配色方案。",
    tools={
        "style_layers": style_map_layers,
        "autostyle_new_layers": auto_style_new_layers,
        "check_and_autostyle": check_and_auto_style_layers,
        "apply_color_scheme": apply_intelligent_color_scheme,
        "color_by_attribute": color_layers_by_attribute,
    },
    tool_metadata={
        "style_layers": ToolDisplayMetadata(
            display_name="Manual Layer Styling",
            category="styling",
        ),
        "autostyle_new_layers": ToolDisplayMetadata(
            display_name="Auto-style New Layers",
            category="styling",
        ),
        "check_and_autostyle": ToolDisplayMetadata(
            display_name="Check and Auto-style",
            category="styling",
        ),
        "apply_color_scheme": ToolDisplayMetadata(
            display_name="Apply Color Scheme",
            category="styling",
        ),
        "color_by_attribute": ToolDisplayMetadata(
            display_name="Color By Attribute",
            category="styling",
        ),
    },
    selector_metadata={
        "style_layers": SelectorToolMetadata(
            name="style_layers",
            category="styling",
            description="Change colors, symbols, opacity, stroke, fill, and map appearance.",
        ),
        "autostyle_new_layers": SelectorToolMetadata(
            name="autostyle_new_layers",
            category="styling",
            description="Automatically style newly loaded layers based on data type.",
        ),
        "check_and_autostyle": SelectorToolMetadata(
            name="check_and_autostyle",
            category="styling",
            description="Check whether loaded layers need automatic styling and improve them.",
        ),
        "apply_color_scheme": SelectorToolMetadata(
            name="apply_color_scheme",
            category="styling",
            description="Apply color palettes and color theory schemes across map layers.",
        ),
        "color_by_attribute": SelectorToolMetadata(
            name="color_by_attribute",
            category="styling",
            description=(
                "Color features inside a layer by an attribute field "
                "(district/adname/type/category)."
            ),
        ),
        "style_map_layers": SelectorToolMetadata(
            name="style_map_layers",
            category="styling",
            description="Apply manual visual styles, themes, colors, and symbols to layers.",
        ),
        "auto_style_new_layers": SelectorToolMetadata(
            name="auto_style_new_layers",
            category="styling",
            description="Automatically apply smart styling to newly loaded geographic data.",
        ),
        "check_and_auto_style_layers": SelectorToolMetadata(
            name="check_and_auto_style_layers",
            category="styling",
            description="Verify and improve existing layer styling and visibility.",
        ),
        "apply_intelligent_color_scheme": SelectorToolMetadata(
            name="apply_intelligent_color_scheme",
            category="styling",
            description="Apply accessible color schemes and palettes to layers.",
        ),
        "color_layers_by_attribute": SelectorToolMetadata(
            name="color_layers_by_attribute",
            category="styling",
            description=(
                "Apply categorical colors by attribute field within one layer "
                "and promote it to the map."
            ),
        ),
    },
    plan_aliases={
        "style_layers": "style_layers",
        "style_map_layers": "style_layers",
        "autostyle_new_layers": "autostyle_new_layers",
        "auto_style_new_layers": "autostyle_new_layers",
        "check_and_autostyle": "check_and_autostyle",
        "check_and_auto_style_layers": "check_and_autostyle",
        "apply_color_scheme": "apply_color_scheme",
        "apply_intelligent_color_scheme": "apply_color_scheme",
        "color_by_attribute": "color_by_attribute",
        "color_layers_by_attribute": "color_by_attribute",
        "styling": "style_layers",
        "style": "style_layers",
    },
    layer_keywords=(
        "样式",
        "风格",
        "可视化",
        "颜色",
        "配色",
        "上色",
        "按区",
        "分类上色",
        "style",
        "color",
        "visual",
        "choropleth",
    ),
    prompt=(
        "- 样式是用户主动要求时才执行，不要在地理编码、加载或分析后自动改样式。\n"
        "- 样式工具可读取 geodata_layers / geodata_results / geodata_last_results；"
        "成功后会自动把图层 promote 到地图，不要要求用户先去结果列表勾选。\n"
        "- 用户确认「按区上色 / 按某字段上色」时，必须在本轮调用 "
        "color_layers_by_attribute（传入 field，如 adname），禁止只回复「好的」而不调工具。\n"
        "- style_layers / apply_color_scheme 只能给「整层」一个颜色；"
        "层内按属性分类上色必须用 color_layers_by_attribute。\n"
        "- 若图层还不在地图上但已在结果集合中，可先 add_layers_to_map，"
        "或直接调用样式工具（会自动上图）。\n"
        "- 保留用户已有样式，除非用户明确要求覆盖。"
    ),
)
