"use client";

import { useRef, useState, useEffect } from "react";
import { formatFileSize, isFileSizeValid } from "../../utils/fileUtils";
import { getUploadUrl, getApiBase } from "../../utils/apiBase";
import { sha256OfFile } from "../../utils/hashUtil";
import Logger from "../../utils/logger";

// 地理与数据主题的上传提示语
const FUNNY_UPLOAD_MESSAGES = [
  "正在把数据钉到真实世界中...",
  "正在教数据找到自己的地理位置...",
  "正在为坐标安排一个地球上的家...",
  "正在把混乱数据转换成漂亮的地理数据...",
  "正在和卫星协商更好的接收质量...",
  "正在整理空间数据的小宇宙...",
  "正在丈量困惑与清晰之间的距离...",
  "正在数据集中寻找正北方向...",
  "正在把数据翻译成地球语言...",
  "正在穿越地理维度传输文件...",
  "正在为数据点画出看不见的联系...",
  "正在沿着文件结构做 GPS 导航...",
  "正在让地球妈妈为你的数据骄傲...",
  "正在说服数据留在地图边界内...",
  "正在请求地图为新图层腾位置...",
  "正在把地理数据归档进地球抽屉...",
  "正在计算通往优秀地图的最短路径...",
  "正在把数据指向正确方向...",
  "正在给坐标办理地图通行证...",
  "正在与国际日期变更线同步...",
];

const FUNNY_STYLING_MESSAGES = [
  "正在给数据培养一点审美...",
  "正在用 AI 魔法点亮灰色图形...",
  "正在挑选让制图师会心一笑的配色...",
  "正在给数据做一次地图杂志级改造...",
  "正在向色彩理论请教灵感...",
  "正在给地理要素上数字妆容...",
  "正在为地理舞会打扮数据...",
  "正在调和像素与多边形的完美色盘...",
  "正在把数据从普通变成出彩...",
  "正在让图层漂亮到让其他地图羡慕...",
  "正在把数据集变成好看的视觉舞台...",
  "正在创作一幅 GIS 风格作品...",
  "正在为每个要素刷上快乐的小色块...",
  "正在给多边形做专业修饰...",
  "正在寻找数据专属的惊艳色调...",
  "正在给地理现实加一点滤镜...",
  "正在让数据表达内在美...",
  "正在用人工智能的画笔绘制数据...",
  "正在让地图美到卫星都想合影...",
  "正在创作一件地理空间杰作...",
];

const FUNNY_FINALIZING_MESSAGES = [
  "正在优雅地冲过终点线...",
  "正在为这份地理礼物系上最后的蝴蝶结...",
  "正在庆祝数据成功变身...",
  "正在命中制图完美靶心...",
  "正在准备把图层发射到地图平流层...",
  "正在添加最后一点地理光泽...",
  "正在给数据颁发可视化金牌...",
  "正在为新图层铺上红毯...",
  "正在撒上最后一点制图星尘...",
  "正在为完成样式的数据开个小庆功会...",
  "正在为图层登场准备气球...",
  "正在为这场地理表演谢幕...",
  "正在把数据擦亮到地图上闪闪发光...",
  "正在为制图作品签名...",
  "正在给表现出色的数据别上一枚奖章...",
];

function getRandomMessage(messages: string[]): string {
  return messages[Math.floor(Math.random() * messages.length)];
}

interface UploadSectionProps {
  addLayer: (layer: any) => void;
  updateLayerStyle: (layerId: string, style: any) => void;
}

