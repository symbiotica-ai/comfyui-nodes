// ABOUTME: Frontend extension for NSVideoConcatMulti node
// ABOUTME: Adds dynamic input expansion via "Update inputs" button

import { app } from "../../../scripts/app.js";

app.registerExtension({
    name: "neuralsins.videoConcatMulti",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "NSVideoConcatMulti") {
            return;
        }

        nodeType.prototype.onNodeCreated = function () {
            const settingsInputs = [
                { name: "transition_settings", type: "TRANSITION_SETTINGS" },
                { name: "effects_settings", type: "EFFECTS_SETTINGS" },
                { name: "overlay_settings", type: "OVERLAY_SETTINGS" },
                { name: "visual_cues_settings", type: "VISUAL_CUES_SETTINGS" },
                { name: "caption_settings", type: "CAPTION_SETTINGS" },
            ];

            // Save and remove all settings inputs, returning their connection info
            const detachSettings = () => {
                const saved = [];
                for (const { name, type } of settingsInputs) {
                    const idx = this.inputs.findIndex(input => input.name === name);
                    if (idx < 0) continue;
                    let originInfo = null;
                    const linkId = this.inputs[idx].link;
                    if (linkId != null) {
                        const link = app.graph.links[linkId];
                        if (link) {
                            originInfo = { nodeId: link.origin_id, slot: link.origin_slot };
                        }
                    }
                    this.removeInput(idx);
                    saved.push({ name, type, originInfo });
                }
                return saved;
            };

            // Re-add settings inputs at the end and restore connections
            const reattachSettings = (saved) => {
                for (const { name, type, originInfo } of saved) {
                    this.addInput(name, type, { shape: 7 });
                    if (originInfo) {
                        const originNode = app.graph.getNodeById(originInfo.nodeId);
                        if (originNode) {
                            originNode.connect(originInfo.slot, this, this.inputs.length - 1);
                        }
                    }
                }
            };

            // Ensure video inputs always appear before settings inputs
            const reorderInputs = () => {
                const settingsNames = new Set(settingsInputs.map(s => s.name));
                // Check if any settings input appears before a video input
                let lastVideoIdx = -1;
                let firstSettingsIdx = Infinity;
                for (let i = 0; i < this.inputs.length; i++) {
                    if (this.inputs[i].name.startsWith("video_")) lastVideoIdx = i;
                    if (settingsNames.has(this.inputs[i].name) && i < firstSettingsIdx) firstSettingsIdx = i;
                }
                if (lastVideoIdx > firstSettingsIdx) {
                    const saved = detachSettings();
                    reattachSettings(saved);
                }
            };

            this.addWidget("button", "Update inputs", null, () => {
                const target = this.widgets.find(w => w.name === "inputcount")["value"];
                const videoInputs = this.inputs.filter(input => input.name.startsWith("video_"));
                const current = videoInputs.length;

                if (target === current) return;

                const videoType = videoInputs[0]?.type || "VIDEO";

                if (target < current) {
                    for (let i = current; i > target; i--) {
                        const idx = this.inputs.findIndex(input => input.name === `video_${i}`);
                        if (idx >= 0) this.removeInput(idx);
                    }
                } else {
                    const saved = detachSettings();
                    for (let i = current + 1; i <= target; i++) {
                        this.addInput(`video_${i}`, videoType, { shape: 7 });
                    }
                    reattachSettings(saved);
                }

                reorderInputs();
            });

            // Fix order on workflow load (configure runs after onNodeCreated)
            const origConfigure = this.configure?.bind(this);
            this.configure = function (data) {
                origConfigure?.(data);
                reorderInputs();
            };
        };
    }
});
