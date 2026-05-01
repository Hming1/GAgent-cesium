"use client";

import { useState, memo } from "react";
import { useSettingsStore } from "../../stores/settingsStore";
import { ChevronDown, ChevronUp, RotateCcw, Info, Wand2 } from "lucide-react";
import { ColorScale, ColorSettings } from "../../stores/settingsStore";
import { generateColorScale } from "../../utils/colorGenerator";

const COLOR_SCALE_LABELS: Record<keyof ColorScale, string> = {
  shade_50: "50 - 最浅",
  shade_100: "100",
  shade_200: "200",
  shade_300: "300",
  shade_400: "400",
  shade_500: "500 - 基础",
  shade_600: "600",
  shade_700: "700",
  shade_800: "800",
  shade_900: "900",
  shade_950: "950 - 最深",
};

// Organized color groups
const COLOR_GROUPS = {
  core: {
    title: "核心颜色",
    description: "文本、背景和主要操作使用的 UI 主色",
    scales: ["primary", "second_primary", "secondary", "tertiary"] as (keyof ColorSettings)[],
  },
  semantic: {
    title: "语义颜色",
    description: "状态与反馈颜色",
    scales: ["danger", "warning", "info", "neutral"] as (keyof ColorSettings)[],
  },
  corporate: {
    title: "企业/品牌颜色",
    description: "用于图层样式和自定义元素的品牌色",
    scales: ["corporate_1", "corporate_2", "corporate_3"] as (keyof ColorSettings)[],
  },
};

const COLOR_SCALE_NAMES: Record<keyof ColorSettings, string> = {
  primary: "主色（文本与边框）",
  second_primary: "第二主色（操作）",
  secondary: "辅助色（强调）",
  tertiary: "第三色（成功）",
  danger: "危险色（错误）",
  warning: "警告色",
  info: "信息色",
  neutral: "中性色（黑白灰）",
  corporate_1: "品牌色 1（玫瑰）",
  corporate_2: "品牌色 2（天空蓝）",
  corporate_3: "品牌色 3（紫色）",
};

const COLOR_USAGE_HINTS: Record<keyof ColorSettings, string> = {
  primary: "用于主文本（900）、背景（50-100）、边框（300）、图标（600-700）和侧边栏（800）",
  second_primary: "用于操作按钮（600）、悬停状态（700）、用户消息（200）和进度条（500）",
  secondary: "用于焦点环（300）、等待状态（500-600）、侧边栏悬停（800）和徽章（100）",
  tertiary: "用于成功消息（600）、完成状态、复选框和导出按钮（700）",
  danger: "用于错误消息、删除/移除按钮（600）、错误背景（100）和悬停（700）",
  warning: "用于警告消息与提醒（600）、警告背景（100-200）",
  info: "用于信息提示（600）和信息背景（100-200）",
  neutral: "用于纯白（50）、纯黑（950）、遮罩背景和中性灰",
  corporate_1: "第一个品牌色，用于图层类型样式（玫瑰/粉色系）",
  corporate_2: "第二个品牌色，用于图层类型样式（天空蓝系）",
  corporate_3: "第三个品牌色，用于图层类型样式（紫色系）",
};

interface ColorScaleEditorProps {
  scaleName: keyof ColorSettings;
  scale: ColorScale;
  onUpdate: (shade: keyof ColorScale, color: string) => void;
  onAutoGenerate: (baseColor: string) => void;
}