export default function UploadSection({
  addLayer,
  updateLayerStyle,
}: UploadSectionProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const xhrRef = useRef<XMLHttpRequest | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [currentFileIndex, setCurrentFileIndex] = useState<number>(0);
  const [totalFiles, setTotalFiles] = useState<number>(0);
  const [currentFileName, setCurrentFileName] = useState<string>("");
  const [funnyMessage, setFunnyMessage] = useState<string>("");

  const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100MB in bytes
  const MAX_FILE_SIZE_FORMATTED = formatFileSize(MAX_FILE_SIZE);

  // Rotate funny messages during upload for entertainment
  useEffect(() => {
    if (!isUploading) return;

    const messageRotationInterval = setInterval(() => {
      if (uploadProgress < 70) {
        setFunnyMessage(getRandomMessage(FUNNY_UPLOAD_MESSAGES));
      } else if (uploadProgress < 100) {
        setFunnyMessage(getRandomMessage(FUNNY_STYLING_MESSAGES));
      } else {
        setFunnyMessage(getRandomMessage(FUNNY_FINALIZING_MESSAGES));
      }
    }, 3000); // Change message every 3 seconds

    return () => clearInterval(messageRotationInterval);
  }, [isUploading, uploadProgress]);

  const cancelUpload = () => {
    if (xhrRef.current) {
      xhrRef.current.abort();
      xhrRef.current = null;
      setIsUploading(false);
      setUploadProgress(0);
      setCurrentFileIndex(0);
      setTotalFiles(0);
      setCurrentFileName("");
      setFunnyMessage("");
      setUploadError("上传已由用户取消");
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;

    // Clear any previous error message
    setUploadError(null);
    setIsUploading(true);
    setUploadProgress(0);
    setTotalFiles(files.length);
    setCurrentFileIndex(0);

    const API_UPLOAD_URL = getUploadUrl();
    const API_BASE_URL = getApiBase();
    const newLayers: any[] = [];

    try {
      // Process each file sequentially
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setCurrentFileIndex(i + 1);
        setCurrentFileName(file.name);

        // Set a funny upload message
        setFunnyMessage(getRandomMessage(FUNNY_UPLOAD_MESSAGES));

        // Check file size limit
        if (!isFileSizeValid(file, MAX_FILE_SIZE)) {
          throw new Error(
            `文件 ${file.name} 大小为 ${formatFileSize(file.size)}，超过 ${MAX_FILE_SIZE_FORMATTED} 限制。`,
          );
        }

        // Upload phase (0-70% of total progress for this file)
        const baseProgress = (i / files.length) * 100;
        const uploadPhaseProgress = (progressPercent: number) => {
          const fileProgress =
            baseProgress + (progressPercent * 0.7) / files.length;
          setUploadProgress(Math.round(fileProgress));
        };

        // assemble form data
        const formData = new FormData();
        formData.append("file", file);

        // Upload the file
        // Compute SHA-256 locally before upload for integrity verification
        const localSha256 = await sha256OfFile(file);

        const { url, id } = await new Promise<{ url: string; id: string }>(
          (resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhrRef.current = xhr;

            xhr.open("POST", API_UPLOAD_URL);

            // Set up progress tracking for upload phase
            xhr.upload.onprogress = (event) => {
              if (event.lengthComputable) {
                const percentComplete = Math.round(
                  (event.loaded / event.total) * 100,
                );
                uploadPhaseProgress(percentComplete);
              }
            };

            xhr.onload = () => {
              if (xhr.status >= 200 && xhr.status < 300) {
                try {
                  const data = JSON.parse(xhr.responseText);
                  resolve(data);
                } catch (error) {
                  reject(new Error("响应不是有效的 JSON"));
                }
              } else {
                try {
                  const errorData = JSON.parse(xhr.responseText);
                  reject(new Error(errorData.detail || "上传失败"));
                } catch (e) {
                  reject(new Error(`上传失败：${xhr.statusText}`));
                }
              }
            };

            xhr.onerror = () => reject(new Error("发生网络错误"));
            xhr.ontimeout = () => reject(new Error("上传超时"));
            xhr.onabort = () => reject(new Error("上传已由用户取消"));

            xhr.send(formData);
          },
        );

        // Upload completed, update progress to 70%
        const uploadCompleteProgress = baseProgress + 70 / files.length;
        setUploadProgress(Math.round(uploadCompleteProgress));

        // Verify integrity against backend-reported hash/size
        try {
          const metaRes = await fetch(
            `${API_BASE_URL}/uploads/meta/${encodeURIComponent(id)}`,
          );
          if (metaRes.ok) {
            const meta = await metaRes.json();
            const isConverted = ['zip', 'kml', 'csv'].some(ext => file.name.toLowerCase().endsWith(`.${ext}`));
            if (!isConverted && meta?.sha256 && typeof meta.sha256 === "string") {
              if (meta.sha256.toLowerCase() !== localSha256.toLowerCase()) {
                throw new Error(
                  `文件 ${file.name} 完整性校验失败。期望 ${localSha256.slice(0, 8)}…，实际为 ${String(meta.sha256).slice(0, 8)}…`,
                );
              }
            }
            if (!isConverted && meta?.size && Number.isFinite(Number(meta.size))) {
              const serverSize = Number(meta.size);
              if (serverSize !== file.size) {
                throw new Error(
                  `文件 ${file.name} 大小不一致。本地为 ${file.size} 字节，服务器为 ${serverSize} 字节。`,
                );
              }
            }
          } else {
            Logger.warn(
              "Upload meta endpoint returned",
              metaRes.status,
              metaRes.statusText,
            );
          }
        } catch (verifyErr) {
          // Surface integrity failure to the user and abort processing this file
          throw verifyErr instanceof Error
            ? verifyErr
            : new Error(String(verifyErr));
        }

        // Create the new layer
        const newLayer = {
          id: id,
          name: file.name,
          data_type: "uploaded",
          data_link: url,
          visible: true,
          data_source_id: "manual",
          data_origin: "uploaded",
          data_source: "user",
          layer_type: "UPLOADED",
        };

        // Add to store
        addLayer(newLayer);
        newLayers.push(newLayer);

        // Styling phase (70-100% of total progress for this file)
        const stylingPhaseProgress = (percent: number) => {
          const fileProgress =
            baseProgress + 70 / files.length + (percent * 0.3) / files.length;
          setUploadProgress(Math.round(fileProgress));
        };

        // Apply automatic AI styling
        try {
          stylingPhaseProgress(0); // Start styling phase

          // Set a funny styling message
          setFunnyMessage(getRandomMessage(FUNNY_STYLING_MESSAGES));

          const styleResponse = await fetch(`${API_BASE_URL}/ai-style`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              query: `Auto-style the layer "${newLayer.name}"`,
              geodata_layers: [newLayer],
            }),
          });

          stylingPhaseProgress(50); // Halfway through styling

          if (styleResponse.ok) {
            const styleResult = await styleResponse.json();
            if (styleResult.success && styleResult.styled_layers.length > 0) {
              const styledLayer = styleResult.styled_layers[0];
              // Update the layer with the AI-generated styling
              if (styledLayer.style) {
                updateLayerStyle(id, styledLayer.style);
                Logger.log(
                  `Applied automatic AI styling to layer: ${file.name}`,
                );
              }
            }
          } else {
            Logger.warn(
              "Automatic styling request failed:",
              styleResponse.statusText,
            );
          }

          stylingPhaseProgress(100); // Styling complete

          // Set a funny finalizing message
          setFunnyMessage(getRandomMessage(FUNNY_FINALIZING_MESSAGES));
        } catch (autoStyleError) {
          Logger.warn("Error applying automatic styling:", autoStyleError);
          stylingPhaseProgress(100); // Still mark as complete even if styling fails

          // Set a funny finalizing message even if styling fails
          setFunnyMessage(getRandomMessage(FUNNY_FINALIZING_MESSAGES));
        }
      }

      // All files processed successfully
      setUploadProgress(100);
      Logger.log(`Successfully uploaded and styled ${files.length} file(s)`);
    } catch (err) {
      if (err instanceof Error && err.message === "上传已由用户取消") {
        Logger.log("上传已由用户取消");
      } else {
        setUploadError(
          `上传错误：${err instanceof Error ? err.message : String(err)}`,
        );
        Logger.error("Error uploading files:", err);
      }
    } finally {
      // reset so same files can be re‑picked
      e.target.value = "";
      setIsUploading(false);
      setUploadProgress(0);
      setCurrentFileIndex(0);
      setTotalFiles(0);
      setCurrentFileName("");
      setFunnyMessage("");
      xhrRef.current = null;
    }
  };

  return (
    <div className="mb-4">
      <h3 className="font-semibold mb-2">上传数据</h3>
      <div
        className={`border border-dashed border-primary-400 p-4 rounded bg-primary-100 text-center cursor-pointer ${isUploading ? "opacity-75" : ""}`}
        onClick={() => !isUploading && fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".geojson,.zip,.kml,.csv"
          onChange={handleFileUpload}
          className="hidden"
          disabled={isUploading}
          multiple
        />
        {isUploading ? (
          <div className="flex flex-col items-center justify-center">
            <div className="w-full max-w-xs bg-primary-200 rounded-full h-2.5 mb-2">
              <div
                className="bg-info-600 h-2.5 rounded-full transition-all duration-300"
                style={{ width: `${uploadProgress}%` }}
              ></div>
            </div>
            <p className="text-sm text-info-600">{uploadProgress}% 完成</p>
            {totalFiles > 1 && (
              <p className="text-xs text-neutral-600">
                文件 {currentFileIndex} / {totalFiles}
              </p>
            )}
            {currentFileName && (
              <p className="text-xs text-neutral-500 mt-1 truncate max-w-xs">
                {currentFileName}
              </p>
            )}
            <p className="text-xs text-neutral-400 mt-1 text-center italic">
              {funnyMessage ||
                (uploadProgress < 70
                  ? "上传中..."
                  : uploadProgress < 100
                    ? "正在应用 AI 样式..."
                    : "正在完成...")}
            </p>
            <button
              onClick={(e) => {
                e.stopPropagation(); // Prevent triggering the file input click
                cancelUpload();
              }}
              className="mt-2 px-3 py-1 bg-danger-100 text-danger-700 text-xs rounded hover:bg-danger-200 transition-colors"
            >
              取消上传
            </button>
          </div>
        ) : (
          <>
            <p className="text-sm text-neutral-500">
              拖放或点击上传 GeoJSON 文件
            </p>
            <p className="text-xs text-neutral-400 mt-1">
              支持多文件上传 • 最大大小：{MAX_FILE_SIZE_FORMATTED}
            </p>
            <p className="text-xs text-neutral-400">格式：支持 .geojson, .zip, .kml, .csv</p>
          </>
        )}
      </div>
      {uploadError && (
        <div className="mt-2 p-2 bg-danger-100 border border-danger-400 text-danger-700 text-sm rounded">
          {uploadError}
        </div>
      )}
    </div>
  );
}
