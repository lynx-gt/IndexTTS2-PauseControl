// IndexTTS-Node 前端扩展：动态下拉（任务 → 段 联动；参考音频列表）
import { app } from "../../scripts/app.js";

async function fetchJSON(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  }
}

function findWidget(node, name) {
  return node.widgets ? node.widgets.find((w) => w.name === name) : null;
}

app.registerExtension({
  name: "IndexTTS-Node.UI",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    // 候选试听节点：任务下拉 + 段号下拉联动
    if (nodeData.name === "IndexTTSListen") {
      const onNodeCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = async function () {
        const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
        const taskWidget = findWidget(this, "task");
        const segWidget = findWidget(this, "segment");
        if (!taskWidget || !segWidget) return r;

        const loadSegs = async (taskPath) => {
          const name = encodeURIComponent(String(taskPath || "").split(/[\\/]/).pop());
          const segs = await fetchJSON(`/indextts/tasks/${name}/segments`);
          if (segs) {
            segWidget.options.values = segs.map((s) => String(s.id));
            segWidget.value = segWidget.options.values[0] ?? "1";
          }
        };

        const origCb = taskWidget.callback;
        taskWidget.callback = async (v) => {
          if (origCb) origCb(v);
          await loadSegs(v);
        };

        const tasks = await fetchJSON("/indextts/tasks");
        if (tasks && tasks.length) {
          taskWidget.options.values = tasks.map((t) => t.path);
          taskWidget.value = taskWidget.options.values[0];
          await loadSegs(taskWidget.value);
        }
        return r;
      };
    }
    // 单条生成 / 批量生成：参考音频下拉（音色、情感）
    if (nodeData.name === "IndexTTSSingle" || nodeData.name === "IndexTTSBatch") {
      const onNodeCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = async function () {
        const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
        const refs = await fetchJSON("/indextts/refs");
        if (!refs) return r;
        const spkW = findWidget(this, "spk_ref");
        const emoW = findWidget(this, "emo_ref");
        if (spkW) {
          spkW.options.values = [...refs];
          spkW.serialize = false;
        }
        if (emoW) {
          emoW.options.values = ["", ...refs];
          emoW.serialize = false;
        }
        return r;
      };
    }
  },
});