// Memoize the ColorScaleEditor to prevent re-renders when parent state changes
// This ensures the expanded/collapsed state persists when colors are updated
const ColorScaleEditor = memo(function ColorScaleEditor({
  scaleName,
  scale,
  onUpdate,
  onAutoGenerate,
}: ColorScaleEditorProps) {
  const [expanded, setExpanded] = useState(false);
  const [showQuickPicker, setShowQuickPicker] = useState(false);

  const handleQuickColorChange = (color: string) => {
    onAutoGenerate(color);
    // Keep the quick picker open so users can try multiple colors
  };

  return (
    <div className="border border-primary-300 rounded p-3 bg-primary-100 dark:bg-primary-900">
      <div
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between cursor-pointer"
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setExpanded(!expanded);
          }
        }}
      >
        <div className="flex items-center space-x-3 flex-1">
          {/* Gradient preview - clickable to select colors */}
          <div className="flex space-x-0.5">
            {Object.entries(scale).map(([shade, color]) => (
              <div
                key={shade}
                onClick={(e) => {
                  e.stopPropagation();
                  if (!expanded) {
                    setExpanded(true);
                  }
                  // Create a temporary color input to trigger color picker
                  const input = document.createElement('input');
                  input.type = 'color';
                  input.value = color;
                  input.style.position = 'absolute';
                  input.style.opacity = '0';
                  input.style.pointerEvents = 'none';
                  document.body.appendChild(input);
                  
                  input.addEventListener('change', (event) => {
                    const newColor = (event.target as HTMLInputElement).value;
                    onUpdate(shade as keyof ColorScale, newColor);
                    document.body.removeChild(input);
                  });
                  
                  input.addEventListener('blur', () => {
                    setTimeout(() => {
                      if (document.body.contains(input)) {
                        document.body.removeChild(input);
                      }
                    }, 100);
                  });
                  
                  input.click();
                }}
                className="w-3 h-8 first:rounded-l last:rounded-r cursor-pointer hover:ring-2 hover:ring-secondary-500 hover:z-10 transition-all"
                style={{ backgroundColor: color }}
                title={`${shade}: ${color} - 点击修改`}
              />
            ))}
          </div>
          <div className="flex-1">
            <div className="font-medium text-primary-900 dark:text-primary-100 text-sm">
              {COLOR_SCALE_NAMES[scaleName]}
            </div>
            <div className="text-xs text-primary-800 dark:text-primary-400 mt-0.5">
              {COLOR_USAGE_HINTS[scaleName]}
            </div>
          </div>
        </div>
        <div className="flex items-center space-x-2 flex-shrink-0">
          {/* Quick Color Picker Button */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowQuickPicker(!showQuickPicker);
            }}
            className="p-1.5 bg-secondary-100 hover:bg-secondary-200 rounded transition-colors"
            title="快速设置颜色（自动生成所有色阶）"
          >
            <Wand2 className="w-4 h-4 text-secondary-700" />
          </button>
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-primary-600 dark:text-primary-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-primary-600 dark:text-primary-400" />
          )}
        </div>
      </div>

      {/* Quick Color Picker */}
      {showQuickPicker && (
        <div className="mt-3 p-3 bg-secondary-50 border border-secondary-200 rounded">
          <div className="flex items-center space-x-3">
            <input
              type="color"
              value={scale.shade_500}
              onChange={(e) => handleQuickColorChange(e.target.value)}
              className="w-16 h-16 rounded cursor-pointer border-2 border-secondary-300"
              title="选择主色，所有色阶将自动生成"
            />
            <div className="flex-1">
              <p className="text-sm font-medium text-secondary-900 mb-1">
                快速配色
              </p>
              <p className="text-xs text-secondary-800">
                选择主色后，系统会自动生成从浅到深的 11 个色阶。
              </p>
            </div>
          </div>
        </div>
      )}

      {expanded && (
        <div className="mt-3 grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
          {Object.entries(scale).map(([shade, color]) => (
            <div key={shade} className="flex flex-col items-center space-y-1">
              <input
                type="color"
                value={color}
                onChange={(e) =>
                  onUpdate(shade as keyof ColorScale, e.target.value)
                }
                className="w-12 h-12 rounded cursor-pointer border border-primary-300"
                title={`编辑 ${shade}`}
              />
              <span className="text-xs text-primary-700 font-mono">
                {COLOR_SCALE_LABELS[shade as keyof ColorScale]}
              </span>
              <span className="text-[10px] text-primary-500 font-mono">
                {color}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

export default function ColorSettingsComponent() {
  const [isOpen, setIsOpen] = useState(false); // Start collapsed by default
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const color_settings = useSettingsStore((state) => state.color_settings);
  const updateColorScale = useSettingsStore((state) => state.updateColorScale);
  const resetColorSettings = useSettingsStore((state) => state.resetColorSettings);

  if (!color_settings) {
    return (
      <div className="border border-primary-300 rounded p-4 bg-primary-100 dark:bg-primary-900">
        <p className="text-primary-600">正在加载颜色设置...</p>
      </div>
    );
  }

  const handleReset = () => {
    resetColorSettings();
    setShowResetConfirm(false);
  };

  const handleAutoGenerate = (scaleName: keyof ColorSettings, baseColor: string) => {
    const generatedScale = generateColorScale(baseColor);
    // Update all shades at once
    Object.entries(generatedScale).forEach(([shade, color]) => {
      updateColorScale(scaleName, shade as keyof ColorScale, color);
    });
  };

  return (
    <div className="border border-primary-300 rounded bg-primary-50 dark:bg-neutral-900 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-4 py-3 bg-primary-100 hover:bg-primary-200 dark:bg-primary-900 dark:hover:bg-primary-800 transition-colors flex items-center justify-between"
      >
        <div className="flex items-center space-x-2">
          <h2 className="text-lg font-semibold text-primary-900 dark:text-primary-100">
            颜色自定义
          </h2>
          <span className="text-xs bg-secondary-100 dark:bg-secondary-900 text-secondary-800 dark:text-secondary-100 px-2 py-0.5 rounded-full font-medium">
            企业品牌
          </span>
        </div>
        {isOpen ? (
          <ChevronUp className="w-5 h-5 text-primary-700 dark:text-primary-300" />
        ) : (
          <ChevronDown className="w-5 h-5 text-primary-700 dark:text-primary-300" />
        )}
      </button>

      {isOpen && (
        <div className="p-4 space-y-4">
          {/* Info Box */}
          <div className="bg-info-50 border border-info-200 rounded p-3 text-sm">
            <div className="flex items-start space-x-2">
              <Info className="w-4 h-4 text-info-600 mt-0.5 flex-shrink-0" />
              <div className="text-info-900">
                <p className="font-medium mb-1">
                  自定义应用配色方案
                </p>
                <ul className="text-xs space-y-1 text-info-800">
                  <li>
                    • 点击<strong>魔法棒</strong>图标可快速生成配色
                  </li>
                  <li>
                    • 修改会立即应用到整个应用
                  </li>
                  <li>
                    • <strong>核心颜色</strong>用于主要 UI 元素
                  </li>
                  <li>
                    • <strong>语义颜色</strong>用于状态反馈
                  </li>
                  <li>
                    • <strong>品牌颜色</strong>用于图层样式和品牌展示
                  </li>
                  <li>
                    • 每个颜色包含 11 个色阶（50=最浅，950=最深）
                  </li>
                  <li>
                    • 导出设置可保存你的自定义配色
                  </li>
                </ul>
              </div>
            </div>
          </div>

          {/* Color Groups */}
          {Object.entries(COLOR_GROUPS).map(([groupKey, group]) => (
            <div key={groupKey} className="space-y-2">
              <div className="border-b border-primary-200 pb-1">
                <h3 className="text-sm font-semibold text-primary-900 dark:text-primary-300">
                  {group.title}
                </h3>
                <p className="text-xs text-primary-800 dark:text-primary-300">{group.description}</p>
              </div>
              <div className="space-y-2">
                {group.scales.map((scaleName) => (
                  <ColorScaleEditor
                    key={scaleName}
                    scaleName={scaleName}
                    scale={color_settings[scaleName]}
                    onUpdate={(shade, color) =>
                      updateColorScale(scaleName, shade, color)
                    }
                    onAutoGenerate={(baseColor) =>
                      handleAutoGenerate(scaleName, baseColor)
                    }
                  />
                ))}
              </div>
            </div>
          ))}

          {/* Reset Button */}
          <div className="pt-4 border-t border-primary-200">
            {!showResetConfirm ? (
              <button
                onClick={() => setShowResetConfirm(true)}
                className="flex items-center space-x-2 px-4 py-2 bg-primary-200 text-primary-700 rounded hover:bg-primary-300 transition-colors font-medium"
              >
                <RotateCcw className="w-4 h-4" />
                <span>重置</span>
              </button>
            ) : (
              <div className="flex items-center space-x-2">
                <p className="text-sm text-primary-700">
                  是否将所有颜色重置为默认值？
                </p>
                <button
                  onClick={handleReset}
                  className="px-3 py-1 bg-danger-600 text-neutral-50 rounded hover:bg-danger-700 transition-colors font-medium text-sm"
                >
                  确认
                </button>
                <button
                  onClick={() => setShowResetConfirm(false)}
                  className="px-3 py-1 bg-primary-300 text-primary-900 rounded hover:bg-primary-400 transition-colors font-medium text-sm"
                >
                  取消
                </button>
              </div>
            )}
          </div>

          {/* Usage Tips */}
          <div className="bg-warning-50 border border-warning-200 rounded p-3 text-xs text-warning-900">
            <p className="font-medium mb-1">颜色选择建议：</p>
            <ul className="space-y-1">
              <li>
                • 使用较浅色阶（50-300）作为背景，较深色阶（700-950）作为文本
              </li>
              <li>
                • 保持文本与背景之间有足够对比度，提升可访问性
              </li>
              <li>
                • 保持品牌色与企业规范一致
              </li>
              <li>
                • 使用色盲模拟器测试颜色可访问性
              </li>
              <li>
                • 危险色建议保持红色系，方便用户快速识别
              </li>
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
